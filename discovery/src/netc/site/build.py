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
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from jinja2 import Environment, PackageLoader, StrictUndefined

from netc.fetch.robots import ROBOTS_USER_AGENT
from netc.models import AreaConfig, Event
from netc.pipeline.overrides import apply_overrides
from netc.pipeline.timeutil import clock_time, format_central, short_day, to_central
from netc.site import calendar as cal
from netc.storage import DataStore, atomic_write, dump_json

PUBLIC_FIELDS: Final = (
    "id", "slug", "title", "start", "end", "all_day", "area", "location", "organizer", "summary",
    "categories", "original_url", "status", "last_verified", "inferred", "original_unavailable",
)  # fmt: skip
WEB_ASSETS: Final = ("css", "js", "vendor", "img", "fonts", "_headers", "favicon.ico", "robots.txt")
REPO_URL: Final = "https://github.com/timbertino1/CommunityTechConnect"
PAST_PAGE_SIZE: Final = 50
# The suggestion form (T132). SUGGEST_ENDPOINT is the deployed Worker's /suggest URL (T134); until
# it is set, the /suggest/ page and its links are left out, so nothing half-working goes live.
SUGGEST_ENDPOINT: Final[str | None] = "https://netc-suggest.tim-bertino.workers.dev/suggest"
TURNSTILE_SITE_KEY: Final = "0x4AAAAAAFjOWyUQYlRhF1wP"  # public; the secret is a Worker secret
TURNSTILE_HOST: Final = "https://challenges.cloudflare.com"
"""Past events per page of /past/ (T117); older ones are on /past/page/<n>/."""
INFERRED_LABELS: Final = {"area": "area", "categories": "topics", "source_tz": "time zone"}


class BuildError(Exception):
    """The site could not be built (e.g. an unsafe output directory)."""


@dataclass
class BuildReport:
    pages: int
    events_listed: int


def build_site(
    data_dir: Path,
    out_dir: Path,
    web_dir: Path,
    *,
    now: datetime,
    site_domain: str,
    suggest_endpoint: str | None = SUGGEST_ENDPOINT,
) -> BuildReport:
    if suggest_endpoint and not suggest_endpoint.startswith("https://"):
        raise BuildError(f"the suggestion endpoint must be an https URL: {suggest_endpoint!r}")
    store = DataStore(data_dir)
    categories = {c.id: c.label for c in store.read_categories()}
    areas = store.read_areas()
    area_labels: dict[str, str] = {a.id: a.label for a in areas.areas} if areas else {}
    organizers = {o.id: o.name for o in store.read_organizers()}
    sources = store.read_sources()
    source_names = {s.id: s.name for s in sources}

    # Applied here too, so a merged override shows up at the next deploy.
    events = apply_overrides(store.read_events(), store.read_overrides())
    public = [e for e in events if e.is_public]
    upcoming = sorted(
        (e for e in public if (e.end or e.start) > now), key=lambda e: (e.start, e.id)
    )
    # FR-035: past once it has ended; listed most recent first (FR-034).
    past = sorted(
        (e for e in public if (e.end or e.start) <= now),
        key=lambda e: (e.start, e.id),
        reverse=True,
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
    this_month = cal.current_month(now)
    common = {
        "updated": format_central(now, None, all_day=False),
        "repo_url": REPO_URL,
        # Where the nav's Calendar link goes once filters.js adds the filters (T113): /calendar/
        # itself is a redirect, which would drop them.
        "calendar_now": f"/calendar/{this_month[0]}/{this_month[1]:02d}/",
        # The filter form's choices (_filters.html, on the list and calendar pages).
        "filter_areas": [(a, label) for a, label in area_labels.items()],
        "filter_topics": list(categories.items()),
        "suggest": (
            {"endpoint": suggest_endpoint, "site_key": TURNSTILE_SITE_KEY}
            if suggest_endpoint
            else None
        ),
    }

    def organizer_of(event: Event) -> str | None:
        if event.organizer_id and event.organizer_id in organizers:
            return organizers[event.organizer_id]
        return source_names.get(event.listings[0].source_id) if event.listings else None

    views = {e.id: _view(e, organizer_of(e), categories, area_labels) for e in public}
    pages = 0
    _write(
        out_dir / "index.html",
        env.get_template("list.html").render(
            nav="upcoming",
            past=False,
            events=[views[e.id] for e in upcoming],
            months=_months([views[e.id] for e in upcoming]),
            counts={
                "upcoming": len(upcoming),
                "watched": sum(1 for s in sources if s.status == "active"),
            },
            **common,
        ),
    )
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
            repo_host="github.com/timbertino1/CommunityTechConnect",
            **common,
        ),
    )
    pages += 1
    pages += _past_pages(env, out_dir, [views[e.id] for e in past], common)
    if suggest_endpoint:
        _write(
            out_dir / "suggest" / "index.html",
            env.get_template("suggest.html").render(nav="suggest", **common),
        )
        pages += 1
    pages += _calendar_pages(env, out_dir, public, views, now, common)
    # Without 404.html, Cloudflare Pages serves index.html with a 200 for every unknown path.
    _write(out_dir / "404.html", env.get_template("404.html").render(nav="", **common))
    pages += 1

    _copy_web(web_dir, out_dir)
    if suggest_endpoint:
        _add_suggest_headers(out_dir / "_headers", suggest_endpoint)
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
    by_year: dict[int, list[dict[str, Any]]] = {}
    for event in past:
        year = to_central(event.start).year
        by_year.setdefault(year, []).append(_public_record(event, organizer_of(event)))
    for year, records in by_year.items():
        atomic_write(out_dir / "data" / "past" / f"{year}.json", dump_json(records))
    return BuildReport(pages=pages, events_listed=len(upcoming))


