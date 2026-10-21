"""discover-events with the AI second opinion (T082): undecided listings are asked, confident
answers decide, answers are cached with the run's data, and the report shows the spend."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from netc.connectors import default_connectors
from netc.fetch import FixtureHttp
from netc.pipeline.ai import Ai, AiCache
from netc.pipeline.discover_events import DiscoverReport, discover_events
from netc.pipeline.run_report import render_markdown
from netc.storage import DataStore
from tests.ai_support import ScriptedClient, verdict
from tests.data_samples import make_source

pytestmark = pytest.mark.integration

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "integration_ai"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    for name in ("categories.yaml", "areas.yaml"):
        shutil.copy(REPO_DATA / name, root / name)
    DataStore(root).write_source(
        make_source("src_lincoln-builders", name="Lincoln Builders", connector="jsonld",
                    url="https://lincolngroup.example.org/events", default_area="lincoln")
    )  # fmt: skip
    return root


def run(root: Path, client: ScriptedClient | None) -> DiscoverReport:
    service = None
    if client is not None:
        service = Ai(client, AiCache(root / "cache" / "ai", now=NOW), now=NOW)
    return discover_events(
        DataStore(root), FixtureHttp(FIXTURES), default_connectors(lambda: NOW), now=NOW,
        force=True, ai=service, log=lambda _event: None,
    )  # fmt: skip


def titles(root: Path, state: str) -> set[str]:
    return {e.title for e in DataStore(root).read_events() if e.review_state == state}


def test_without_ai_the_unclear_listing_waits_for_review(data: Path) -> None:
    report = run(data, None)
    assert report.listings["kept"] == 1 and report.listings["held"] == 1
    assert titles(data, "pending_review") == {"Monthly get-together"}
    assert report.ai_calls is None
    assert "AI second opinion" not in render_markdown(report)


def test_a_confident_answer_decides_and_is_marked_inferred(data: Path) -> None:
    client = ScriptedClient(verdict(area="lincoln", categories=["software-dev"]))
    report = run(data, client)
    assert len(client.calls) == 1 and "Monthly get-together" in client.calls[0]["data"]
    assert report.listings["held"] == 0 and report.listings["kept"] == 2
    event = next(e for e in DataStore(data).read_events() if e.title == "Monthly get-together")
    assert event.review_state == "published"  # a trusted source's event
    assert event.categories == ["software-dev"] and "categories" in event.inferred
    assert "**AI second opinion:** 1 call this run" in render_markdown(report)
    assert list((data / "cache" / "ai").glob("2026-10.jsonl"))


def test_an_ai_rejection_keeps_it_off_the_site(data: Path) -> None:
    run(data, ScriptedClient(verdict(relevant=False, reason="a social with no tech content")))
    assert "Monthly get-together" not in {e.title for e in DataStore(data).read_events()}


def test_the_next_run_uses_the_cache(data: Path) -> None:
    run(data, ScriptedClient(verdict()))
    again = ScriptedClient()
    report = run(data, again)
    assert again.calls == []
    assert report.ai_calls == 0


def test_the_data_with_an_ai_cache_validates(data: Path) -> None:
    from netc.cli import main

    run(data, ScriptedClient(verdict()))
    assert main(["validate-data", "--data-dir", str(data)]) == 0


def test_the_report_says_when_the_ai_gave_no_usable_answer(data: Path) -> None:
    from netc.pipeline.ai import AiReply

    report = run(data, ScriptedClient(AiReply(None, 0, 0, 0, error="BadRequestError (400)")))
    assert report.listings["held"] == 1
    text = render_markdown(report)
    assert "1 gave no usable answer (last: `BadRequestError (400)`); those wait for review." in text
