"""Deterministic, atomic reading and writing of the versioned data/ directory (T030).

Writes are byte-for-byte reproducible (sorted keys, stable ordering, UTF-8, LF, trailing newline)
so daily diffs stay small and reviewable, and atomic (temp file + rename) so a crash never leaves
a half-written file. Events are partitioned into data/events/<YYYY>/<YYYY-MM>.json by the month
their start falls in, in Central Time.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ValidationError

from netc.models import (
    DEFAULT_TZ,
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
)

CENTRAL: Final = ZoneInfo(DEFAULT_TZ)
EVENT_FILE: Final = re.compile(r"^(\d{4})/(\d{4})-(\d{2})\.json$")


class StorageError(Exception):
    """A data file could not be read or written."""


class _Loader(yaml.SafeLoader):
    """YAML loader that keeps dates and times as strings, exactly as JSON would."""


_Loader.yaml_implicit_resolvers = {
    first: [(tag, regex) for tag, regex in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def read_raw(path: Path) -> Any:
    """Parse a .json or .yaml file into plain JSON-compatible data. Raises StorageError."""
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            return json.loads(text)
        return yaml.load(text, Loader=_Loader)  # noqa: S506 - SafeLoader subclass
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise StorageError(f"{path}: cannot be parsed: {exc}") from exc


def dump_json(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def dump_yaml(data: Any) -> bytes:
    text = yaml.safe_dump(
        data, sort_keys=True, allow_unicode=True, default_flow_style=False, width=100, indent=2
    )
    return text.encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` atomically; skip the write when nothing changed."""
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def event_month_path(event: Event) -> str:
    """Relative path under events/ for the Central Time month of the event's start."""
    local = event.start.astimezone(CENTRAL)
    return f"{local:%Y}/{local:%Y-%m}.json"


def _to_data(model: BaseModel) -> Any:
    return model.model_dump(mode="json")


def _parse[M: BaseModel](model: type[M], raw: Any, path: Path, index: int | None = None) -> M:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        where = path.as_posix() if index is None else f"{path.as_posix()} [{index}]"
        raise StorageError(f"{where}: invalid {model.__name__}: {exc}") from exc