MONTH_NAMES: Final = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
WEEKDAYS: Final = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _calendar_pages(
    env: Environment,
    out_dir: Path,
    public: list[Event],
    views: dict[str, dict[str, Any]],
    now: datetime,
    common: dict[str, Any],
) -> int:
    """/calendar/ (to the current month), and a page per month and ISO week from 12 months
    back to 12 ahead (T109). Returns the number of pages written."""
    months = cal.months_around(now)
    weeks = cal.weeks_around(now)
    month_set, week_set = set(months), set(weeks)
    today = to_central(now).date()

    def month_link(month: cal.Month) -> dict[str, str] | None:
        if month not in month_set:
            return None
        return {"href": f"/calendar/{month[0]}/{month[1]:02d}/", "label": _month_label(month)}

    def week_link(week: cal.Week) -> dict[str, str] | None:
        if week not in week_set:
            return None
        return {"href": f"/calendar/{week[0]}/week/{week[1]:02d}/", "label": f"Week {week[1]}"}

    def day_view(day: date, events: list[Event], month: int | None) -> dict[str, Any]:
        return {
            "iso": day.isoformat(),
            "number": day.day,
            "label": short_day(day),
            "in_month": month is None or day.month == month,
            "today": day == today,
            "events": [_cal_entry(views[e.id], e, day) for e in events],
        }

    current = cal.current_month(now)
    _write(
        out_dir / "calendar" / "index.html",
        env.get_template("calendar_index.html").render(
            nav="calendar",
            current_href=f"/calendar/{current[0]}/{current[1]:02d}/",
            current_label=_month_label(current),
            **common,
        ),
    )
    pages = 1
    for month in months:
        grid = cal.month_weeks(*month)
        by_day = cal.events_by_day(public, [d for w in grid for d in w])
        rows = [
            {
                **(week_link(cal.iso_week(w[0])) or {}),
                "days": [day_view(d, by_day[d], month[1]) for d in w],
            }
            for w in grid
        ]
        _write(
            out_dir / "calendar" / str(month[0]) / f"{month[1]:02d}" / "index.html",
            env.get_template("calendar_month.html").render(
                nav="calendar",
                label=_month_label(month),
                weekdays=WEEKDAYS,
                weeks=rows,
                any_events=any(by_day[d] for w in grid for d in w if d.month == month[1]),
                prev=month_link(cal.prev_month(*month)),
                next=month_link(cal.next_month(*month)),
                **common,
            ),
        )
        pages += 1
    for week in weeks:
        days = cal.week_days(*week)
        by_day = cal.events_by_day(public, days)
        first, last = days[0], days[-1]
        dash = " \N{EN DASH} "
        end = str(last.day) if first.month == last.month else _month_day(last)
        span = f"{_month_day(first)}{dash}{end}"
        _write(
            out_dir / "calendar" / str(week[0]) / "week" / f"{week[1]:02d}" / "index.html",
            env.get_template("calendar_week.html").render(
                nav="calendar",
                label=f"Week {week[1]}: {span}, {last.year}",
                days=[day_view(d, by_day[d], None) for d in days],
                prev=week_link(cal.prev_week(*week)),
                next=week_link(cal.next_week(*week)),
                # The week's month; at the range's edges, the one of its two that has a page.
                month=month_link((first.year, first.month)) or month_link((last.year, last.month)),
                **common,
            ),
        )
        pages += 1
    return pages


def _month_label(month: tuple[int, int]) -> str:
    return f"{MONTH_NAMES[month[1] - 1]} {month[0]}"


def _month_day(day: date) -> str:
    """ "Nov 2"."""
    return f"{MONTH_NAMES[day.month - 1][:3]} {day.day}"


