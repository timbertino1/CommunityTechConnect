"""The gap finder: targeted searches for quiet groups, annual events and known groups with no
working source (T089; research R7; FR-013)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest

from netc.finders.base import FinderContext, FinderResult
from netc.finders.gaps import MAX_GAP_QUERIES, RESEARCH_AFTER, GapFinder
from netc.models import AreaConfig, Event, KnownGroup, SearchUsage
from netc.pipeline.coverage import annual_series_due, series_title
from netc.search.base import BudgetedSearch, SearchResult
from netc.storage import DataStore
from tests.ai_support import NOW
from tests.data_samples import make_event, make_source

pytestmark = pytest.mark.unit

REPO = DataStore(Path(__file__).resolve().parents[3] / "data")
AREAS: AreaConfig = REPO.read_areas()  # type: ignore[assignment]


class Provider:
    name: ClassVar[str] = "fake"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        return [
            SearchResult(
                "Found it",
                f"https://found-{len(self.queries)}.example.org/events",
                "Upcoming meetups in Omaha, Nebraska",
            )
        ]


def run(provider: Provider, **kw: Any) -> FinderResult:
    search = BudgetedSearch(provider, SearchUsage(month="2026-10", used=0, last_run={}), now=NOW)
    return GapFinder().run(FinderContext(now=NOW, areas=AREAS, search=search, **kw))


def past(source_id: str, days_ago: list[int], title: str = "Meetup") -> list[Event]:
    return [
        make_event(
            slug=f"{source_id.replace('_', '-')}-{d}",
            start=NOW - timedelta(days=d),
            title=title,
            url=f"https://example.org/{source_id}/{d}/",
            source_id=source_id,
        )
        for d in days_ago
    ]


def test_a_quiet_group_is_searched_for_by_name() -> None:
    provider = Provider()
    source = make_source("src_quiet", name="Omaha Quiet Devs")
    result = run(provider, sources=[source], events=past("src_quiet", [40, 54, 68, 82]))
    assert provider.queries == ['"Omaha Quiet Devs" Nebraska events']
    [lead] = result.candidates
    assert lead.found_via == "gap"
    assert lead.evidence[0] == 'gap check: quiet group: "Omaha Quiet Devs" Nebraska events'


def test_an_annual_event_is_searched_for_ten_months_on() -> None:
    events = [
        make_event(
            slug="c-2024",
            title="Nebraska.Code() 2024",
            start=NOW - timedelta(days=760),
            url="https://nebraskacode.example.org/2024",
            organizer_id="org_nc",
        ),
        make_event(
            slug="c-2025",
            title="Nebraska.Code() 2025",
            start=NOW - timedelta(days=395),
            url="https://nebraskacode.example.org/2025",
            organizer_id="org_nc",
        ),
    ]
    [series] = annual_series_due(events, NOW)
    assert series.title == "Nebraska.Code()"
    provider = Provider()
    run(provider, events=events)
    assert provider.queries == ['"Nebraska.Code()" 2026']


def test_series_titles_drop_years() -> None:
    assert series_title("INTERFACE Omaha 2026") == "INTERFACE Omaha"
    assert series_title("Fall Event 2026 - (NE)NUG") == "Fall Event - (NE)NUG"


def test_a_series_with_its_next_edition_listed_is_not_due() -> None:
    events = [
        make_event(
            slug="a",
            title="Kernelcon 2025",
            start=NOW - timedelta(days=400),
            url="https://kernelcon.example.org/2025",
        ),
        make_event(
            slug="b",
            title="Kernelcon 2026",
            start=NOW - timedelta(days=35),
            url="https://kernelcon.example.org/2026",
        ),
    ]
    assert annual_series_due(events, NOW) == []


def test_known_groups_without_a_working_source_are_searched_monthly() -> None:
    groups = [
        KnownGroup(name="ISACA Omaha", area="omaha"),
        KnownGroup(name="Searched lately", last_searched=NOW - timedelta(days=5)),
        KnownGroup(name="Has a source", source_ids=["src_ok"]),
        KnownGroup(name="Paused source", source_ids=["src_paused"]),
        KnownGroup(name="Defunct", status="defunct"),
    ]
    sources = [make_source("src_ok"), make_source("src_paused", status="paused")]
    provider = Provider()
    result = run(provider, known_groups=groups, sources=sources)
    assert provider.queries == ['"ISACA Omaha" Omaha', '"Paused source" Nebraska']
    assert set(result.searched_groups) == {"ISACA Omaha", "Paused source"}
    assert timedelta(days=30) == RESEARCH_AFTER


def test_at_most_max_gap_queries_a_run() -> None:
    groups = [KnownGroup(name=f"Group {i}") for i in range(40)]
    provider = Provider()
    run(provider, known_groups=groups)
    assert len(provider.queries) == MAX_GAP_QUERIES == 15


def test_no_search_means_no_gap_checks() -> None:
    result = GapFinder().run(FinderContext(now=NOW, areas=AREAS))
    assert result.stats["skipped_no_search"] == 1
