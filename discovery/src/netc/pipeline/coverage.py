"""Coverage gaps (research R7; FR-013): groups that went quiet and annual events not yet listed.

Shared by the health issue (which reports them) and the gap finder (which searches for them).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from statistics import median
from typing import Final

from netc.models import Event, Source

QUIET_LOOKBACK: Final = timedelta(days=183)
QUIET_MIN_EVENTS: Final = 3
ANNUAL_MIN_GAP: Final = timedelta(days=300)
ANNUAL_MAX_GAP: Final = timedelta(days=430)
ANNUAL_SEARCH_AFTER: Final = timedelta(days=300)
"""About 10 months after the last edition, look for the next one."""
_YEARS: Final = re.compile(r"\b(19|20)\d\d\b|\b'\d\d\b")
_SPACE: Final = re.compile(r"\s+")


@dataclass(frozen=True)
class QuietSource:
    source: Source
    last_event: datetime
    usual_gap: timedelta


@dataclass(frozen=True)
class AnnualSeries:
    title: str
    """The series name without years, e.g. "Nebraska.Code() Conference"."""
    last_event: datetime
    organizer_id: str | None


def quiet_sources(
    sources: Iterable[Source], events: Iterable[Event], now: datetime
) -> list[QuietSource]:
    """Active sources whose events stopped: nothing upcoming, and the time since the last event
    is more than twice the usual gap over the last six months."""
    starts: dict[str, list[datetime]] = {}
    upcoming: set[str] = set()
    for event in _counted(events):
        for source_id in {x.source_id for x in event.listings}:
            if event.start > now:
                upcoming.add(source_id)
            elif event.start >= now - QUIET_LOOKBACK:
                starts.setdefault(source_id, []).append(event.start)
    quiet = []
    for source in sources:
        past = sorted(set(starts.get(source.id, [])))
        if source.status != "active" or source.id in upcoming or len(past) < QUIET_MIN_EVENTS:
            continue
        gap = timedelta(seconds=median((b - a).total_seconds() for a, b in pairwise(past)))
        if now - past[-1] > 2 * gap:
            quiet.append(QuietSource(source, past[-1], gap))
    return quiet


def annual_series_due(events: Iterable[Event], now: datetime) -> list[AnnualSeries]:
    """Series held about once a year (same organizer, same title apart from the year) whose
    last edition was at least ten months ago and whose next one isn't listed yet."""
    groups: dict[tuple[str, str], list[Event]] = {}
    for event in _counted(events):
        base = series_title(event.title)
        owner = event.organizer_id or event.listings[0].source_id
        groups.setdefault((owner, base.casefold()), []).append(event)
    due = []
    for group in groups.values():
        group.sort(key=lambda e: e.start)
        if any(e.start > now for e in group):
            continue
        past = [e.start for e in group]
        yearly = any(ANNUAL_MIN_GAP <= b - a <= ANNUAL_MAX_GAP for a, b in pairwise(past))
        if yearly and now - past[-1] >= ANNUAL_SEARCH_AFTER:
            last = group[-1]
            due.append(AnnualSeries(series_title(last.title), last.start, last.organizer_id))
    return due


def series_title(title: str) -> str:
    return _SPACE.sub(" ", _YEARS.sub(" ", title)).strip(" -:·")


def _counted(events: Iterable[Event]) -> list[Event]:
    return [e for e in events if e.status != "cancelled" and e.review_state != "rejected"]