def _cal_entry(view: dict[str, Any], event: Event, day: date) -> dict[str, Any]:
    """One event on one calendar day: its start time on its first day, "All day", or
    "Continues" on the days after."""
    start = to_central(event.start)
    if event.all_day:
        time = "All day"
    elif start.date() == day:
        time = clock_time(start)
    else:
        time = "Continues"
    return {**view, "time": time}


def _past_pages(
    env: Environment, out_dir: Path, views: list[dict[str, Any]], common: dict[str, Any]
) -> int:
    """/past/ and /past/page/<n>/, PAST_PAGE_SIZE events each, most recent first (T117).
    Returns the number of pages written."""
    chunks = [views[i : i + PAST_PAGE_SIZE] for i in range(0, len(views), PAST_PAGE_SIZE)] or [[]]

    def href(number: int) -> str:
        return "/past/" if number == 1 else f"/past/page/{number}/"

    for number, chunk in enumerate(chunks, start=1):
        path = out_dir / "past" if number == 1 else out_dir / "past" / "page" / str(number)
        _write(
            path / "index.html",
            env.get_template("past.html").render(
                nav="past",
                past=True,
                events=chunk,
                months=_months(chunk),
                page=number,
                page_count=len(chunks),
                newer=href(number - 1) if number > 1 else None,
                older=href(number + 1) if number < len(chunks) else None,
                **common,
            ),
        )
    return len(chunks)


def _months(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Event views grouped by their Central Time month, in the order given."""
    months: list[dict[str, Any]] = []
    for view in views:
        if not months or months[-1]["name"] != view["month"]:
            months.append({"name": view["month"], "events": []})
        months[-1]["events"].append(view)
    for month in months:
        n = len(month["events"])
        month["count"] = f"{n} event" if n == 1 else f"{n} events"
    return months


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
    local = to_central(event.start)
    days = cal.days_spanned(event.start, event.end, all_day=event.all_day)
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
        "month": f"{local:%B %Y}",
        "date_block": {
            "month": f"{local:%b}".upper(),
            "day": str(local.day),
            "dow": f"{local:%a}",
        },
        "start_iso": event.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "where": where,
        "where_full": location.address or where,
        "organizer": organizer,
        "category_labels": [categories.get(c, c) for c in event.categories],
        "summary": event.summary,
        "original_url": event.original_url,
        "host": _host(event.original_url),
        "original_unavailable": event.original_unavailable,
        # For filters.js (T112, contracts/site-urls.md): the area, the topic ids, the Central
        # Time days covered, and the lowercase text that keyword search matches.
        "filter": {
            "area": event.area,
            "cats": " ".join(event.categories),
            "start": days[0].isoformat(),
            "end": days[-1].isoformat(),
            "search": " ".join(p for p in (event.title, organizer, event.summary) if p).lower(),
        },
        "also_listed": list({o["url"]: o for o in others}.values()),
        "last_verified": format_central(event.last_verified, None, all_day=False),
        "inferred_note": (
            f"The {_and_list(inferred)} were worked out by NETechConnect, "
            "not stated by the organizer."
            if inferred
            else ""
        ),
    }


def _public_record(event: Event, organizer: str | None) -> dict[str, Any]:
    data = event.model_dump(mode="json")
    data["organizer"] = organizer
    return {field: data.get(field) for field in PUBLIC_FIELDS}


def _and_list(items: list[str]) -> str:
    """ "topics", "topics and area", "topics, area and time zone"."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


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


def _add_suggest_headers(headers: Path, endpoint: str) -> None:
    """The /suggest/* block of contracts/site-urls.md, for the configured Worker. Pages adds a
    path's headers to those of /*, so the site-wide CSP is removed first (two CSPs would both
    apply and block Turnstile)."""
    worker = f"https://{urlsplit(endpoint).hostname}"
    csp = (
        f"default-src 'self'; script-src 'self' {TURNSTILE_HOST}; frame-src {TURNSTILE_HOST}; "
        f"connect-src 'self' {worker}; img-src 'self' data:; style-src 'self'; "
        f"object-src 'none'; base-uri 'none'; form-action {worker}; frame-ancestors 'none'"
    )
    text = headers.read_text(encoding="utf-8").rstrip("\n")
    block = f"/suggest/*\n  ! Content-Security-Policy\n  Content-Security-Policy: {csp}\n"
    atomic_write(headers, f"{text}\n\n{block}".encode())


def _copy_web(web_dir: Path, out_dir: Path) -> None:
    for name in WEB_ASSETS:
        source = web_dir / name
        if source.is_dir():
            for file in sorted(source.rglob("*")):
                if file.is_file() and file.name not in (".gitkeep", "README.md"):
                    atomic_write(out_dir / name / file.relative_to(source), file.read_bytes())
        elif source.is_file():
            atomic_write(out_dir / name, source.read_bytes())
