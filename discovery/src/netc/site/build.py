"""`netc build-site`: render the static site from data/ (T064; contracts/site-urls.md).

Pages: ``/`` (upcoming, soonest first), ``/events/<slug>/`` (one per public event),
``/about/``, and ``/404.html`` for unknown paths. Only events that are published, shown, and
not over are listed. Templates escape everything (Jinja autoescape) and contain no inline
scripts or styles. ``web/`` assets (CSS, JS, ``_headers``) are copied; tooling files are not.
Public data files hold public fields only.
"""

from __future__ import annotations

import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from jinja2 import Environment, PackageLoader, StrictUndefined

from netc.fetch.robots import ROBOTS_USER_AGENT
from netc.models import AreaConfig, Event
from netc.pipeline.overrides import apply_overrides
from netc.pipeline.timeutil import format_central
from netc.storage import DataStore, atomic_write, dump_json

PUBLIC_FIELDS: Final = (
    "id", "slug", "title", "start", "end", "all_day", "area", "location", "organizer", "summary",
    "categories", "original_url", "status", "last_verified", "inferred", "original_unavailable",
)  # fmt: skip
WEB_ASSETS: Final = ("css", "js", "vendor", "img", "fonts", "_headers", "favicon.ico", "robots.txt")
REPO_URL: Final = "https://github.com/timbertino1/CommunityTechConnect"
INFERRED_LABELS: Final = {"area": "area", "categories": "topics", "source_tz": "time zone"}


class BuildError(Exception):
    """The site could not be built (e.g. an unsafe output directory)."""


@dataclass
class BuildReport:
    pages: int
    events_listed: int


