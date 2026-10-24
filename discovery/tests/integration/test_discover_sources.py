"""`discover-sources` end to end, offline (T094; quickstart scenario 2).

From a small starting set, one run finds Nebraska groups through at least three kinds of
channel, adds them on probation, rejects out-of-state and non-tech sites, and publishes nothing
from mentions it couldn't resolve.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from netc.cli import main
from netc.connectors import default_connectors
from netc.fetch import FixtureHttp
from netc.github.review_pr import build_review_pr
from netc.models import KnownGroup, Organizer, SearchUsage
from netc.pipeline.discover_sources import DiscoverSourcesReport, discover_sources
from netc.pipeline.sources_report import render_sources_markdown
from netc.search.base import BudgetedSearch
from netc.search.offline import FixtureSearch
from netc.storage import DataStore
from tests.data_samples import make_source

pytestmark = pytest.mark.integration

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "integration_sources"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
FEED = "https://news.example.com/feed/"


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    for name in ("categories.yaml", "areas.yaml"):
        shutil.copy(REPO_DATA / name, root / name)
    store = DataStore(root)
    store.write_source(
        make_source(
            "src_prairie-python",
            name="Prairie Python",
            url="https://www.meetup.com/prairie-python/events/",
            connector="jsonld",
        )
    )
    store.write_organizers(
        [
            Organizer(
                id="org_spb", name="Silicon Prairie Builders", url="https://spbuilders.example.org/"
            )
        ]
    )
    store.write_known_groups(
        [
            KnownGroup(name="Heartland Rust Users", area="omaha"),
            KnownGroup(name="ISACA Omaha", area="omaha"),
        ]
    )
    return root


def run(root: Path, *, dry_run: bool = False, **kw: Any) -> DiscoverSourcesReport:
    store = DataStore(root)
    search = BudgetedSearch(
        FixtureSearch(FIXTURES / "search_index.json"), store.read_search_usage(now=NOW), now=NOW
    )
    return discover_sources(
        store,
        FixtureHttp(FIXTURES),
        default_connectors(lambda: NOW),
        now=NOW,
        search=search,
        news_feeds=[FEED],
        dry_run=dry_run,
        **{"log": lambda _line: None, **kw},
    )


def test_new_groups_are_found_through_three_kinds_of_channel(data: Path) -> None:
    report = run(data)
    added = {s.id: s for s in report.added}
    assert set(added) == {
        "src_omaha-data-engineers",
        "src_heartlandrust-example-org",
        "src_lincolnsec-example-org",
        "src_news-example-com",
    }
    assert {s.found_via for s in added.values()} == {"web_search", "link_graph", "news"}
    assert all(s.trust == "probationary" and s.origin == "discovered" for s in added.values())
    stored = {s.id for s in DataStore(data).read_sources()}
    assert set(added) <= stored


def test_out_of_state_and_non_tech_sites_are_rejected(data: Path) -> None:
    run(data)
    by_url = {c.url: c for c in DataStore(data).read_candidates()}
    assert by_url["https://kccloud.example.org/"].result == "rejected"
    assert (
        by_url["https://kccloud.example.org/"].reason == "its upcoming events are outside Nebraska"
    )
    assert by_url["https://yoga.example.org/"].result == "rejected"
    assert "https://bigskydevs.example.org/" not in by_url  # named another state: never a candidate


def test_mentions_are_never_published(data: Path) -> None:
    run(data)
    store = DataStore(data)
    mentions = {m.title: m for m in store.read_mentions()}
    assert mentions["Omaha Data Engineers: Streaming Night"].resolution == "resolved"
    article = mentions["Cyber Night coming to The Mill"]
    assert (article.resolution, article.attempts) == ("unresolved", 1)
    assert store.read_events() == []  # discover-sources never writes events


def test_known_groups_gain_their_new_source_and_record_searches(data: Path) -> None:
    run(data)
    groups = {g.name: g for g in DataStore(data).read_known_groups()}
    rust = groups["Heartland Rust Users"]
    assert rust.source_ids == ["src_heartlandrust-example-org"]
    assert groups["ISACA Omaha"].last_searched == NOW
    assert "Lincoln Security Collective" in groups  # a new group the run learned about


def test_a_second_run_finds_nothing_new(data: Path) -> None:
    run(data)
    again = run(data)
    assert again.added == [] and sum(again.found.values()) == 0


def test_search_usage_is_recorded_without_results(data: Path) -> None:
    run(data)
    usage = DataStore(data).read_search_usage(now=NOW)
    assert isinstance(usage, SearchUsage) and usage.used > 40
    text = (data / "state" / "search_usage.json").read_text(encoding="utf-8")
    assert "kccloud.example.org" not in text and "Rust meetups" not in text  # results, not queries


def test_the_data_validates_and_the_report_says_what_happened(data: Path) -> None:
    report = run(data)
    assert main(["validate-data", "--data-dir", str(data)]) == 0
    text = render_sources_markdown(report)
    assert "**4 added on probation**" in text
    assert "### Added on probation" in text and "`https://kccloud.example.org/`" in text


def test_a_dry_run_writes_nothing(data: Path) -> None:
    before = sorted(p.relative_to(data).as_posix() for p in data.rglob("*") if p.is_file())
    run(data, dry_run=True)
    after = sorted(p.relative_to(data).as_posix() for p in data.rglob("*") if p.is_file())
    assert after == before


def test_the_command_runs_offline(data: Path, tmp_path: Path) -> None:
    report = tmp_path / "sources.md"
    code = main(
        [
            "discover-sources",
            "--data-dir",
            str(data),
            "--offline",
            "--fixtures",
            str(FIXTURES),
            "--search-fixtures",
            str(FIXTURES / "search_index.json"),
            "--news-feed",
            FEED,
            "--now",
            "2026-10-20T12:00:00Z",
            "--report",
            str(report),
        ]
    )
    assert code == 0
    assert report.read_text(encoding="utf-8").startswith("## Finding new groups")
    # The documented command reaches all three channels, like the in-process run (T105).
    added = [s for s in DataStore(data).read_sources() if s.origin == "discovered"]
    assert {s.found_via for s in added} == {"web_search", "link_graph", "news"}


def test_evaluation_stops_at_the_time_budget_and_the_rest_wait(data: Path) -> None:
    # Each clock reading is 10 minutes later: the budget runs out after the finders.
    ticks = iter(range(0, 100_000, 600))
    report = run(data, clock=lambda: float(next(ticks)), time_budget_seconds=40 * 60)
    assert report.stopped_for_time
    assert report.evaluated["deferred"] > 0 and not report.added
    pending = [c for c in DataStore(data).read_candidates() if c.result == "pending"]
    assert len(pending) == report.evaluated["deferred"]  # kept for the next run
    text = render_sources_markdown(report)
    assert "time limit" in text and f"{report.evaluated['deferred']} candidates wait" in text


def test_each_stage_is_logged_with_its_time(data: Path) -> None:
    lines: list[str] = []
    run(data, log=lines.append)
    events = [json.loads(x) for x in lines]
    stages = [e["stage"] for e in events if e.get("event") == "stage_done"]
    assert stages[-3:] == ["finders", "mentions", "evaluation"]
    assert all(isinstance(e["seconds"], float) for e in events if e.get("event") == "stage_done")
    assert any(e.get("event") == "finder_done" for e in events)


def test_mentions_stop_at_their_own_budget_and_the_report_says_so(data: Path) -> None:
    # Every clock reading is 5 minutes later; the mention stage gets 10 minutes of the run.
    ticks = iter(range(0, 100_000, 300))
    report = run(data, clock=lambda: float(next(ticks)), mentions_budget_seconds=10 * 60)
    assert report.mentions["deferred"] > 0
    assert "wait for the next run" in render_sources_markdown(report).split("### Mentions")[1]


# --- Visitors' suggestions (T133; FR-020, FR-022)

NOTE = "Private note: ask Pat about the Tuesday group"
SUGGESTED = {
    "https://heartlandrust.example.org/": "added",
    "https://yoga.example.org/": "rejected",
    "https://nowhere.example.org/": "needs_review",  # can't be read: a person decides
    "https://www.facebook.com/omaha-tech": None,  # not a source page: straight to review
}


class FakeSuggestions:
    def __init__(self, urls: list[str], *, failing: bool = False) -> None:
        self.values = {
            f"suggestion:{i:08d}-0000-4000-8000-000000000000": json.dumps(
                {"url": url, "note": NOTE, "received_at": "2026-10-19T09:00:00Z"}
            ).encode()
            for i, url in enumerate(urls)
        }
        self.failing = failing
        self.deleted: list[str] = []

    def keys(self) -> list[str]:
        if self.failing:
            from netc.inbox.kv import InboxError

            raise InboxError("could not list the inbox (HTTP 403)")
        return list(self.values)

    def read(self, key: str) -> bytes | None:
        return self.values.get(key)

    def delete(self, key: str) -> None:
        self.deleted.append(key)


def suggest(data: Path, **kw: Any) -> tuple[DiscoverSourcesReport, FakeSuggestions]:
    inbox = FakeSuggestions(list(SUGGESTED))
    return run(data, finders=[], suggestions=inbox, **kw), inbox


def test_suggestions_are_evaluated_like_any_other_candidate(data: Path) -> None:
    report, inbox = suggest(data)
    results = {c.url: c.result for c in DataStore(data).read_candidates()}
    for url, expected in SUGGESTED.items():
        if expected is not None:
            assert results[url] == expected, url
    [added] = report.added
    assert (added.id, added.origin, added.found_via) == (
        "src_heartlandrust-example-org",
        "suggested",
        "suggestion",
    )
    assert sorted(inbox.deleted) == sorted(inbox.values)
    assert (report.suggestions_read, report.suggestions_deleted) == (4, 4)


def test_suggestions_that_need_a_person_go_to_the_review_queue(data: Path) -> None:
    report, _ = suggest(data)
    queue = DataStore(data).read_review_queue()
    assert sorted((r.kind, r.ref) for r in queue) == [
        ("suggestion", "https://nowhere.example.org/"),
        ("suggestion", "https://www.facebook.com/omaha-tech"),
    ]
    assert report.suggestions_for_review == 2
    # A second run with the same suggestions adds no duplicate review items.
    suggest(data)
    assert len(DataStore(data).read_review_queue()) == 2


def test_a_note_never_reaches_a_file_or_the_review_pr(data: Path) -> None:
    suggest(data)
    for path in data.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "Pat" not in text and "Tuesday group" not in text, path
    store = DataStore(data)
    pr = build_review_pr(
        store.read_review_queue(), store.read_events(), store.read_sources(),
        categories={}, areas={}, now=NOW,
    )  # fmt: skip
    assert pr is not None
    assert "nowhere.example.org" in pr.body
    assert "Pat" not in pr.body and "Tuesday" not in pr.body


def test_the_report_says_what_came_of_the_suggestions(data: Path) -> None:
    report, _ = suggest(data)
    text = render_sources_markdown(report)
    assert "**Visitor suggestions:** 4 read, 2 sent to review, 4 cleared from KV." in text


def test_suggestions_are_evaluated_before_anything_else(data: Path) -> None:
    from netc.finders.base import make_candidate
    from netc.pipeline.evaluate import evaluate_candidates

    store = DataStore(data)
    areas = store.read_areas()
    assert areas is not None
    found = make_candidate(
        "https://yoga.example.org/", found_via="web_search", evidence=[], now=NOW
    )
    asked = make_candidate(
        "https://heartlandrust.example.org/", found_via="suggestion", evidence=[], now=NOW
    )
    result = evaluate_candidates(
        [found, asked], http=FixtureHttp(FIXTURES), connectors=default_connectors(lambda: NOW),
        sources=[], categories=store.read_categories(), areas=areas, now=NOW, max_evaluations=1,
    )  # fmt: skip
    assert [c.result for c in result.candidates] == ["pending", "added"]


def test_a_dry_run_keeps_the_suggestions(data: Path) -> None:
    report, inbox = suggest(data, dry_run=True)
    assert inbox.deleted == [] and DataStore(data).read_review_queue() == []
    assert report.suggestions_read == 4


def test_suggestions_that_cannot_be_listed_do_not_stop_the_run(data: Path) -> None:
    report = run(data, finders=[], suggestions=FakeSuggestions([], failing=True))
    assert report.written
    assert report.suggestions_error is not None and "403" in report.suggestions_error
    assert "could not be read" in render_sources_markdown(report)
