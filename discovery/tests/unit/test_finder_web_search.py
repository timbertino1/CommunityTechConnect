"""The web search finder: weekly search results become candidate sources and mentions (T086;
research R6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from netc.finders.base import FinderContext, lead_from_result, site_key
from netc.finders.web_search import WebSearchFinder
from netc.models import AreaConfig, CandidateSource, EventMention, SearchUsage
from netc.search.base import BudgetedSearch, SearchError, SearchResult
from netc.storage import DataStore
from tests.ai_support import NOW
from tests.data_samples import make_source

pytestmark = pytest.mark.unit

REPO = DataStore(Path(__file__).resolve().parents[3] / "data")
AREAS: AreaConfig = REPO.read_areas()  # type: ignore[assignment]
SEARCH = Path(__file__).resolve().parents[1] / "fixtures" / "finders" / "search"


def recorded(name: str) -> list[SearchResult]:
    data = json.loads((SEARCH / name).read_text(encoding="utf-8"))
    return [SearchResult(r["title"], r["url"], r["content"]) for r in data["results"]]


class Recorded:
    name: ClassVar[str] = "recorded"

    def __init__(
        self,
        by_query: dict[str, list[SearchResult]] | None = None,
        fallback: list[SearchResult] | None = None,
        fail: bool = False,
    ) -> None:
        self.by_query = by_query or {}
        self.fallback = fallback or []
        self.fail = fail
        self.queries: list[str] = []

    def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        if self.fail:
            raise SearchError("down")
        return self.by_query.get(query, self.fallback)


def context(provider: Any = None, *, budget: int = 400, **kw: Any) -> FinderContext:
    search = None
    if provider is not None:
        usage = SearchUsage(month="2026-10", used=0, last_run={})
        search = BudgetedSearch(provider, usage, now=NOW, budget=budget)
    return FinderContext(now=NOW, areas=AREAS, search=search, **kw)


# --- Site keys


@pytest.mark.parametrize(
    ("url", "key"),
    [
        (
            "https://www.meetup.com/omaha-data-engineers/events/123/",
            "meetup.com/omaha-data-engineers",
        ),
        ("https://meetup.com/Omaha-Data-Engineers/", "meetup.com/omaha-data-engineers"),
        ("https://lu.ma/omaha-ai?utm=x", "lu.ma/omaha-ai"),
        ("https://www.eventbrite.com/o/acme-123", "eventbrite.com/o/acme-123"),
        ("https://www.heartlandrust.example.org/events", "heartlandrust.example.org"),
    ],
)
def test_site_keys_tell_sites_and_platform_groups_apart(url: str, key: str) -> None:
    assert site_key(url) == key


# --- One result at a time


def lead(title: str, url: str, snippet: str = "") -> CandidateSource | EventMention | None:
    return lead_from_result(
        SearchResult(title, url, snippet),
        found_via="web_search",
        evidence="web search: test",
        now=NOW,
        areas=AREAS,
    )


def test_a_meetup_group_becomes_a_candidate_at_its_group_page() -> None:
    found = lead("Omaha Data Engineers", "https://www.meetup.com/omaha-data-engineers/events/9/")
    assert isinstance(found, CandidateSource)
    assert found.url == "https://www.meetup.com/omaha-data-engineers/"
    assert found.found_via == "web_search" and found.result == "pending"
    assert found.evidence == ["web search: test", "result: Omaha Data Engineers"]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.meetup.com/register/",
        "https://www.meetup.com/find/us--ne--omaha/",
        "https://www.facebook.com/groups/omahatech",
        "https://www.linkedin.com/company/acme",
        "https://en.wikipedia.org/wiki/Omaha",
    ],
)
def test_platform_pages_and_social_sites_are_not_candidates(url: str) -> None:
    assert lead("Something", url) is None


def test_results_that_name_another_state_are_skipped() -> None:
    assert (
        lead(
            "Big Sky Devs",
            "https://bigskydevs.example.org/",
            "Monthly meetup for developers in Denver, Colorado.",
        )
        is None
    )


@pytest.mark.parametrize(
    ("title", "url", "snippet"),
    [
        # Real results from the Oct 25 run: "Omaha cloud user group" and "Lincoln tech conference".
        ("India Cricket Team Schedule, Results & Timetable",
         "https://www.cricinfo.com/team/india-6/match-schedule-fixtures-and-results",
         "Upcoming matches, series and fixtures."),
        ("Dayton International Airport - Easy to and Through", "https://flydayton.com/",
         "Nonstop flights to 14 destinations."),
        ("Cloud Native Days", "https://news.example.com/2026/10/cloud-native-days",
         "A conference for platform engineers."),
    ],
)  # fmt: skip
def test_results_that_name_no_nebraska_place_are_skipped(
    title: str, url: str, snippet: str
) -> None:
    assert lead(title, url, snippet) is None


@pytest.mark.parametrize(
    ("title", "url", "snippet"),
    [
        ("Data engineers meetup", "https://www.meetup.com/omaha-data-engineers/", ""),
        ("Python Users Group", "https://pyugs.example.org/", "Monthly talks in Lincoln, NE."),
        ("Heartland Rust Users", "https://rust.example.org/", "Rust meetups across Nebraska."),
        ("Kearney Coders", "https://kearneycoders.example.org/", "Coffee and code."),
    ],
)  # fmt: skip
def test_a_nebraska_place_in_the_title_snippet_or_address_is_enough(
    title: str, url: str, snippet: str
) -> None:
    assert lead(title, url, snippet) is not None


def test_gap_check_results_need_no_place(  # their queries name the group itself
) -> None:
    found = lead_from_result(
        SearchResult("Heartland Rust Users", "https://rust.example.org/", "Monthly meetups."),
        found_via="gap",
        evidence="gap: Heartland Rust Users",
        now=NOW,
        areas=AREAS,
    )
    assert isinstance(found, CandidateSource)


def test_news_articles_become_mentions_not_sources() -> None:
    found = lead(
        "Cyber Night at The Mill (News)",
        "https://news.example.com/2026/10/cyber-night-the-mill",
        "The Lincoln Security Collective hosts Cyber Night on Nov 12.",
    )
    assert isinstance(found, EventMention)
    assert found.channel == "web_search" and found.resolution == "unresolved"
    assert found.links == ["https://news.example.com/2026/10/cyber-night-the-mill"]


def test_an_ordinary_site_is_a_candidate_as_found() -> None:
    found = lead(
        "Lincoln Security Collective",
        "https://lincolnsec.example.org/events",
        "Monthly cybersecurity talks in Lincoln, Nebraska.",
    )
    assert (
        isinstance(found, CandidateSource) and found.url == "https://lincolnsec.example.org/events"
    )


# --- The finder


def test_the_weekly_queries_run_and_known_sites_are_skipped() -> None:
    provider = Recorded(fallback=recorded("omaha_meetup.json"))
    known = make_source("src_known", url="https://heartlandrust.example.org/")
    result = WebSearchFinder().run(context(provider, sources=[known]))
    assert len(provider.queries) == 40
    urls = {c.url for c in result.candidates}
    assert urls == {"https://www.meetup.com/omaha-data-engineers/"}  # denver, register, known gone
    assert result.stats["queries"] == 40
    assert result.stats["results"] == 160


def test_candidates_and_mentions_are_deduplicated_across_queries() -> None:
    provider = Recorded(fallback=recorded("lincoln_security.json"))
    result = WebSearchFinder().run(context(provider))
    assert [c.url for c in result.candidates] == ["https://lincolnsec.example.org/events"]
    assert len(result.mentions) == 1


def test_already_known_candidates_are_skipped() -> None:
    provider = Recorded(fallback=recorded("lincoln_security.json"))
    old = CandidateSource(
        url="https://lincolnsec.example.org/",
        found_via="link_graph",
        evidence=["x"],
        result="rejected",
        reason="no tech events",
        last_evaluated=NOW,
    )
    result = WebSearchFinder().run(context(provider, candidates=[old]))
    assert result.candidates == []


def test_the_budget_stops_the_sweep() -> None:
    provider = Recorded(fallback=[])
    result = WebSearchFinder().run(context(provider, budget=5))
    assert len(provider.queries) == 5
    assert result.stats["budget_exhausted"] == 1


def test_search_errors_are_counted_and_the_sweep_goes_on() -> None:
    provider = Recorded(fail=True)
    result = WebSearchFinder().run(context(provider))
    assert result.stats["errors"] == 40 and result.candidates == []


def test_no_search_provider_means_nothing_to_do() -> None:
    result = WebSearchFinder().run(context(None))
    assert result.stats == {"skipped_no_search": 1}