def build_site(
    data_dir: Path, out_dir: Path, web_dir: Path, *, now: datetime, site_domain: str
) -> BuildReport:
    store = DataStore(data_dir)
    categories = {c.id: c.label for c in store.read_categories()}
    areas = store.read_areas()
    area_labels: dict[str, str] = {a.id: a.label for a in areas.areas} if areas else {}
    organizers = {o.id: o.name for o in store.read_organizers()}
    source_names = {s.id: s.name for s in store.read_sources()}

    # Applied here too, so a merged override shows up at the next deploy.
    events = apply_overrides(store.read_events(), store.read_overrides())
    public = [e for e in events if e.is_public]
    upcoming = sorted(
        (e for e in public if (e.end or e.start) > now), key=lambda e: (e.start, e.id)
    )

    _prepare(out_dir)
    env = Environment(
        loader=PackageLoader("netc", "site/templates"),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    common = {"updated": format_central(now, None, all_day=False)}

    def organizer_of(event: Event) -> str | None:
        if event.organizer_id and event.organizer_id in organizers:
            return organizers[event.organizer_id]
        return source_names.get(event.listings[0].source_id) if event.listings else None

    views = {e.id: _view(e, organizer_of(e), categories, area_labels) for e in public}
    pages = 0
    _write(out_dir / "index.html", env.get_template("list.html").render(
        nav="upcoming", events=[views[e.id] for e in upcoming], **common))  # fmt: skip
    pages += 1
    for event in public:
        _write(
            out_dir / "events" / event.slug / "index.html",
            env.get_template("event.html").render(nav="", e=views[event.id], **common),
        )
        pages += 1
    _write(
        out_dir / "about" / "index.html",
        env.get_template("about.html").render(
            nav="about",
            user_agent=f"{ROBOTS_USER_AGENT}/1.0 (+https://{site_domain}/about)",
            repo_url=REPO_URL,
            repo_host="github.com/timbertino1/CommunityTechConnect",
            **common,
        ),
    )
    pages += 1
    # Without 404.html, Cloudflare Pages serves index.html with a 200 for every unknown path.
    _write(out_dir / "404.html", env.get_template("404.html").render(nav="", **common))
    pages += 1

    _copy_web(web_dir, out_dir)
    atomic_write(
        out_dir / "data" / "upcoming.json",
        dump_json([_public_record(e, organizer_of(e)) for e in upcoming]),
    )
    atomic_write(
        out_dir / "data" / "meta.json",
        dump_json(
            {
                "categories": [{"id": cid, "label": label} for cid, label in categories.items()],
                "areas": [{"id": aid, "label": label} for aid, label in area_labels.items()],
                "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ),
    )
    atomic_write(out_dir / "data" / "map.json", dump_json(_map_data(upcoming, areas)))
    return BuildReport(pages=pages, events_listed=len(upcoming))


def _map_data(upcoming: list[Event], areas: AreaConfig | None) -> dict[str, Any]:
    """The header map's towns, and a pin per city with upcoming in-person events (T152).
    Cancelled and online events get no pin, nor does a city missing from the points table."""
    points = areas.points if areas else {}
    counts: Counter[str] = Counter()
    for event in upcoming:
        if areas is None or event.status == "cancelled" or event.location.online:
            continue
        if found := areas.map_point(event.location.city):
            counts[found[0]] += 1
    return {
        "towns": [{"name": n, "lat": p.lat, "lon": p.lon} for n, p in sorted(points.items())],
        "pins": [
            {"city": n, "lat": points[n].lat, "lon": points[n].lon, "events": c}
            for n, c in sorted(counts.items())
        ],
    }


def _view(
    event: Event, organizer: str | None, categories: dict[str, str], areas: dict[str, str]
) -> dict[str, Any]:
    location = event.location
    if location.online and not location.venue:
        where = "Online"
    else:
        parts = [p for p in (location.venue, location.city) if p]
        where = ", ".join(dict.fromkeys(parts)) or areas.get(event.area, "Nebraska")
        if location.online:
            where += " and online"
    others = [
        {"url": listing.url, "host": _host(listing.url)}
        for listing in event.listings
        if listing.url != event.original_url
    ]
    inferred = [INFERRED_LABELS[f] for f in event.inferred if f in INFERRED_LABELS]
    return {
        "id": event.id,
        "slug": event.slug,
        "title": event.title,
        "status": event.status,
        "when": format_central(event.start, event.end, all_day=event.all_day),
        "start_iso": event.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "where": where,
        "where_full": location.address or where,
        "organizer": organizer,
        "category_labels": [categories.get(c, c) for c in event.categories],
        "summary": event.summary,
        "original_url": event.original_url,
        "host": _host(event.original_url),
        "original_unavailable": event.original_unavailable,
        "also_listed": list({o["url"]: o for o in others}.values()),
        "last_verified": format_central(event.last_verified, None, all_day=False),
        "inferred_note": (
            f"The {' and '.join(inferred)} were worked out by NETechConnect, "
            "not stated by the organizer."
            if inferred
            else ""
        ),
    }


def _public_record(event: Event, organizer: str | None) -> dict[str, Any]:
    data = event.model_dump(mode="json")
    data["organizer"] = organizer
    return {field: data.get(field) for field in PUBLIC_FIELDS}


def _host(url: str) -> str:
    return urlsplit(url).hostname or url


def _prepare(out_dir: Path) -> None:
    """Start from an empty output directory, refusing to wipe anything that isn't a build."""
    if out_dir.exists():
        contents = list(out_dir.iterdir())
        if contents and not (out_dir / "index.html").exists():
            raise BuildError(f"{out_dir} is not empty and does not look like a previous build")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)


def _write(path: Path, html: str) -> None:
    atomic_write(path, html.encode("utf-8"))


def _copy_web(web_dir: Path, out_dir: Path) -> None:
    for name in WEB_ASSETS:
        source = web_dir / name
        if source.is_dir():
            for file in sorted(source.rglob("*")):
                if file.is_file() and file.name != ".gitkeep":
                    atomic_write(out_dir / name / file.relative_to(source), file.read_bytes())
        elif source.is_file():
            atomic_write(out_dir / name, source.read_bytes())
