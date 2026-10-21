"""Web search: the provider interface, Tavily, the monthly budget and the weekly queries (T078;
research R6, gate V4)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from netc.fetch.api import ApiResponse
from netc.models import SearchUsage
from netc.search.base import (
    MONTHLY_QUERY_BUDGET,
    BudgetedSearch,
    SearchBudgetExhaustedError,
    SearchError,
    SearchProvider,
    SearchResult,
)
from netc.search.queries import WEEKLY_QUERIES, all_queries, weekly_queries
from netc.search.tavily import TAVILY_URL, TavilyProvider
from netc.storage import DataStore

pytestmark = pytest.mark.unit

SEARCH = Path(__file__).resolve().parents[1] / "fixtures" / "finders" / "search"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
KEY = "test-search-key-not-real"


class FakeApi:
    def __init__(self, status: int = 200, data: Any = None) -> None:
        self.status = status
        self.data = data if data is not None else {"results": []}
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def post_json(
        self, url: str, payload: Mapping[str, Any], *, headers: Mapping[str, str]
    ) -> ApiResponse:
        self.calls.append((url, dict(payload), dict(headers)))
        return ApiResponse(self.status, self.data)


class FakeProvider:
    name: ClassVar[str] = "fake"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        return [SearchResult("Omaha Data Engineers", "https://data.example.org/", "Monthly talks")]


def recorded(name: str) -> Any:
    return json.loads((SEARCH / name).read_text(encoding="utf-8"))


# --- The interface


def test_tavily_and_fakes_satisfy_the_interface() -> None:
    providers: list[SearchProvider] = [TavilyProvider(KEY, FakeApi()), FakeProvider()]
    assert {p.name for p in providers} == {"tavily", "fake"}


# --- Tavily


def test_tavily_sends_a_basic_search_with_the_key_in_a_header() -> None:
    api = FakeApi(data=recorded("omaha_meetup.json"))
    TavilyProvider(KEY, api).search("Omaha tech meetup", count=5)
    [(url, payload, headers)] = api.calls
    assert url == TAVILY_URL
    assert payload["query"] == "Omaha tech meetup"
    assert payload["max_results"] == 5
    assert payload["search_depth"] == "basic"  # 1 credit per search
    assert payload.get("include_raw_content") is False
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert KEY not in json.dumps(payload)


def test_tavily_results_become_search_results() -> None:
    results = TavilyProvider(KEY, FakeApi(data=recorded("omaha_meetup.json"))).search("q")
    assert [r.url for r in results] == [
        "https://www.meetup.com/omaha-data-engineers/",
        "https://bigskydevs.example.org/",
        "https://heartlandrust.example.org/",
        "https://www.meetup.com/register/",
    ]
    first = results[0]
    assert first.title == "Omaha Data Engineers | Meetup"
    assert first.snippet.startswith("A community for data engineers")


def test_unsafe_or_malformed_results_are_dropped() -> None:
    data = {
        "results": [
            {"title": "ok", "url": "https://good.example.org/", "content": "fine"},
            {"title": "http", "url": "http://plain.example.org/", "content": "x"},
            {"title": "js", "url": "javascript:alert(1)", "content": "x"},
            {"title": "ip", "url": "https://10.0.0.5/", "content": "x"},
            {"url": "https://no-title.example.org/"},
            "not an object",
        ]
    }
    results = TavilyProvider(KEY, FakeApi(data=data)).search("q")
    assert [r.url for r in results] == [
        "https://good.example.org/",
        "https://no-title.example.org/",
    ]
    assert results[1].title == ""


def test_result_text_is_plain_and_capped() -> None:
    data = {"results": [{"title": "<b>Bold</b> group", "url": "https://a.example.org/",
                         "content": "<script>x</script>" + "word " * 500}]}  # fmt: skip
    [result] = TavilyProvider(KEY, FakeApi(data=data)).search("q")
    assert result.title == "Bold group"
    assert "<" not in result.snippet and len(result.snippet) <= 600


@pytest.mark.parametrize(("status", "data"), [(401, {"detail": "bad key"}), (500, {}), (200, [])])
def test_errors_raise_without_echoing_the_key(status: int, data: Any) -> None:
    with pytest.raises(SearchError) as caught:
        TavilyProvider(KEY, FakeApi(status=status, data=data)).search("q")
    assert KEY not in str(caught.value)


def test_the_key_comes_from_the_environment() -> None:
    assert TavilyProvider.from_env(FakeApi(), {"SEARCH_API_KEY": KEY}).name == "tavily"
    with pytest.raises(SearchError, match="SEARCH_API_KEY"):
        TavilyProvider.from_env(FakeApi(), {})


# --- The monthly budget


def fresh_usage() -> SearchUsage:
    return SearchUsage(month="2026-10", used=0, last_run={})


def test_each_query_counts_and_records_only_its_date() -> None:
    provider = FakeProvider()
    search = BudgetedSearch(provider, fresh_usage(), now=NOW)
    assert search.search("Omaha tech meetup")[0].url == "https://data.example.org/"
    assert search.usage == SearchUsage(
        month="2026-10", used=1, last_run={"Omaha tech meetup": date(2026, 10, 20)}
    )


def test_calls_stop_when_the_budget_is_reached() -> None:
    provider = FakeProvider()
    usage = SearchUsage(month="2026-10", used=MONTHLY_QUERY_BUDGET - 1, last_run={})
    search = BudgetedSearch(provider, usage, now=NOW)
    search.search("one more")
    with pytest.raises(SearchBudgetExhaustedError):
        search.search("too many")
    assert provider.queries == ["one more"]
    assert search.remaining == 0


def test_a_new_month_starts_a_new_budget_and_keeps_the_dates() -> None:
    old = SearchUsage(month="2026-09", used=MONTHLY_QUERY_BUDGET,
                      last_run={"Omaha tech meetup": date(2026, 9, 28)})  # fmt: skip
    search = BudgetedSearch(FakeProvider(), old, now=NOW)
    assert search.remaining == MONTHLY_QUERY_BUDGET
    search.search("Lincoln AI meetup")
    assert search.usage.month == "2026-10" and search.usage.used == 1
    assert search.usage.last_run["Omaha tech meetup"] == date(2026, 9, 28)


def test_the_budget_is_well_under_the_free_plan() -> None:
    # Tavily's free plan is 1,000 searches a month; weekly queries use about 175.
    assert WEEKLY_QUERIES * 5 <= MONTHLY_QUERY_BUDGET <= 500


def test_a_failed_call_still_counts(tmp_path: Path) -> None:
    class Failing(FakeProvider):
        def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
            raise SearchError("down")

    search = BudgetedSearch(Failing(), fresh_usage(), now=NOW)
    with pytest.raises(SearchError):
        search.search("q")
    assert search.usage.used == 1  # the provider may have charged for it


def test_results_are_never_written_to_data(tmp_path: Path) -> None:
    store = DataStore(tmp_path)
    search = BudgetedSearch(FakeProvider(), store.read_search_usage(now=NOW), now=NOW)
    search.search("Omaha tech meetup")
    store.write_search_usage(search.usage)
    written = {p.relative_to(tmp_path).as_posix(): p.read_text(encoding="utf-8")
               for p in tmp_path.rglob("*") if p.is_file()}  # fmt: skip
    assert list(written) == ["state/search_usage.json"]
    text = written["state/search_usage.json"]
    assert "data.example.org" not in text and "Monthly talks" not in text
    assert DataStore(tmp_path).read_search_usage(now=NOW) == search.usage


def test_no_usage_file_means_a_fresh_month(tmp_path: Path) -> None:
    assert DataStore(tmp_path).read_search_usage(now=NOW) == fresh_usage()


# --- The weekly queries


def test_queries_combine_topics_and_places() -> None:
    queries = all_queries()
    assert len(queries) == len(set(queries))
    assert "Omaha cybersecurity meetup" in queries
    assert "Lincoln AI user group" in queries
    assert "Nebraska tech hackathon" in queries
    assert all(any(p in q for p in ("Omaha", "Lincoln", "Nebraska")) for q in queries)
    assert len(queries) > WEEKLY_QUERIES  # not every query runs every week


def test_about_forty_queries_a_week() -> None:
    assert WEEKLY_QUERIES == 40
    assert len(weekly_queries({})) == 40


def test_least_recently_run_queries_go_first() -> None:
    queries = all_queries()
    last_run = {q: date(2026, 10, 13) for q in queries[:40]}  # last week's batch
    this_week = weekly_queries(last_run)
    assert set(this_week[: len(queries) - 40]) == set(queries[40:])  # never-run first
    assert weekly_queries(last_run) == this_week  # deterministic
