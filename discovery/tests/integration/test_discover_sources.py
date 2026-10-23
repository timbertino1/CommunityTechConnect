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
