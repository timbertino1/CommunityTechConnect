"""Helpers for site-build tests: a small data directory and a build runner."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from netc.cli import main
from netc.models import Event, Organizer
from netc.storage import DataStore
from tests.data_samples import make_event, make_source, utc

ROOT = Path(__file__).resolve().parents[2]
REPO_DATA = ROOT / "data"
WEB = ROOT / "web"
NOW = "2026-10-18T12:00:00Z"
NOW_DT = utc(2026, 10, 18, 12)


def site_event(
    url: str,
    title: str,
    start: datetime,
    slug: str,
    **overrides: Any,
) -> Event:
    data: dict[str, Any] = {"organizer_id": "org_prairie-python", "categories": ["software-dev"]}
    data.update(overrides)
    return make_event(slug=slug, start=start, url=url, title=title, **data)


def make_data(root: Path, events: list[Event]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("categories.yaml", "areas.yaml"):
        shutil.copy(REPO_DATA / name, root / name)
    store = DataStore(root)
    store.write_source(make_source())
    store.write_organizers(
        [Organizer(id="org_prairie-python", name="Prairie Python", home_city="Omaha")]
    )
    store.write_events(events)
    return root


def build(data: Path, out: Path) -> int:
    return main(
        ["build-site", "--data", str(data), "--out", str(out), "--web", str(WEB), "--now", NOW]
    )


def html_files(out: Path) -> dict[str, str]:
    return {
        p.relative_to(out).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(out.rglob("*.html"))
    }