class DataStore:
    """Typed access to one data/ directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # ------------------------------------------------------------ generic helpers

    def _read_list[M: BaseModel](self, relative: str, model: type[M]) -> list[M]:
        path = self.root / relative
        if not path.exists():
            return []
        raw = read_raw(path)
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise StorageError(f"{path}: expected a list")
        return [_parse(model, item, path, i) for i, item in enumerate(raw)]

    def _write_list(
        self,
        relative: str,
        items: Iterable[BaseModel],
        key: Callable[[Any], Any] | None,
    ) -> None:
        ordered = sorted(items, key=key) if key is not None else list(items)
        data = [_to_data(item) for item in ordered]
        path = self.root / relative
        atomic_write(path, dump_json(data) if path.suffix == ".json" else dump_yaml(data))

    # ------------------------------------------------------------ events

    def read_events(self) -> list[Event]:
        events: list[Event] = []
        for relative in self._event_files():
            path = self.root / "events" / relative
            raw = read_raw(path)
            if not isinstance(raw, list):
                raise StorageError(f"{path}: expected a list")
            events.extend(_parse(Event, item, path, i) for i, item in enumerate(raw))
        return sorted(events, key=lambda e: (e.start, e.id))

    def write_events(self, events: Iterable[Event]) -> None:
        """Write the complete set of events, removing month files that no longer have any."""
        by_month: dict[str, list[Event]] = {}
        seen: set[str] = set()
        for event in events:
            if event.id in seen:
                raise StorageError(f"duplicate event id {event.id}")
            seen.add(event.id)
            by_month.setdefault(event_month_path(event), []).append(event)

        events_dir = self.root / "events"
        for relative, month_events in by_month.items():
            month_events.sort(key=lambda e: (e.start, e.id))
            atomic_write(events_dir / relative, dump_json([_to_data(e) for e in month_events]))
        for relative in self._event_files():
            if relative not in by_month:
                (events_dir / relative).unlink()
        for year_dir in events_dir.glob("[0-9][0-9][0-9][0-9]"):
            if year_dir.is_dir() and not any(year_dir.iterdir()):
                year_dir.rmdir()

    def _event_files(self) -> list[str]:
        events_dir = self.root / "events"
        if not events_dir.is_dir():
            return []
        found = (p.relative_to(events_dir).as_posix() for p in events_dir.glob("*/*.json"))
        return sorted(rel for rel in found if EVENT_FILE.match(rel))

    # ------------------------------------------------------------ sources (one YAML per source)

    def read_sources(self) -> list[Source]:
        sources_dir = self.root / "sources"
        if not sources_dir.is_dir():
            return []
        sources = [_parse(Source, read_raw(p), p) for p in sorted(sources_dir.glob("*.yaml"))]
        return sorted(sources, key=lambda s: s.id)

    def write_source(self, source: Source) -> None:
        atomic_write(self.root / "sources" / f"{source.id}.yaml", dump_yaml(_to_data(source)))

    # ------------------------------------------------------------ list files

    def read_candidates(self) -> list[CandidateSource]:
        return self._read_list("candidates.json", CandidateSource)

    def write_candidates(self, items: Iterable[CandidateSource]) -> None:
        self._write_list("candidates.json", items, key=lambda c: c.url)

    def read_mentions(self) -> list[EventMention]:
        return self._read_list("mentions.json", EventMention)

    def write_mentions(self, items: Iterable[EventMention]) -> None:
        self._write_list("mentions.json", items, key=lambda m: m.id)

    def read_review_queue(self) -> list[ReviewItem]:
        return self._read_list("review/queue.json", ReviewItem)

    def write_review_queue(self, items: Iterable[ReviewItem]) -> None:
        self._write_list("review/queue.json", items, key=lambda r: (r.created, r.id))

    def read_known_groups(self) -> list[KnownGroup]:
        return self._read_list("known_groups.yaml", KnownGroup)

    def write_known_groups(self, items: Iterable[KnownGroup]) -> None:
        self._write_list("known_groups.yaml", items, key=lambda g: (g.name.casefold(), g.name))

    def read_organizers(self) -> list[Organizer]:
        return self._read_list("organizers.yaml", Organizer)

    def write_organizers(self, items: Iterable[Organizer]) -> None:
        self._write_list("organizers.yaml", items, key=lambda o: o.id)

    def read_categories(self) -> list[Category]:
        return self._read_list("categories.yaml", Category)

    def write_categories(self, items: Iterable[Category]) -> None:
        # Kept in the given order: it is the display order chosen by the administrator.
        self._write_list("categories.yaml", items, key=None)

    def read_areas(self) -> AreaConfig | None:
        """data/areas.yaml, edited by hand only (no writer: comments must survive)."""
        path = self.root / "areas.yaml"
        return _parse(AreaConfig, read_raw(path), path) if path.exists() else None

    def read_overrides(self) -> list[Override]:
        return self._read_list("overrides.yaml", Override)

    def write_overrides(self, items: Iterable[Override]) -> None:
        self._write_list("overrides.yaml", items, key=lambda o: o.event_id)

    # ------------------------------------------------------------ small special files

    def read_review_open(self) -> list[str]:
        path = self.root / "review" / "open.json"
        if not path.exists():
            return []
        raw = read_raw(path)
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise StorageError(f"{path}: expected a list of review ids")
        return sorted(raw)

    def write_review_open(self, review_ids: Iterable[str]) -> None:
        atomic_write(self.root / "review" / "open.json", dump_json(sorted(set(review_ids))))

    def read_source_status(self) -> dict[str, SourceStatus]:
        path = self.root / "state" / "source_status.json"
        if not path.exists():
            return {}
        raw = read_raw(path)
        if not isinstance(raw, dict):
            raise StorageError(f"{path}: expected an object keyed by source id")
        return {key: _parse(SourceStatus, value, path) for key, value in sorted(raw.items())}

    def write_source_status(self, statuses: Mapping[str, SourceStatus]) -> None:
        data = {key: _to_data(value) for key, value in statuses.items()}
        atomic_write(self.root / "state" / "source_status.json", dump_json(data))
