"""Event lifecycle across runs (T052; FR-007, FR-016, data-model state transitions)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from netc.models import Event, ReviewItem, Source
from netc.pipeline.lifecycle import Incoming, LifecycleResult, apply_run, review_id_for
from tests.data_samples import make_event, make_review, make_source, utc

pytestmark = pytest.mark.unit

NOW = utc(2026, 10, 18, 12)
START = utc(2026, 11, 10, 23, 30)
TRUSTED = make_source("src_trusted")
PROBATIONARY = make_source(
    "src_probation", trust="probationary", origin="discovered", found_via="web_search"
)
SOURCES: dict[str, Source] = {s.id: s for s in (TRUSTED, PROBATIONARY)}


def ev(
    source_id: str = "src_trusted", url: str = "https://example.org/e/1", **overrides: Any
) -> Event:
    data: dict[str, Any] = {"start": START, "url": url, "source_id": source_id}
    data.update(overrides)
    return make_event(**data)


def seen(event: Event, when: datetime = NOW) -> Event:
    """The event as built fresh from this run's listing."""
    listing = event.listings[0].model_copy(update={"last_seen": when, "missing_runs": 0})
    return event.model_copy(
        update={"listings": [listing], "first_seen": when, "last_verified": when}
    )


def run(
    existing: list[Event],
    incoming: list[Event | Incoming],
    refreshed: set[str] | None = None,
    queue: list[ReviewItem] | None = None,
    now: datetime = NOW,
) -> LifecycleResult:
    items = [x if isinstance(x, Incoming) else Incoming(x) for x in incoming]
    return apply_run(
        existing,
        items,
        sources=SOURCES,
        refreshed_sources=refreshed if refreshed is not None else {"src_trusted", "src_probation"},
        queue=queue or [],
        now=now,
    )


def only(result: LifecycleResult) -> Event:
    (event,) = result.events
    return event


# --- New events and review


def test_new_event_from_a_trusted_source_is_published() -> None:
    result = run([], [seen(ev(review_state="pending_review"))])
    assert only(result).review_state == "published"
    assert result.new_reviews == []


def test_new_event_from_a_probationary_source_waits_for_review() -> None:
    event = seen(ev("src_probation"))
    result = run([], [event])
    assert only(result).review_state == "pending_review"
    (review,) = result.new_reviews
    assert review.kind == "event"
    assert review.ref == event.id
    assert review.decision == "pending"
    assert "probationary" in review.reason
    assert review.id == review_id_for(event.id)


def test_a_held_event_waits_for_review_even_from_a_trusted_source() -> None:
    result = run([], [Incoming(seen(ev()), hold_reason="low confidence: relevance")])
    assert only(result).review_state == "pending_review"
    assert result.new_reviews[0].reason == "low confidence: relevance"


def test_review_items_are_not_duplicated() -> None:
    event = seen(ev("src_probation"))
    queue = [make_review(review_id_for(event.id), ref=event.id)]
    assert run([], [event], queue=queue).new_reviews == []


# --- Updates


def test_changed_details_update_the_event_and_last_verified() -> None:
    old = ev(
        title="Prairie Python Meetup", first_seen=utc(2026, 10, 1), last_verified=utc(2026, 10, 10)
    )
    fresh = seen(ev(title="Prairie Python: Packaging Night", summary="New topic."))
    event = only(run([old], [fresh]))
    assert event.title == "Prairie Python: Packaging Night"
    assert event.summary == "New topic."
    assert event.last_verified == NOW
    assert event.id == old.id
    assert event.slug == old.slug  # URLs stay stable
    assert event.first_seen == utc(2026, 10, 1)


def test_a_moved_event_matched_by_its_link_gets_the_new_time() -> None:
    old = ev()
    fresh = seen(ev(start=START + timedelta(days=7)))
    assert only(run([old], [fresh])).start == START + timedelta(days=7)


def test_review_decisions_and_visibility_are_kept() -> None:
    for state in ("pending_review", "rejected"):
        old = ev(review_state=state, visibility="hidden")
        event = only(run([old], [seen(ev())]))
        assert event.review_state == state
        assert event.visibility == "hidden"


def test_a_new_listing_from_another_source_joins_the_existing_event() -> None:
    old = ev()
    fresh = seen(
        ev("src_probation", url="https://mirror.example.org/e", title="Omaha Python Meetup")
    )
    event = only(run([old], [fresh]))
    assert {x.source_id for x in event.listings} == {"src_trusted", "src_probation"}


# --- Status transitions


def test_source_says_cancelled() -> None:
    event = only(run([ev()], [seen(ev(status="cancelled"))]))
    assert event.status == "cancelled"


def test_missing_on_two_consecutive_runs_becomes_unverified() -> None:
    first = only(run([ev()], []))
    assert first.status == "scheduled"
    assert first.listings[0].missing_runs == 1
    second = only(run([first], [], now=NOW + timedelta(hours=12)))
    assert second.status == "unverified"
    assert second.listings[0].missing_runs == 2


def test_reappearing_makes_it_scheduled_again() -> None:
    gone = ev(status="unverified")
    gone = gone.model_copy(
        update={"listings": [gone.listings[0].model_copy(update={"missing_runs": 3})]}
    )
    event = only(run([gone], [seen(ev())]))
    assert event.status == "scheduled"
    assert event.listings[0].missing_runs == 0


def test_a_failed_or_skipped_source_does_not_count_as_missing() -> None:
    event = only(run([ev()], [], refreshed=set()))
    assert event.listings[0].missing_runs == 0
    assert event.status == "scheduled"


def test_still_listed_elsewhere_stays_scheduled() -> None:
    both = ev()
    other = both.listings[0].model_copy(
        update={"source_id": "src_probation", "url": "https://mirror.example.org/e"}
    )
    both = both.model_copy(update={"listings": [*both.listings, other]})
    fresh = seen(ev("src_probation", url="https://mirror.example.org/e"))
    event = only(run([both], [fresh], now=NOW))
    event = only(
        run(
            [event],
            [
                seen(
                    ev("src_probation", url="https://mirror.example.org/e"),
                    NOW + timedelta(hours=12),
                )
            ],
            now=NOW + timedelta(hours=12),
        )
    )
    assert event.status == "scheduled"


def test_past_events_are_left_alone() -> None:
    past = ev(start=utc(2026, 9, 1, 23))
    event = only(run([past], []))
    assert event.status == "scheduled"
    assert event.listings[0].missing_runs == 0


def test_cancelled_events_do_not_turn_unverified() -> None:
    cancelled = ev(status="cancelled")
    for _ in range(3):
        cancelled = only(run([cancelled], []))
    assert cancelled.status == "cancelled"


def test_events_are_returned_soonest_first() -> None:
    later = seen(ev(url="https://example.org/later", start=START + timedelta(days=3)))
    sooner = seen(ev(url="https://example.org/sooner"))
    result = run([], [later, sooner])
    assert [e.start for e in result.events] == [START, START + timedelta(days=3)]
