"""The monthly check of past events' original pages (T116; US5 scenario 3, FR-040)."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

import pytest

from netc.fetch import (
    BudgetExceededError,
    ContentTypeNotAllowedError,
    FetchError,
    FetchKind,
    FetchResponse,
    RobotsDisallowedError,
)
from netc.models import Event
from netc.pipeline.linkcheck import MAX_CHECKS, check_links, due
from tests.data_samples import make_event, utc

pytestmark = pytest.mark.unit

NOW = utc(2026, 11, 1, 11)


class FakeHttp:
    """Answers by URL: a status code, or an exception to raise."""

    def __init__(self, answers: Mapping[str, int | Exception] | None = None) -> None:
        self.answers = dict(answers or {})
        self.requested: list[str] = []

    def get(
        self,
        url: str,
        *,
        kind: FetchKind = "page",
        allowed_types: Collection[str] | None = None,
        delay_seconds: float | None = None,
    ) -> FetchResponse:
        self.requested.append(url)
        answer = self.answers.get(url, 200)
        if isinstance(answer, Exception):
            raise answer
        return FetchResponse(url, answer, "text/html", "utf-8", {}, b"<html></html>")


LAST_MONTH = utc(2026, 10, 1, 23)


def past(n: int = 1, *, start: datetime = LAST_MONTH, **overrides: Any) -> Event:
    return make_event(url=f"https://e{n}.example.org/e", start=start, **overrides)


def flags(events: list[Event]) -> dict[str, bool]:
    return {e.original_url: e.original_unavailable for e in events}


@pytest.mark.parametrize("status", [404, 410])
def test_a_gone_page_is_flagged(status: int) -> None:
    event = past()
    updated, report = check_links([event], FakeHttp({event.original_url: status}), now=NOW)
    assert flags(updated) == {event.original_url: True}
    assert (report.checked, report.unavailable) == (1, 1)


def test_a_page_that_is_back_is_unflagged() -> None:
    event = past(original_unavailable=True)
    updated, report = check_links([event], FakeHttp(), now=NOW)
    assert flags(updated) == {event.original_url: False}
    assert (report.checked, report.unavailable) == (1, 0)


def test_a_reachable_page_that_is_not_html_counts_as_there() -> None:
    event = past(original_unavailable=True)
    http = FakeHttp({event.original_url: ContentTypeNotAllowedError("a PDF")})
    updated, _ = check_links([event], http, now=NOW)
    assert flags(updated) == {event.original_url: False}


@pytest.mark.parametrize(
    "answer", [403, 429, 500, 503, FetchError("timeout"), RobotsDisallowedError("robots")]
)
def test_anything_unclear_leaves_the_flag_alone(answer: int | Exception) -> None:
    flagged, fine = past(1, original_unavailable=True), past(2)
    http = FakeHttp({flagged.original_url: answer, fine.original_url: answer})
    updated, report = check_links([flagged, fine], http, now=NOW)
    assert flags(updated) == {flagged.original_url: True, fine.original_url: False}
    assert report.checked == 0


def test_only_public_past_events_are_checked() -> None:
    events = [
        past(1),
        past(2, start=utc(2026, 11, 20, 23)),  # upcoming
        past(3, review_state="pending_review"),
        past(4, visibility="hidden"),
        past(5, start=utc(2026, 10, 31, 23), end=utc(2026, 11, 1, 15)),  # still running
    ]
    http = FakeHttp()
    check_links(events, http, now=NOW)
    assert http.requested == ["https://e1.example.org/e"]


def test_at_most_fifty_links_a_run_and_other_months_check_others() -> None:
    events = [past(n) for n in range(120)]
    seen: set[str] = set()
    for month in range(1, 4):
        http = FakeHttp()
        check_links(events, http, now=utc(2027, month, 1, 11))
        assert len(http.requested) == MAX_CHECKS == 50
        seen.update(http.requested)
    assert len(seen) == 120  # three months cover all 120


def test_a_host_out_of_budget_is_skipped_for_the_rest_of_the_run() -> None:
    same_host = [
        make_event(url=f"https://busy.example.org/e/{n}", start=utc(2026, 10, n, 23))
        for n in range(1, 4)
    ]
    other = past(9, original_unavailable=True)
    out_of_budget = BudgetExceededError("busy.example.org")
    http = FakeHttp({e.original_url: out_of_budget for e in same_host})
    updated, report = check_links([*same_host, other], http, now=NOW)
    assert sum("busy.example.org" in url for url in http.requested) == 1
    assert other.original_url in http.requested
    assert flags(updated)[other.original_url] is False
    assert report.checked == 1


def test_events_keep_their_order_and_unchecked_ones_are_unchanged() -> None:
    events = [past(n) for n in range(3)]
    http = FakeHttp({events[1].original_url: 404})
    updated, _ = check_links(events, http, now=NOW)
    assert [e.id for e in updated] == [e.id for e in events]
    assert updated[0] is events[0] and updated[2] is events[2]


@pytest.mark.parametrize(
    ("now", "expected"),
    [(utc(2026, 11, 1, 11), True), (utc(2026, 11, 1, 23), True), (utc(2026, 11, 2, 11), False)],
)
def test_it_runs_on_the_first_day_of_the_month(now: datetime, expected: bool) -> None:
    assert due(now) is expected
