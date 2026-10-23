"""Event lifecycle across runs (T059; FR-007, FR-016; data-model.md state transitions).

Given the stored events and the events built from this run's listings:

- an incoming event that matches a stored one (same id, or the de-duplication rule) updates it:
  fresh details, merged listings, ``last_verified`` now; its id, slug, first-seen date, review
  state, and visibility are kept, and ``scheduled`` comes back if it had become ``unverified``;
- a source that says "cancelled" makes the event ``cancelled``;
- a listing missing from a source that was read successfully this run counts one missed run;
  an upcoming event whose every listing has missed two runs becomes ``unverified``. Sources
  that failed or were skipped never count as missing, and past events are left alone;
- a new event is ``published`` when any of its sources is trusted, otherwise it waits for
  review (``pending_review`` plus a Review Item); a held event (e.g. undecided relevance) also
  waits for review;
- an event whose only listings come from Eventbrite is deleted once it has ended (Eventbrite's
  API terms, gate V2), rather than kept for the past-events archive.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from netc.models import Event, ReviewItem, Source
from netc.pipeline.dedupe import cost_rank, merge, same_event

UNVERIFIED_AFTER_MISSED_RUNS: Final = 2
PROBATIONARY_REASON: Final = "new event from a probationary source"


@dataclass(frozen=True)
class Incoming:
    event: Event
    hold_reason: str | None = None
    """Set when the event must be reviewed regardless of source trust."""


@dataclass
class LifecycleResult:
    events: list[Event]
    new_reviews: list[ReviewItem] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    """Ids of events deleted this run (ended, and known only from Eventbrite)."""


def review_id_for(event_id: str) -> str:
    return "rev_" + hashlib.sha256(f"event:{event_id}".encode()).hexdigest()[:12]


def apply_run(
    existing: Iterable[Event],
    incoming: Iterable[Incoming],
    *,
    sources: Mapping[str, Source],
    refreshed_sources: set[str],
    queue: Iterable[ReviewItem],
    now: datetime,
) -> LifecycleResult:
    events: dict[str, Event] = {e.id: e for e in existing}
    queued = {r.id for r in queue}
    new_reviews: list[ReviewItem] = []

    for item in incoming:
        fresh = item.event
        match = events.get(fresh.id) or next(
            (e for e in events.values() if same_event(e, fresh)), None
        )
        if match is not None:
            events[match.id] = _update(match, fresh, now)
            continue

        reason = item.hold_reason
        if reason is None and not any(
            (s := sources.get(listing.source_id)) is not None and s.trust == "trusted"
            for listing in fresh.listings
        ):
            reason = PROBATIONARY_REASON
        if reason is None:
            events[fresh.id] = fresh.model_copy(update={"review_state": "published"})
            continue
        events[fresh.id] = fresh.model_copy(update={"review_state": "pending_review"})
        review_id = review_id_for(fresh.id)
        if review_id not in queued:
            queued.add(review_id)
            new_reviews.append(
                ReviewItem(
                    id=review_id, kind="event", ref=fresh.id, reason=reason[:280], created=now
                )
            )

    updated: list[Event] = []
    removed: list[str] = []
    for event in events.values():
        if _ended_eventbrite_only(event, sources, now):
            removed.append(event.id)
        else:
            updated.append(_count_missing(event, refreshed_sources, now))
    updated.sort(key=lambda e: (e.start, e.id))
    return LifecycleResult(updated, new_reviews, removed)


def _ended_eventbrite_only(event: Event, sources: Mapping[str, Source], now: datetime) -> bool:
    """Eventbrite's API terms (3.1, gate V2) forbid storing anything about past events, so an
    event known only from Eventbrite is deleted once it has ended instead of being archived."""
    if (event.end or event.start) >= now:
        return False
    return all(
        (s := sources.get(listing.source_id)) is not None and s.connector == "eventbrite_org"
        for listing in event.listings
    )


def _update(stored: Event, fresh: Event, now: datetime) -> Event:
    combined = merge(stored, fresh)
    status = "cancelled" if fresh.status == "cancelled" else "scheduled"
    # A stated cost outlives a read that says nothing; a default the admin removed does not.
    kept = stored if cost_rank(stored) == 2 and cost_rank(fresh) < 2 else fresh
    return combined.model_copy(
        update={
            "title": fresh.title,
            "summary": fresh.summary,
            "start": fresh.start,
            "end": fresh.end,
            "source_tz": fresh.source_tz,
            "tz_assumed": fresh.tz_assumed,
            "all_day": fresh.all_day,
            "location": fresh.location,
            "area": fresh.area,
            "categories": fresh.categories,
            "inferred": fresh.inferred
            if kept is fresh
            else [f for f in fresh.inferred if f != "cost"],
            "cost": kept.cost,
            "price": kept.price,
            "status": status,
            "first_seen": stored.first_seen,
            "last_verified": now,
        }
    )


def _count_missing(event: Event, refreshed: set[str], now: datetime) -> Event:
    if (event.end or event.start) <= now:
        return event  # past events drop out of feeds naturally
    listings = [
        listing.model_copy(update={"missing_runs": listing.missing_runs + 1})
        if listing.source_id in refreshed and listing.last_seen < now
        else listing
        for listing in event.listings
    ]
    status = event.status
    if status == "scheduled" and all(
        x.missing_runs >= UNVERIFIED_AFTER_MISSED_RUNS for x in listings
    ):
        status = "unverified"
    return event.model_copy(update={"listings": listings, "status": status})
