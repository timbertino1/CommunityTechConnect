"""Candidate evaluation: robots and terms, feed detection, sample events, and the decision
(T090; research R6; FR-015, FR-016)."""

from __future__ import annotations

import json
from collections.abc import Collection
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from netc.connectors import default_connectors
from netc.fetch import FetchKind, FetchResponse, FixtureHttp, RobotsDisallowedError
from netc.finders.base import make_candidate
from netc.models import AreaConfig, CandidateSource, Category
from netc.pipeline.evaluate import (
    MAX_EVALUATIONS,
    RECHECK_AFTER,
    EvaluateResult,
    evaluate_candidates,
)
from netc.storage import DataStore
from tests.ai_support import NOW, ScriptedClient, ai, verdict
from tests.data_samples import make_source

pytestmark = pytest.mark.unit

REPO = DataStore(Path(__file__).resolve().parents[3] / "data")
AREAS: AreaConfig = REPO.read_areas()  # type: ignore[assignment]
CATEGORIES: list[Category] = REPO.read_categories()
FINDERS = Path(__file__).resolve().parents[1] / "fixtures" / "finders"
LUMA_FEED = "https://api.lu.ma/ics/get?entity=calendar&id=cal-AbC123xyz"

PAGES = {
    "https://heartlandrust.example.org/": ("pages/jsonld_events.html", "text/html"),
    "https://kccloud.example.org/": ("candidates/out_of_state.html", "text/html"),
    "https://yoga.example.org/": ("candidates/non_tech.html", "text/html"),
    "https://acme-hosting.example.com/": ("pages/no_signals.html", "text/html"),
    "https://cowork.example.org/events": ("pages/coworking_calendar.html", "text/html"),
    "https://cowork.example.org/events.ics": ("feeds/cowork_events.ics", "text/calendar"),
    "https://www.meetup.com/omaha-data-engineers/events/": ("pages/meetup_group.html", "text/html"),
    LUMA_FEED: ("feeds/luma_calendar.ics", "text/calendar"),
}


def http(tmp_path: Path) -> FixtureHttp:
    index = {u: {"file": str(FINDERS / f), "content_type": t} for u, (f, t) in PAGES.items()}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return FixtureHttp(tmp_path)


def pending(url: str, found_via: Any = "web_search") -> CandidateSource:
    return make_candidate(url, found_via=found_via, evidence=["web search: test"], now=NOW)


def evaluate(tmp_path: Path, candidates: list[CandidateSource], **kw: Any) -> EvaluateResult:
    return evaluate_candidates(
        candidates,
        http=kw.pop("client", None) or http(tmp_path),
        connectors=default_connectors(lambda: NOW),
        sources=kw.pop("sources", []),
        categories=CATEGORIES,
        areas=AREAS,
        now=NOW,
        **kw,
    )


def one(tmp_path: Path, url: str, **kw: Any) -> tuple[CandidateSource, EvaluateResult]:
    result = evaluate(tmp_path, [pending(url)], **kw)
    [candidate] = result.candidates
    return candidate, result


# --- Added


def test_a_nebraska_tech_group_with_event_data_is_added_on_probation(tmp_path: Path) -> None:
    candidate, result = one(tmp_path, "https://heartlandrust.example.org/")
    assert candidate.result == "added" and candidate.last_evaluated == NOW
    [source] = result.added
    assert source.id == "src_heartlandrust-example-org"
    assert source.name == "Heartland Rust Users"
    assert (source.trust, source.origin, source.found_via) == (
        "probationary",
        "discovered",
        "web_search",
    )
    assert source.connector == "jsonld" and source.status == "active"
    assert source.default_area == "omaha" and source.added_at == NOW.date()
    assert any("1 of 1 upcoming events" in e for e in candidate.evidence)


def test_a_linked_calendar_feed_is_read_with_the_ical_reader(tmp_path: Path) -> None:
    candidate, result = one(tmp_path, "https://cowork.example.org/events")
    assert candidate.result == "added"
    [source] = result.added
    assert source.connector == "ical"
    assert source.feed_url == "https://cowork.example.org/events.ics"
    assert source.default_area == "lincoln"


def test_a_meetup_group_is_set_up_like_the_other_meetup_sources(tmp_path: Path) -> None:
    candidate, result = one(tmp_path, "https://www.meetup.com/omaha-data-engineers/")
    assert candidate.result == "added"
    [source] = result.added
    assert source.id == "src_omaha-data-engineers"
    assert source.url == "https://www.meetup.com/omaha-data-engineers/events/"
    assert source.connector == "jsonld" and source.rate_limit_seconds == 10
    assert source.follow_links is not None
    assert source.follow_links.path_glob == "/omaha-data-engineers/events/[0-9]*"
    assert source.name == "Omaha Data Engineers"


def test_a_luma_calendar_is_read_through_its_ical_feed(tmp_path: Path) -> None:
    candidate, result = one(tmp_path, LUMA_FEED)
    assert candidate.result == "added"
    [source] = result.added
    assert source.connector == "ical"
    assert source.url == LUMA_FEED and source.feed_url == LUMA_FEED
    assert source.id == "src_luma-cal-abc123xyz"
    assert source.name == "Omaha Builders Club"
    assert source.default_area == "omaha"


