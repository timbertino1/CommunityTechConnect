"""Resolving mentions to the organizer's event page (T091; FR-014)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import pytest

from netc.fetch import FixtureHttp
from netc.finders.base import make_mention
from netc.models import EventMention, SearchUsage
from netc.pipeline.resolve import MAX_ATTEMPTS, parse_date_hint, resolve_mentions
from netc.search.base import BudgetedSearch, SearchResult
from tests.ai_support import NOW
from tests.data_samples import make_event

pytestmark = pytest.mark.unit

PAGES = Path(__file__).resolve().parents[1] / "fixtures" / "finders" / "pages"
EVENT_PAGE = "https://heartlandrust.example.org/events/rust-night-nov"


def http(tmp_path: Path) -> FixtureHttp:
    index = {EVENT_PAGE: {"file": str(PAGES / "jsonld_events.html"), "content_type": "text/html"}}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return FixtureHttp(tmp_path)


def mention(title: str = "Rust Night", links: list[str] | None = None, **kw: Any) -> EventMention:
    made = make_mention(
        title,
        links if links is not None else [EVENT_PAGE],
        channel="newsletter",
        date_hint=kw.pop("date_hint", "Nov 18"),
    )
    assert made is not None
    return made.model_copy(update=kw)


class Finds:
    name: ClassVar[str] = "fake"

    def __init__(self, url: str) -> None:
        self.url = url
        self.queries: list[str] = []

    def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        return [SearchResult("Rust Night", self.url, "Omaha")]


def search(provider: Any) -> BudgetedSearch:
    return BudgetedSearch(provider, SearchUsage(month="2026-10", used=0, last_run={}), now=NOW)


def test_a_mention_whose_link_has_the_event_is_resolved(tmp_path: Path) -> None:
    result = resolve_mentions([mention()], http=http(tmp_path), now=NOW)
    [m] = result.mentions
    assert m.resolution == "resolved"
    [candidate] = result.candidates
    assert candidate.url == "https://heartlandrust.example.org/"
    assert candidate.found_via == "newsletter"
    assert candidate.evidence[0] == "resolved mention: Rust Night"


def test_a_resolved_mention_points_at_a_stored_event(tmp_path: Path) -> None:
    stored = make_event(url=EVENT_PAGE, slug="rust-night")
    result = resolve_mentions([mention()], http=http(tmp_path), now=NOW, events=[stored])
    assert result.mentions[0].event_id == stored.id


def test_a_mention_without_links_is_searched_for(tmp_path: Path) -> None:
    provider = Finds(EVENT_PAGE)
    result = resolve_mentions(
        [mention(links=[], place_hint="Omaha")],
        http=http(tmp_path),
        now=NOW,
        search=search(provider),
    )
    assert provider.queries == ['"Rust Night" Omaha']
    assert result.mentions[0].resolution == "resolved"


def test_a_page_without_the_event_does_not_resolve_and_counts_a_try(tmp_path: Path) -> None:
    result = resolve_mentions([mention("Totally different talk")], http=http(tmp_path), now=NOW)
    [m] = result.mentions
    assert (m.resolution, m.attempts) == ("unresolved", 1)
    assert result.candidates == []


def test_after_four_tries_a_mention_is_discarded(tmp_path: Path) -> None:
    tired = mention("Never found", attempts=MAX_ATTEMPTS)
    assert (
        resolve_mentions([tired], http=http(tmp_path), now=NOW).mentions[0].resolution
        == "discarded"
    )
    assert MAX_ATTEMPTS == 4


def test_a_mention_whose_date_has_passed_is_discarded(tmp_path: Path) -> None:
    old = mention("Rust Night", date_hint="Oct 1")
    assert (
        resolve_mentions([old], http=http(tmp_path), now=NOW).mentions[0].resolution == "discarded"
    )


def test_resolved_and_discarded_mentions_are_left_alone(tmp_path: Path) -> None:
    done = [mention(resolution="resolved"), mention("B", resolution="discarded")]
    assert resolve_mentions(done, http=http(tmp_path), now=NOW).mentions == done


def test_nothing_is_ever_published(tmp_path: Path) -> None:
    result = resolve_mentions([mention()], http=http(tmp_path), now=NOW)
    assert not hasattr(result, "events")  # resolution only finds pages and candidates


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("Nov 12", date(2026, 11, 12)),
        ("Thu, Nov 12, 6 PM", date(2026, 11, 12)),
        ("November 5, 2026", date(2026, 11, 5)),
        ("Jan 15", date(2027, 1, 15)),  # next year once the month has gone by
        ("Oct 1", date(2026, 10, 1)),
        ("sometime soon", None),
        (None, None),
    ],
)
def test_date_hints_are_read(hint: str | None, expected: date | None) -> None:
    assert parse_date_hint(hint, NOW) == expected
