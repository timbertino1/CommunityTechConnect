"""The per-source runner: isolation and observability (T037; FR-002, FR-008)."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

import pytest

from netc.connectors.base import ParseResult, RawPayload
from netc.fetch import FetchTimeoutError, SafeHttp
from netc.models import RawListing, Source, SourceStatus
from netc.pipeline.runner import RunResult, run_sources
from netc.pipeline.sanitize import is_plain_text
from tests.data_samples import make_source

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 18, 11, 0, tzinfo=UTC)
HTTP = cast(SafeHttp, object())  # fake connectors never touch the network


def raw_listing(title: str = "Omaha Python Meetup") -> RawListing:
    return RawListing(
        external_id="1",
        url="https://example.com/e/1",
        title=title,
        start=datetime(2026, 10, 20, 18, 30),
        end=None,
        tz="America/Chicago",
        all_day=False,
        location_text="Omaha, NE",
        online=False,
        organizer_text="Omaha Python",
        description_text="Talks.",
        cancelled=False,
    )


def payload() -> RawPayload:
    return RawPayload(
        url="https://example.com/feed.ics",
        content=b"",
        content_type="text/calendar",
        fetched_at=NOW,
    )


class FakeConnector:
    kind: ClassVar[str] = "ical"

    def __init__(self, listings: int = 2, warnings: list[str] | None = None) -> None:
        self.listings = listings
        self.warnings = warnings or []
        self.calls: list[str] = []

    def fetch(self, source: Source, http: SafeHttp) -> RawPayload:
        self.calls.append(source.id)
        return payload()

    def parse(self, source: Source, payload: RawPayload) -> ParseResult:
        return ParseResult([raw_listing(f"Event {i}") for i in range(self.listings)], self.warnings)


class PerSource(FakeConnector):
    """Behaves differently per source id."""

    def __init__(self, behaviors: dict[str, Any]) -> None:
        super().__init__()
        self.behaviors = behaviors

    def fetch(self, source: Source, http: SafeHttp) -> RawPayload:
        self.calls.append(source.id)
        behavior = self.behaviors.get(source.id)
        if isinstance(behavior, BaseException):
            raise behavior
        if callable(behavior):
            behavior()
        return payload()

    def parse(self, source: Source, payload: RawPayload) -> ParseResult:
        key = f"{source.id}:parse"
        if key in self.behaviors:
            return cast(ParseResult, self.behaviors[key])
        return super().parse(source, payload)


class LogCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    @property
    def records(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.lines]

    def events(self, name: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r["event"] == name]


def sources(*ids: str, **overrides: Any) -> list[Source]:
    return [make_source(source_id, **overrides) for source_id in ids]


def run(
    srcs: list[Source],
    connector: Any,
    previous: dict[str, SourceStatus] | None = None,
    **kwargs: Any,
) -> tuple[RunResult, LogCapture]:
    log = LogCapture()
    result = run_sources(
        srcs, {"ical": connector}, HTTP, previous or {}, now=NOW, log=log, **kwargs
    )
    return result, log


# --- Isolation (FR-008)


def test_successful_sources_return_their_listings_and_fresh_status() -> None:
    result, _ = run(sources("src_a", "src_b"), FakeConnector(listings=3))
    assert [o.status for o in result.outcomes] == ["ok", "ok"]
    assert all(len(o.listings) == 3 for o in result.outcomes)
    status = result.statuses["src_a"]
    assert status.last_attempt == NOW
    assert status.last_success == NOW
    assert status.last_error is None
    assert status.consecutive_failures == 0
    assert status.events_found_last_run == 3


class PastEvents(FakeConnector):
    def __init__(self, past: object, latest: object) -> None:
        super().__init__(listings=0)
        self.past, self.latest = past, latest

    def parse(self, source: Source, payload: RawPayload) -> ParseResult:
        return ParseResult([], [], self.past, self.latest)  # type: ignore[arg-type]


def test_the_past_event_summary_is_passed_through() -> None:
    latest = datetime(2026, 10, 13, 22, 30, tzinfo=UTC)
    result, _ = run(sources("src_a"), PastEvents(4, latest))
    (outcome,) = result.outcomes
    assert (outcome.past, outcome.latest_past) == (4, latest)


@pytest.mark.parametrize(
    ("past", "latest"),
    [(-1, None), (True, None), ("3", None), (2, "2026-10-13"), (2, datetime(2026, 10, 13))],
)
def test_a_malformed_past_event_summary_is_ignored(past: object, latest: object) -> None:
    result, _ = run(sources("src_a"), PastEvents(past, latest))
    (outcome,) = result.outcomes
    assert outcome.status == "ok"
    assert outcome.latest_past is None
    assert outcome.past in (0, 2)


def test_a_raising_connector_is_recorded_and_the_others_still_run() -> None:
    connector = PerSource({"src_bad": RuntimeError("boom")})
    result, _ = run(sources("src_bad", "src_good"), connector)
    bad, good = result.outcomes
    assert bad.status == "failed"
    assert good.status == "ok"
    assert connector.calls == ["src_bad", "src_good"]
    status = result.statuses["src_bad"]
    assert status.last_attempt == NOW
    assert status.consecutive_failures == 1
    assert status.last_error is not None and "boom" in status.last_error


def test_fetch_errors_are_recorded_like_any_failure() -> None:
    connector = PerSource({"src_slow": FetchTimeoutError("https://slow.example.com/ timed out")})
    result, _ = run(sources("src_slow"), connector)
    assert result.outcomes[0].status == "failed"
    assert "FetchTimeoutError" in (result.statuses["src_slow"].last_error or "")


def test_consecutive_failures_accumulate_and_last_success_is_kept() -> None:
    previous = {
        "src_bad": SourceStatus(
            last_attempt=NOW - timedelta(days=1),
            last_success=NOW - timedelta(days=3),
            consecutive_failures=2,
        )
    }
    result, _ = run(sources("src_bad"), PerSource({"src_bad": ValueError("x")}), previous)
    status = result.statuses["src_bad"]
    assert status.consecutive_failures == 3
    assert status.last_success == NOW - timedelta(days=3)
    assert status.events_found_last_run is None


def test_success_resets_the_failure_count() -> None:
    previous = {"src_a": SourceStatus(last_attempt=NOW - timedelta(days=1), consecutive_failures=4)}
    result, _ = run(sources("src_a"), FakeConnector(), previous)
    assert result.statuses["src_a"].consecutive_failures == 0


def test_a_hanging_connector_times_out_and_the_run_moves_on() -> None:
    release = threading.Event()
    connector = PerSource({"src_hang": lambda: release.wait(10)})
    try:
        result, _ = run(sources("src_hang", "src_next"), connector, source_timeout_seconds=0.2)
    finally:
        release.set()
    hang, nxt = result.outcomes
    assert hang.status == "failed"
    assert "timed out" in (result.statuses["src_hang"].last_error or "")
    assert nxt.status == "ok"


@pytest.mark.parametrize(
    "garbage",
    [
        "not a parse result",
        None,
        ParseResult(cast(list[RawListing], [{"title": "dict, not a RawListing"}])),
        ParseResult(cast(list[RawListing], "abc")),
    ],
)
def test_garbage_from_a_connector_is_a_failure(garbage: Any) -> None:
    connector = PerSource({"src_junk:parse": garbage})
    result, _ = run(sources("src_junk", "src_ok"), connector)
    assert result.outcomes[0].status == "failed"
    assert "invalid" in (result.statuses["src_junk"].last_error or "")
    assert result.outcomes[1].status == "ok"


def test_unknown_connector_kind_is_a_failure() -> None:
    result, _ = run(sources("src_rss", connector="rss"), FakeConnector())
    assert result.outcomes[0].status == "failed"
    assert "rss" in (result.statuses["src_rss"].last_error or "")


def test_keyboard_interrupt_is_not_swallowed() -> None:
    with pytest.raises(KeyboardInterrupt):
        run(sources("src_a"), PerSource({"src_a": KeyboardInterrupt()}))


def test_too_many_listings_are_capped_with_a_warning() -> None:
    result, _ = run(sources("src_flood"), FakeConnector(listings=50), max_listings_per_source=10)
    outcome = result.outcomes[0]
    assert outcome.status == "ok"
    assert len(outcome.listings) == 10
    assert any("50" in w for w in outcome.warnings)


# --- Sanitized error messages


def test_last_error_is_sanitized() -> None:
    message = (
        "<script>alert(1)</script> failed at https://api.example.com/v3/events?token=SECRET123#x "
        "contact ops@example.com or 402-555-0199\x00" + "x" * 2000
    )
    result, _ = run(sources("src_bad"), PerSource({"src_bad": RuntimeError(message)}))
    error = result.statuses["src_bad"].last_error or ""
    assert is_plain_text(error)
    assert "<script" not in error
    assert "SECRET123" not in error
    assert "token=" not in error
    assert "https://api.example.com/v3/events" in error
    assert "ops@example.com" not in error
    assert "555-0199" not in error
    assert len(error) <= 500
    SourceStatus.model_validate(result.statuses["src_bad"].model_dump())


# --- Skipped sources


@pytest.mark.parametrize("status", ["paused", "blocked_by_terms"])
def test_paused_and_blocked_sources_are_skipped_untouched(status: str) -> None:
    connector = FakeConnector()
    previous = {
        "src_off": SourceStatus(last_attempt=NOW - timedelta(days=9), consecutive_failures=5)
    }
    result, log = run(sources("src_off", status=status), connector, previous)
    assert connector.calls == []
    assert result.outcomes[0].status == "skipped"
    assert result.outcomes[0].skipped_reason == status
    assert result.statuses["src_off"] == previous["src_off"]
    assert log.events("source_skipped")[0]["reason"] == status


def test_sources_checked_recently_are_not_due() -> None:
    connector = FakeConnector()
    previous = {
        "src_a": SourceStatus(
            last_attempt=NOW - timedelta(hours=12), last_success=NOW - timedelta(hours=12)
        )
    }
    result, _ = run(sources("src_a"), connector, previous)
    assert connector.calls == []
    assert result.outcomes[0].skipped_reason == "not_due"


def test_a_source_is_due_within_an_hour_of_its_interval() -> None:
    # Twice-daily runs drift by minutes; a 24-hour source attempted 23h30m ago is due.
    connector = FakeConnector()
    previous = {"src_a": SourceStatus(last_attempt=NOW - timedelta(hours=23, minutes=30))}
    run(sources("src_a"), connector, previous)
    assert connector.calls == ["src_a"]


def test_shorter_intervals_are_honored() -> None:
    connector = FakeConnector()
    previous = {"src_a": SourceStatus(last_attempt=NOW - timedelta(hours=6))}
    run(sources("src_a", check_interval_hours=6), connector, previous)
    assert connector.calls == ["src_a"]


def test_force_runs_sources_that_are_not_due() -> None:
    connector = FakeConnector()
    previous = {"src_a": SourceStatus(last_attempt=NOW - timedelta(hours=1))}
    run(sources("src_a"), connector, previous, force=True)
    assert connector.calls == ["src_a"]


def test_statuses_of_sources_not_in_this_run_are_kept() -> None:
    previous = {"src_gone": SourceStatus(consecutive_failures=1)}
    result, _ = run(sources("src_a"), FakeConnector(), previous)
    assert result.statuses["src_gone"] == previous["src_gone"]


# --- Structured logs and metrics


def test_every_log_line_is_one_json_object_with_event_and_time() -> None:
    _, log = run(sources("src_a", "src_b"), PerSource({"src_b": RuntimeError("boom")}))
    assert log.lines
    for line in log.lines:
        assert "\n" not in line
        record = json.loads(line)
        assert record["ts"] == "2026-10-18T11:00:00Z"
        assert record["event"]
        assert record["level"] in {"info", "warning", "error"}


def test_per_source_metrics_are_logged() -> None:
    connector = PerSource({"src_bad": RuntimeError("boom")})
    connector.warnings = ["skipped 1 event without a date"]
    _, log = run(sources("src_ok", "src_bad"), connector)
    done = log.events("source_done")[0]
    assert done["source_id"] == "src_ok"
    assert done["listings"] == 2
    assert done["warnings"] == 1
    assert isinstance(done["duration_ms"], int)
    failed = log.events("source_failed")[0]
    assert failed["source_id"] == "src_bad"
    assert failed["level"] == "error"
    assert failed["consecutive_failures"] == 1
    assert "boom" in failed["error"]


def test_run_summary_counts_outcomes() -> None:
    connector = PerSource({"src_bad": RuntimeError("boom")})
    result, log = run(
        [*sources("src_ok", "src_bad"), *sources("src_off", status="paused")], connector
    )
    (summary,) = log.events("run_done")
    assert summary["sources"] == 3
    assert summary["ok"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["listings"] == 2
    assert result.metrics == {
        k: summary[k] for k in ("sources", "ok", "failed", "skipped", "listings")
    }


def test_log_lines_never_contain_secrets_from_errors() -> None:
    connector = PerSource(
        {"src_bad": RuntimeError("GET https://x.example.com/?api_key=SECRET failed")}
    )
    _, log = run(sources("src_bad"), connector)
    assert all("SECRET" not in line for line in log.lines)
