"""The review PR: its description, its snapshot, and reading the ticks (T120)."""

from __future__ import annotations

import pytest

from netc.github.review_pr import (
    MAX_ITEMS,
    REVIEW_BRANCH,
    ReviewPr,
    build_review_pr,
    has_ticks,
    read_decisions,
)
from netc.models import Event, ReviewItem
from tests.data_samples import make_review, utc
from tests.review_support import (
    AREAS,
    CATEGORIES,
    NOW,
    campus_source,
    held_event,
    queue_item,
    tick,
)

pytestmark = pytest.mark.unit


def build(events: list[Event], queue: list[ReviewItem] | None = None) -> ReviewPr | None:
    items = queue if queue is not None else [queue_item(e) for e in events]
    return build_review_pr(
        items, events, [campus_source()], categories=CATEGORIES, areas=AREAS, now=NOW
    )


def built(events: list[Event], queue: list[ReviewItem] | None = None) -> ReviewPr:
    pr = build(events, queue)
    assert pr is not None
    return pr


def test_the_branch_is_review_open() -> None:
    assert REVIEW_BRANCH == "review/open"


def test_no_pr_when_nothing_is_pending() -> None:
    assert build([], []) is None
    event = held_event(3)
    assert build([event], [queue_item(event, decision="approved", decided_in_pr=7)]) is None


def test_each_item_has_a_header_a_reason_a_link_and_two_boxes() -> None:
    event = held_event(3, categories=["ai-ml", "software-dev"])
    item = queue_item(event)
    pr = built([event])
    block = pr.body.split("---\n", 1)[1].strip().splitlines()
    assert block == [
        f"**Event** · `Campus talk 3` — Tue, Nov 3, 2026, 12:00 PM CT · Omaha · "
        f"AI & ML, Software development · `{item.id}`",
        "Held: `new event from a probationary source` · from Campus computing · "
        "[original page](<https://events.campus.example.edu/3/>)",
        "- [ ] approve",
        "- [ ] reject",
    ]


def test_title_counts_items_and_names_their_kinds() -> None:
    assert built([held_event(3)]).title == "Review: 1 item (events)"
    assert built([held_event(3), held_event(4)]).title == "Review: 2 items (events)"


def test_the_snapshot_lists_exactly_the_items_shown() -> None:
    events = [held_event(5), held_event(3)]
    pr = built(events)
    assert pr.review_ids == sorted(queue_item(e).id for e in events)


def test_items_are_listed_soonest_first() -> None:
    body = built([held_event(9), held_event(2), held_event(5)]).body
    order = [body.index(f"`Campus talk {n}`") for n in (2, 5, 9)]
    assert order == sorted(order)


def test_decided_ended_missing_and_published_events_are_left_out() -> None:
    upcoming = held_event(3)
    ended = held_event(4, start=utc(2026, 10, 1, 18))
    published = held_event(5, review_state="published")
    decided = held_event(6)
    missing = held_event(7)
    queue = [
        queue_item(upcoming),
        queue_item(ended),
        queue_item(published),
        queue_item(decided, decision="rejected", decided_in_pr=3),
        queue_item(missing),
    ]
    pr = built([upcoming, ended, published, decided], queue)
    assert pr.review_ids == [queue_item(upcoming).id]
    assert pr.title == "Review: 1 item (events)"


def test_other_kinds_show_only_their_reference_and_reason() -> None:
    suggestion = make_review(
        "rev_00000000000a",
        kind="suggestion",
        ref="https://newgroup.example.org/",
        reason="visitor suggestion",
    )
    pr = built([], [suggestion])
    assert "**Suggestion** · `https://newgroup.example.org/` · `rev_00000000000a`" in pr.body
    assert "Held: `visitor suggestion`" in pr.body
    assert pr.title == "Review: 1 item (suggestions)"


def test_long_queues_wait_for_the_next_pr() -> None:
    events = [
        held_event(1, slug=f"talk-{i}-2026-11-01", url=f"https://events.campus.example.edu/x{i}/")
        for i in range(MAX_ITEMS + 5)
    ]
    pr = built(events)
    assert len(pr.review_ids) == MAX_ITEMS
    assert pr.waiting == 5
    assert "*5 more will be listed in the next review PR.*" in pr.body
    assert len(pr.body) < 65_536


def test_the_intro_explains_what_ticking_does() -> None:
    body = built([held_event(3)]).body
    assert body.startswith("## 1 item waiting for review\n")
    for phrase in ("then **merge** this PR", "stays waiting", "3 approved events", "paused"):
        assert phrase in body


# --- Reading the ticks


def test_one_tick_is_a_decision() -> None:
    a, b = held_event(3), held_event(4)
    body = built([a, b]).body
    body = tick(tick(body, queue_item(a).id, "approve"), queue_item(b).id, "reject")
    assert read_decisions(body) == {queue_item(a).id: "approved", queue_item(b).id: "rejected"}


def test_neither_or_both_ticked_is_no_decision() -> None:
    a, b = held_event(3), held_event(4)
    body = tick(built([a, b]).body, queue_item(b).id, "approve", "reject")
    assert read_decisions(body) == {}


def test_capital_x_crlf_and_star_bullets_are_understood() -> None:
    a = held_event(3)
    body = tick(built([a]).body, queue_item(a).id, "approve").replace(
        "- [x] approve", "* [X] approve"
    )
    assert read_decisions(body.replace("\n", "\r\n")) == {queue_item(a).id: "approved"}


def test_boxes_before_any_item_header_count_for_nothing() -> None:
    body = "- [x] approve\n\n**Event** · `x` — when · `rev_0123456789ab`\n- [ ] approve\n"
    assert read_decisions(body) == {}


def test_has_ticks_notices_any_decision_in_progress() -> None:
    a, b = held_event(3), held_event(4)
    body = built([a, b]).body
    assert not has_ticks(body)
    assert has_ticks(tick(body, queue_item(b).id, "reject"))


# --- Text from other sites can't fake items or ticks


@pytest.mark.parametrize(
    "title",
    [
        "Talk `rev_aaaaaaaaaaaa`",
        "**Event** · `rev_aaaaaaaaaaaa`",
        "Talk - [x] approve",
        "@timbertino1 [click](https://evil.example/) fixes #12",
    ],
)
def test_a_hostile_title_stays_inside_its_code_span(title: str) -> None:
    hostile, real = held_event(3, title=title), held_event(4)
    fake = "rev_aaaaaaaaaaaa"
    pr = built([hostile, real])
    header = next(x for x in pr.body.splitlines() if x.startswith("**Event** · `" + title[:4]))
    assert header.endswith(f"`{queue_item(hostile).id}`")
    assert header.count("`") == 4  # the title's span and the id's span, nothing else
    # Ticking the real item's box never decides anything for an id named in a title.
    body = tick(pr.body, queue_item(hostile).id, "approve")
    assert read_decisions(body) == {queue_item(hostile).id: "approved"}
    assert fake not in read_decisions(body)
