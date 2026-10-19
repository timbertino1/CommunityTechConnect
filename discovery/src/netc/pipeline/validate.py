"""`netc validate-data`: check every file in data/ against its schema, its model, and the
cross-file rules in data-model.md. All problems are collected and reported together.
"""

from __future__ import annotations

import functools
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from netc.models import (
    AreaConfig,
    CandidateSource,
    Category,
    Event,
    EventMention,
    KnownGroup,
    Organizer,
    Override,
    ReviewItem,
    Source,
    SourceStatus,
    load_schema,
)
from netc.storage import EVENT_FILE, StorageError, event_month_path, read_raw

MAX_MESSAGE: Final = 300
_SOURCE_KEY: Final = re.compile(r"^src_[a-z0-9-]{1,80}$")
_REVIEW_ID: Final = re.compile(r"^rev_[a-f0-9]{12}$")

# List files: (path under data/, schema name, model).
LIST_FILES: Final[tuple[tuple[str, str, type[BaseModel]], ...]] = (
    ("candidates.json", "candidate", CandidateSource),
    ("mentions.json", "mention", EventMention),
    ("review/queue.json", "review_item", ReviewItem),
    ("known_groups.yaml", "known_group", KnownGroup),
    ("organizers.yaml", "organizer", Organizer),
    ("categories.yaml", "category", Category),
    ("overrides.yaml", "override", Override),
)


@dataclass
class ValidationReport:
    root: Path
    errors: list[str] = field(default_factory=list)
    files_checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_MESSAGE else text[: MAX_MESSAGE - 1] + "\N{HORIZONTAL ELLIPSIS}"


@functools.cache
def _validator(schema_name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(schema_name))


@dataclass
class _Parsed:
    events: list[tuple[str, Event]] = field(default_factory=list)
    sources: dict[str, Source] = field(default_factory=dict)
    lists: dict[str, list[Any]] = field(default_factory=dict)
    open_ids: list[str] = field(default_factory=list)


