"""When events get published_at and changed_at (feature 002 T003; data-model.md transitions)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from netc.github.review_pr import build_review_pr, read_decisions
from netc.models import Event
from netc.pipeline.dedupe import merge
from netc.pipeline.review import apply_decisions
from tests.data_samples import make_event, utc
from tests.review_support import (
    AREAS,
    CATEGORIES,
    campus_source,
    held_event,
    make_review_data,
    queue_item,
    tick,
)
from tests.review_support import NOW as REVIEW_NOW
from tests.unit.test_lifecycle import PROBATIONARY, START, TRUSTED, ev, only, run, seen

pytestmark = pytest.mark.unit

NOW = utc(2026, 10, 18, 12)
LATER = utc(2026, 10, 19, 12)


# ---------------------------------------------------------------- creation


def test_a_new_event_from_a_trusted_source_is_published_now() -> None:
    event = only(run([], [seen(ev(TRUSTED.id))]))
    assert event.review_state == "published"
    assert event.published_at == NOW
    assert event.changed_at is None


def test_a_new_probationary_event_waits_without_published_at() -> None:
    event = only(run([], [seen(ev(PROBATIONARY.id))]))
    assert event.review_state == "pending_review"
    assert event.published_at is None


# ---------------------------------------------------------------- updates


def stored(**overrides: Any) -> Event:
    data: dict[str, Any] = {"published_at": utc(2026, 10, 12)}
    data.update(overrides)
    return ev(**data)


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Renamed meetup"},
        {"start": utc(2026, 11, 11, 0)},
        {"end": utc(2026, 11, 11, 2)},
        {"all_day": True},
        {"location": {"venue": "Elsewhere", "city": "Omaha", "state": "NE", "online": False}},
        {"status": "cancelled"},
    ],
)
def test_a_detail_change_sets_changed_at(change: dict[str, Any]) -> None:
    before = stored()
    fresh = seen(ev(**change), LATER)
    event = only(run([before], [fresh], now=LATER))
    assert event.changed_at == LATER
    assert event.published_at == utc(2026, 10, 12)


@pytest.mark.parametrize(
    "change",
    [
        {"summary": "New wording of the same talk."},
        {"categories": ["software-dev", "ai-ml"]},
        {},
    ],
)
def test_other_updates_keep_changed_at(change: dict[str, Any]) -> None:
    before = stored(changed_at=utc(2026, 10, 15))
    event = only(run([before], [seen(ev(**change), LATER)], now=LATER))
    assert event.changed_at == utc(2026, 10, 15)
    assert event.last_verified == LATER


def test_changes_while_waiting_for_review_are_not_recorded() -> None:
    """Followers never saw it, so there is nothing to tell them; approval sets published_at."""
    before = ev(PROBATIONARY.id, review_state="pending_review")
    fresh = seen(ev(PROBATIONARY.id, title="Renamed"), LATER)
    event = only(run([before], [fresh], now=LATER))
    assert event.title == "Renamed"
    assert event.changed_at is None


def test_coming_back_from_unverified_is_not_a_change() -> None:
    before = stored(status="unverified")
    event = only(run([before], [seen(ev(), LATER)], now=LATER))
    assert event.status == "scheduled"
    assert event.changed_at is None


def test_published_at_never_moves_on_update() -> None:
    before = stored()
    event = only(run([before], [seen(ev(title="Renamed"), LATER)], now=LATER))
    assert event.published_at == utc(2026, 10, 12)


def test_a_cancelled_event_gets_changed_at_once() -> None:
    before = stored()
    cancelled = only(run([before], [seen(ev(status="cancelled"), LATER)], now=LATER))
    again = only(
        run([cancelled], [seen(ev(status="cancelled"), utc(2026, 10, 20))], now=utc(2026, 10, 20))
    )
    assert again.changed_at == LATER


# ---------------------------------------------------------------- merge


def pair(a: dict[str, Any], b: dict[str, Any]) -> Event:
    first = make_event(url="https://example.org/a", start=START, **a)
    second = make_event(url="https://example.org/b", start=START, **b)
    return merge(first, second)


def test_merge_keeps_the_earliest_published_and_the_latest_changed() -> None:
    merged = pair(
        {"published_at": utc(2026, 10, 12), "changed_at": utc(2026, 10, 14)},
        {"published_at": utc(2026, 10, 11), "changed_at": utc(2026, 10, 16)},
    )
    assert merged.published_at == utc(2026, 10, 11)
    assert merged.changed_at == utc(2026, 10, 16)


def test_merge_treats_an_older_published_event_without_published_at_as_first_seen() -> None:
    """A public event stored before feature 002 counts as published when first seen."""
    merged = pair(
        {"first_seen": utc(2026, 10, 5)},
        {"first_seen": utc(2026, 10, 10), "published_at": utc(2026, 10, 15)},
    )
    assert merged.published_at == utc(2026, 10, 5)


def test_merge_drops_a_change_older_than_the_merged_published_time() -> None:
    merged = pair(
        {"review_state": "pending_review", "changed_at": utc(2026, 10, 11)},
        {"first_seen": utc(2026, 10, 10), "published_at": utc(2026, 10, 15)},
    )
    assert merged.published_at == utc(2026, 10, 15)
    assert merged.changed_at is None


def test_merge_of_two_unreviewed_events_has_no_published_at() -> None:
    merged = pair({"review_state": "pending_review"}, {"review_state": "pending_review"})
    assert merged.published_at is None


# ---------------------------------------------------------------- review approval


def approve(tmp_path: Path, event: Event, now: datetime) -> Event:
    queue = [queue_item(event)]
    store = make_review_data(tmp_path / "data", [event], queue, [campus_source()])
    pr = build_review_pr(queue, [event], store.read_sources(), categories=CATEGORIES,
                         areas=AREAS, now=REVIEW_NOW)  # fmt: skip
    assert pr is not None
    body = tick(pr.body, queue[0].id, "approve")
    apply_decisions(
        store, pr_number=7, decisions=read_decisions(body), open_ids=store.read_review_open(),
        now=now,
    )  # fmt: skip
    (result,) = store.read_events()
    return result


def test_approval_sets_published_at(tmp_path: Path) -> None:
    event = approve(tmp_path, held_event(1), REVIEW_NOW)
    assert event.review_state == "published"
    assert event.published_at == REVIEW_NOW


def test_approval_keeps_an_existing_published_at(tmp_path: Path) -> None:
    held = held_event(1)
    earlier = held.model_copy(update={"published_at": held.first_seen})
    event = approve(tmp_path, earlier, REVIEW_NOW)
    assert event.published_at == held.first_seen


def test_rejection_sets_nothing(tmp_path: Path) -> None:
    held = held_event(1)
    queue = [queue_item(held)]
    store = make_review_data(tmp_path / "data", [held], queue, [campus_source()])
    pr = build_review_pr(queue, [held], store.read_sources(), categories=CATEGORIES,
                         areas=AREAS, now=REVIEW_NOW)  # fmt: skip
    assert pr is not None
    apply_decisions(
        store, pr_number=7, decisions=read_decisions(tick(pr.body, queue[0].id, "reject")),
        open_ids=store.read_review_open(), now=REVIEW_NOW,
    )  # fmt: skip
    (result,) = store.read_events()
    assert result.review_state == "rejected"
    assert result.published_at is None
