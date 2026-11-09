"""Event lifecycle across runs (T059; FR-007, FR-016; data-model.md state transitions).

Given the stored events and the events built from this run's listings:

- an incoming event that matches a stored one (same id, or the de-duplication rule) updates it:
  fresh details, merged listings, ``last_verified`` now; its id, slug, first-seen date, review
  state, and visibility are kept, and ``scheduled`` comes back if it had become ``unverified``;
  ``changed_at`` becomes now when a published event's title, time, place or status changed
  (feature 002);
- a source that says "cancelled" makes the event ``cancelled``;
- a listing missing from a source that was read successfully this run counts one missed run;
  an upcoming event whose every listing has missed two runs becomes ``unverified``. Sources
  that failed or were skipped never count as missing, and past events are left alone;
- a new event is ``published`` (``published_at`` now) when any of its sources is trusted,
  otherwise it waits for review (``pending_review`` plus a Review Item); a held event (e.g.
  undecided relevance) also waits for review. One that is already over when first found gets
  no Review Item: there is nothing left to decide, so it is never listed;
- a pending event Review Item whose event is over, gone, or no longer waiting is ``expired``:
  nothing is left to decide. Expired items count as neither approved nor rejected;
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
from netc.pipeline.dedupe import merge, same_event

UNVERIFIED_AFTER_MISSED_RUNS: Final = 2
FOLLOWED_FIELDS: Final = ("title", "start", "end", "all_day", "location")
"""Details a feed follower is told about when they change (feature 002, ``changed_at``), along
with being cancelled or un-cancelled. (Unverified and back is not news: feeds don't show it.)"""
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
    expired: list[str] = field(default_factory=list)
    """Ids of pending event review items with nothing left to decide (see expire_reviews)."""


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
    queue = list(queue)
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
            events[fresh.id] = fresh.model_copy(
                update={"review_state": "published", "published_at": now}
            )
            continue
        events[fresh.id] = fresh.model_copy(update={"review_state": "pending_review"})
        if _over(fresh, now):
            continue  # found too late to review: never listed, so no item to clutter the queue
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
    expired = expire_reviews(queue, updated, now=now)
    return LifecycleResult(updated, new_reviews, removed, expired)


def expire_reviews(
    queue: Iterable[ReviewItem], events: Iterable[Event], *, now: datetime
) -> list[str]:
    """Ids of pending event items with nothing left to decide: the event is over, was
    deleted, or no longer waits for review. These are exactly the event items the review PR
    leaves out (``netc.github.review_pr.pending_items``), so without this they'd stay pending
    for good."""
    by_id = {e.id: e for e in events}
    expired: list[str] = []
    for item in queue:
        if item.kind != "event" or item.decision != "pending":
            continue
        event = by_id.get(item.ref)
        if event is None or event.review_state != "pending_review" or _over(event, now):
            expired.append(item.id)
    return expired


def _over(event: Event, now: datetime) -> bool:
    """The rule the review PR uses (and FR-035's ``is_upcoming``): over once its end, or its
    start when it has no end, has passed."""
    return (event.end or event.start) <= now


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
    changed = stored.review_state == "published" and (
        any(getattr(stored, f) != getattr(fresh, f) for f in FOLLOWED_FIELDS)
        or (stored.status == "cancelled") != (status == "cancelled")
    )
    return combined.model_copy(
        update={
            "changed_at": now if changed else combined.changed_at,
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
            "inferred": fresh.inferred,
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