def test_new_source_ids_never_clash(tmp_path: Path) -> None:
    taken = make_source("src_heartlandrust-example-org", url="https://other.example.org/")
    _, result = one(tmp_path, "https://heartlandrust.example.org/", sources=[taken])
    assert result.added[0].id == "src_heartlandrust-example-org-2"


# --- Rejected, needs review, blocked


def test_out_of_state_events_are_rejected(tmp_path: Path) -> None:
    candidate, result = one(tmp_path, "https://kccloud.example.org/")
    assert (candidate.result, candidate.reason) == (
        "rejected",
        "its upcoming events are outside Nebraska",
    )
    assert result.added == []


def test_non_tech_events_are_rejected(tmp_path: Path) -> None:
    candidate, _ = one(tmp_path, "https://yoga.example.org/")
    assert candidate.result == "rejected"
    assert candidate.reason == "no tech events among 2 upcoming"


def test_a_site_with_nothing_to_read_needs_review(tmp_path: Path) -> None:
    candidate, _ = one(tmp_path, "https://acme-hosting.example.com/")
    assert candidate.result == "needs_review"
    assert "no calendar feed" in candidate.reason


def test_an_unreachable_site_needs_review(tmp_path: Path) -> None:
    candidate, _ = one(tmp_path, "https://gone.example.org/")
    assert candidate.result == "needs_review" and "could not be read" in candidate.reason


class RobotsNo:
    def get(
        self,
        url: str,
        *,
        kind: FetchKind = "page",
        allowed_types: Collection[str] | None = None,
        delay_seconds: float | None = None,
    ) -> FetchResponse:
        raise RobotsDisallowedError(f"robots.txt disallows {url}")


def test_robots_refusal_is_blocked_by_terms(tmp_path: Path) -> None:
    candidate, _ = one(tmp_path, "https://private.example.org/", client=RobotsNo())
    assert (candidate.result, candidate.reason) == (
        "blocked_by_terms",
        "robots.txt disallows reading it",
    )


class NeverFetch:
    def get(
        self,
        url: str,
        *,
        kind: FetchKind = "page",
        allowed_types: Collection[str] | None = None,
        delay_seconds: float | None = None,
    ) -> FetchResponse:
        raise AssertionError(f"fetched {url}")


@pytest.mark.parametrize("url", ["https://luma.com/nfx6erbc/", "https://lu.ma/omaha-builders"])
def test_luma_pages_are_never_fetched(tmp_path: Path, url: str) -> None:
    raw = pending("https://heartlandrust.example.org/").model_copy(update={"url": url})
    candidate = evaluate(tmp_path, [raw], client=NeverFetch()).candidates[0]
    assert candidate.result == "needs_review"
    assert "iCal" in candidate.reason and "gate V3" in candidate.reason


def test_social_networks_are_blocked_by_terms(tmp_path: Path) -> None:
    raw = pending("https://heartlandrust.example.org/").model_copy(
        update={"url": "https://www.facebook.com/groups/omahatech"}
    )
    candidate = evaluate(tmp_path, [raw]).candidates[0]
    assert candidate.result == "blocked_by_terms"


# --- Which candidates are evaluated


def test_rejected_candidates_wait_a_month(tmp_path: Path) -> None:
    recent = pending("https://yoga.example.org/").model_copy(
        update={"result": "rejected", "reason": "x", "last_evaluated": NOW - timedelta(days=10)}
    )
    old = recent.model_copy(
        update={
            "url": "https://kccloud.example.org/",
            "last_evaluated": NOW - RECHECK_AFTER - timedelta(days=1),
        }
    )
    result = evaluate(tmp_path, [recent, old])
    assert result.candidates[0] == recent  # untouched
    assert result.candidates[1].last_evaluated == NOW
    assert timedelta(days=30) == RECHECK_AFTER


def test_added_and_blocked_candidates_are_never_re_evaluated(tmp_path: Path) -> None:
    done = [
        pending(u).model_copy(update={"result": r, "reason": "x"})
        for u, r in [
            ("https://heartlandrust.example.org/", "added"),
            ("https://private.example.org/", "blocked_by_terms"),
        ]
    ]
    assert evaluate(tmp_path, done).candidates == done


def test_at_most_max_evaluations_a_run(tmp_path: Path) -> None:
    many = [pending(f"https://site{i}.example.org/") for i in range(40)]
    result = evaluate(tmp_path, many)
    assert (
        sum(c.last_evaluated == NOW and c.result != "pending" for c in result.candidates)
        == MAX_EVALUATIONS
    )
    assert result.counts["deferred"] == 40 - MAX_EVALUATIONS


# --- With the AI


def test_the_ai_judges_sample_events_the_rules_cannot(tmp_path: Path) -> None:
    client = ScriptedClient(
        verdict(relevant=False, nebraska=True, reason="yoga"),
        verdict(relevant=False, nebraska=True, reason="yoga"),
    )
    candidate, _ = one(tmp_path, "https://yoga.example.org/", ai=ai(tmp_path, client))
    assert candidate.result == "rejected"
    assert len(client.calls) == 2
