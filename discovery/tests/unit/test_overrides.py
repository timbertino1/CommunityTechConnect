"""Admin overrides applied after every run and before every build (T125; FR-019, FR-045)."""

from __future__ import annotations

import pytest

from netc.models import Event
from netc.pipeline.overrides import apply_overrides
from tests.data_samples import make_event, make_override

pytestmark = pytest.mark.unit


def event(n: int = 1, **overrides: object) -> Event:
    data: dict[str, object] = {
        "slug": f"meetup-{n}",
        "url": f"https://example.org/events/{n}/",
        "categories": ["software-dev"],
        "inferred": ["categories", "area"],
    }
    data.update(overrides)
    return make_event(**data)  # type: ignore[arg-type]


def test_an_override_hides_an_event() -> None:
    target = event()
    [result] = apply_overrides([target], [make_override(target.id, visibility="hidden")])
    assert result.visibility == "hidden"
    assert result.is_public is False


def test_an_override_corrects_categories_and_area() -> None:
    target = event()
    override = make_override(
        target.id, visibility=None, categories=["ai-ml", "data-analytics"], area="lincoln"
    )
    [result] = apply_overrides([target], [override])
    assert result.categories == ["ai-ml", "data-analytics"]
    assert result.area == "lincoln"
    assert result.visibility == "shown"


def test_overridden_fields_are_no_longer_inferred() -> None:
    target = event(inferred=["categories", "area", "end"])
    [cats] = apply_overrides([target], [make_override(target.id, visibility=None,
                                                      categories=["ai-ml"])])  # fmt: skip
    assert cats.inferred == ["area", "end"]
    [area] = apply_overrides([target], [make_override(target.id, visibility=None, area="online")])
    assert area.inferred == ["categories", "end"]


def test_events_without_an_override_are_unchanged() -> None:
    a, b = event(1), event(2)
    result = apply_overrides([a, b], [make_override(a.id, visibility="hidden")])
    assert result[1] == b


def test_order_is_kept() -> None:
    events = [event(n) for n in (3, 1, 2)]
    result = apply_overrides(events, [make_override(events[1].id)])
    assert [e.id for e in result] == [e.id for e in events]


def test_removing_a_hide_override_shows_the_event_again() -> None:
    # Only overrides hide events, so an event with no override is shown.
    hidden = event(visibility="hidden")
    [result] = apply_overrides([hidden], [])
    assert result.visibility == "shown"


def test_an_override_can_unhide_explicitly() -> None:
    hidden = event(visibility="hidden")
    [result] = apply_overrides([hidden], [make_override(hidden.id, visibility="shown")])
    assert result.visibility == "shown"


def test_an_override_cannot_publish_an_event_waiting_for_review() -> None:
    # A probationary source's event stays off the site until it is approved in review.
    waiting = event(review_state="pending_review")
    [result] = apply_overrides([waiting], [make_override(waiting.id, visibility="shown")])
    assert result.review_state == "pending_review"
    assert result.is_public is False


def test_protected_fields_are_never_changed() -> None:
    target = event(review_state="rejected")
    [result] = apply_overrides(
        [target],
        [make_override(target.id, visibility="shown", categories=["ai-ml"], area="online")],
    )
    assert result.original_url == target.original_url
    assert result.review_state == "rejected"
    assert result.listings == target.listings


def test_applying_twice_changes_nothing_more() -> None:
    target = event()
    overrides = [make_override(target.id, categories=["ai-ml"], area="lincoln")]
    once = apply_overrides([target], overrides)
    assert apply_overrides(once, overrides) == once


def test_an_override_for_a_missing_event_is_ignored_here() -> None:
    # validate-data reports it; applying must not fail a run.
    target = event()
    assert apply_overrides([target], [make_override("evt_ffffffffffff")]) == [target]