class _Checker:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.report = ValidationReport(root)
        self.parsed = _Parsed()

    def error(self, where: str, message: str) -> None:
        self.report.errors.append(f"{where}: {_short(message)}")

    def load(self, path: Path) -> Any:
        self.report.files_checked += 1
        try:
            return read_raw(path)
        except StorageError as exc:
            self.error(self.rel(path), f"cannot be parsed ({exc.__cause__ or exc})")
            return _UNREADABLE

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def check_item[M: BaseModel](
        self, raw: Any, schema_name: str, model: type[M], where: str
    ) -> M | None:
        # Both checks always run so every problem is reported; a field the schema already
        # flagged is not reported a second time by the model.
        schema_errors = sorted(
            _validator(schema_name).iter_errors(raw), key=lambda e: list(e.absolute_path)
        )
        flagged: set[str] = set()
        for err in schema_errors:
            location = ".".join(str(part) for part in err.absolute_path) or "(record)"
            flagged.add(location)
            self.error(where, f"{location}: {err.message}")
        try:
            parsed = model.model_validate(raw)
        except ValidationError as exc:
            for detail in exc.errors():
                location = ".".join(str(part) for part in detail["loc"]) or "(record)"
                if location not in flagged and not any(
                    location.startswith(f"{f}.") for f in flagged
                ):
                    self.error(where, f"{location}: {detail['msg']}")
            return None
        return None if schema_errors else parsed

    # ------------------------------------------------------------ files

    def check_list_files(self) -> None:
        for relative, schema_name, model in LIST_FILES:
            path = self.root / relative
            if not path.exists():
                continue
            raw = self.load(path)
            if raw is _UNREADABLE:
                continue
            raw = [] if raw is None else raw
            if not isinstance(raw, list):
                self.error(relative, "expected a list of records")
                continue
            items = []
            for i, item in enumerate(raw):
                parsed = self.check_item(item, schema_name, model, f"{relative} [{i}]")
                if parsed is not None:
                    items.append(parsed)
            self.parsed.lists[relative] = items

    def check_events(self) -> None:
        events_dir = self.root / "events"
        if not events_dir.is_dir():
            return
        for path in sorted(events_dir.rglob("*.json")):
            relative = path.relative_to(events_dir).as_posix()
            where_file = f"events/{relative}"
            if not EVENT_FILE.match(relative):
                self.error(where_file, "event files must be named events/<YYYY>/<YYYY-MM>.json")
                continue
            raw = self.load(path)
            if raw is _UNREADABLE:
                continue
            if not isinstance(raw, list):
                self.error(where_file, "expected a list of events")
                continue
            for i, item in enumerate(raw):
                label = item.get("id", "") if isinstance(item, dict) else ""
                event = self.check_item(
                    item, "event", Event, f"{where_file} [{i}] {label}".rstrip()
                )
                if event is None:
                    continue
                expected = event_month_path(event)
                if expected != relative:
                    self.error(
                        f"{where_file} [{i}] {event.id}",
                        f"starts in events/{expected} (Central Time), not in this file",
                    )
                self.parsed.events.append((where_file, event))

    def check_sources(self) -> None:
        sources_dir = self.root / "sources"
        if not sources_dir.is_dir():
            return
        for path in sorted(sources_dir.glob("*.yaml")):
            relative = self.rel(path)
            raw = self.load(path)
            if raw is _UNREADABLE:
                continue
            source = self.check_item(raw, "source", Source, relative)
            if source is None:
                continue
            if path.stem != source.id:
                self.error(relative, f"file name must match the source id ({source.id}.yaml)")
            self.parsed.sources[source.id] = source

    def check_source_status(self) -> None:
        path = self.root / "state" / "source_status.json"
        if not path.exists():
            return
        raw = self.load(path)
        if raw is _UNREADABLE:
            return
        if not isinstance(raw, dict):
            self.error(self.rel(path), "expected an object keyed by source id")
            return
        for key, value in sorted(raw.items()):
            where = f"{self.rel(path)} {key}"
            if not _SOURCE_KEY.match(str(key)):
                self.error(where, "keys must be source ids (src_...)")
            self.check_item(value, "source_status", SourceStatus, where)

    def check_areas(self) -> None:
        path = self.root / "areas.yaml"
        if not path.exists():
            return
        raw = self.load(path)
        if raw is not _UNREADABLE:
            self.check_item(raw, "areas", AreaConfig, self.rel(path))

    def check_review_open(self) -> None:
        path = self.root / "review" / "open.json"
        if not path.exists():
            return
        raw = self.load(path)
        if raw is _UNREADABLE:
            return
        if not isinstance(raw, list) or not all(
            isinstance(x, str) and _REVIEW_ID.match(x) for x in raw
        ):
            self.error(self.rel(path), "expected a list of review ids (rev_...)")
            return
        self.parsed.open_ids = raw

    # ------------------------------------------------------------ cross-file rules

    def check_cross_file(self) -> None:
        events = self.parsed.events
        sources = self.parsed.sources

        for counter_name, values in (
            ("id", Counter(e.id for _, e in events)),
            ("slug", Counter(e.slug for _, e in events)),
        ):
            for value, count in sorted(values.items()):
                if count > 1:
                    self.error("events", f"duplicate event {counter_name} {value} ({count} times)")

        categories: list[Category] = self.parsed.lists.get("categories.yaml", [])
        category_ids = {c.id for c in categories}
        reviews: list[ReviewItem] = self.parsed.lists.get("review/queue.json", [])
        approved = {r.ref for r in reviews if r.kind == "event" and r.decision == "approved"}

        for where, event in events:
            label = f"{where} {event.id}"
            listing_sources = [sources.get(listing.source_id) for listing in event.listings]
            for listing, source in zip(event.listings, listing_sources, strict=True):
                if source is None:
                    self.error(label, f"listing source {listing.source_id} has no file in sources/")
            if category_ids:
                for category in event.categories:
                    if category not in category_ids:
                        self.error(label, f"category {category} is not in categories.yaml")
            known = [s for s in listing_sources if s is not None]
            if (
                event.review_state == "published"
                and known
                and len(known) == len(listing_sources)
                and all(s.trust == "probationary" for s in known)
                and event.id not in approved
            ):
                self.error(
                    label,
                    "published, but its only listings come from probationary sources and "
                    "there is no approved review item for it",
                )

        event_ids = {e.id for _, e in events}
        overrides: list[Override] = self.parsed.lists.get("overrides.yaml", [])
        for override in overrides:
            if override.event_id not in event_ids:
                self.error("overrides.yaml", f"override for unknown event {override.event_id}")
            if (
                override.visibility is None
                and override.categories is None
                and override.area is None
            ):
                self.error(
                    "overrides.yaml",
                    f"override for {override.event_id} sets none of visibility, categories, area",
                )
            if category_ids and override.categories:
                for category in override.categories:
                    if category not in category_ids:
                        self.error(
                            "overrides.yaml", f"category {category} is not in categories.yaml"
                        )

        queue_ids = {r.id for r in reviews}
        for review_id in self.parsed.open_ids:
            if review_id not in queue_ids:
                self.error("review/open.json", f"{review_id} is not in review/queue.json")


_UNREADABLE: Final = object()


def validate_data(root: Path) -> ValidationReport:
    """Validate the data directory at ``root``; never raises for bad data."""
    if not root.is_dir():
        report = ValidationReport(root)
        report.errors.append(f"{root}: data directory not found")
        return report
    checker = _Checker(root)
    checker.check_list_files()
    checker.check_events()
    checker.check_sources()
    checker.check_source_status()
    checker.check_review_open()
    checker.check_areas()
    checker.check_cross_file()
    return checker.report
