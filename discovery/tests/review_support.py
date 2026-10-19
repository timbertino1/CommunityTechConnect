"""Shared setup for the review PR tests: held events, their queue items, and a data folder."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netc.models import Event, ReviewItem, Source
from netc.pipeline.lifecycle import review_id_for
from netc.storage import DataStore
from tests.data_samples import make_event, make_source, utc

REPO_DATA = Path(__file__).resolve().parents[2] / "data"
NOW = datetime(2026, 10, 19, 11, 0, tzinfo=UTC)
CATEGORIES = {"software-dev": "Software development", "ai-ml": "AI & ML"}
AREAS = {"omaha": "Omaha", "lincoln": "Lincoln"}


def held_event(n: int, *, source_id: str = "src_campus", **overrides: Any) -> Event:
    data: dict[str, Any] = {
        "slug": f"campus-talk-{n}-2026-11-{n:02d}",
        "start": utc(2026, 11, n, 18, 0),
        "url": f"https://events.campus.example.edu/{n}/",
        "source_id": source_id,
        "title": f"Campus talk {n}",
        "review_state": "pending_review",
    }
    data.update(overrides)
    return make_event(**data)


def queue_item(event: Event, **overrides: Any) -> ReviewItem:
    data: dict[str, Any] = {
        "id": review_id_for(event.id),
        "kind": "event",
        "ref": event.id,
        "reason": "new event from a probationary source",
        "created": utc(2026, 10, 18, 23),
    }
    data.update(overrides)
    return ReviewItem.model_validate(data)


def campus_source(**overrides: Any) -> Source:
    data: dict[str, Any] = {
        "name": "Campus computing",
        "url": "https://events.campus.example.edu/",
        "trust": "probationary",
        "origin": "admin",
    }
    data.update(overrides)
    return make_source("src_campus", **data)


def make_review_data(
    root: Path,
    events: list[Event],
    queue: list[ReviewItem],
    sources: list[Source] | None = None,
    open_ids: list[str] | None = None,
) -> DataStore:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("categories.yaml", "areas.yaml"):
        shutil.copy(REPO_DATA / name, root / name)
    store = DataStore(root)
    for source in sources if sources is not None else [campus_source()]:
        store.write_source(source)
    store.write_events(events)
    store.write_review_queue(queue)
    store.write_review_open(open_ids if open_ids is not None else [q.id for q in queue])
    return store


def tick(body: str, review_id: str, *boxes: str) -> str:
    """Tick the named boxes ("approve", "reject") under one item, as GitHub does on click."""
    lines = body.splitlines()
    inside = False
    for i, line in enumerate(lines):
        if line.startswith("**") and line.endswith("`"):
            inside = line.endswith(f"`{review_id}`")
            continue
        for box in boxes:
            if inside and line == f"- [ ] {box}":
                lines[i] = f"- [x] {box}"
    return "\n".join(lines) + "\n"
