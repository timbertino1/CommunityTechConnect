"""Run every due source through its connector, one at a time, in isolation (T038).

A failing source never stops the run (FR-008): whatever goes wrong (an exception, a fetch
error, garbage output, or taking longer than the per-source time limit) is recorded in that
source's run health and the next source starts. Paused and blocked sources are skipped, and so
are sources checked within their interval; the interval is at most 24 hours (FR-002).

Every step is logged as one JSON object per line, with per-source metrics.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal

from netc.connectors.base import Connector, ParseResult
from netc.fetch import HttpClient
from netc.models import RawListing, Source, SourceStatus
from netc.pipeline.sanitize import scrub_pii, to_plain_text

DEFAULT_SOURCE_TIMEOUT_SECONDS: Final = 120.0
DEFAULT_MAX_LISTINGS_PER_SOURCE: Final = 2000
RUN_GAP: Final = timedelta(hours=12)
"""Time between scheduled runs (11:00 and 23:00 UTC). A source is read when waiting for the
next run would leave it unread for longer than its interval (FR-002)."""
DUE_SLACK: Final = timedelta(hours=1)
"""Scheduled runs start late by minutes to hours, so the gap between two runs can be shorter."""
MAX_ERROR_LENGTH: Final = 300
_MAX_RAW_ERROR: Final = 10_000

type LogSink = Callable[[str], None]
type Outcome = Literal["ok", "failed", "skipped"]


class SourceTimeoutError(Exception):
    """A source took longer than its time limit."""


class InvalidConnectorOutputError(Exception):
    """A connector returned something other than a ParseResult of RawListings."""


@dataclass
class SourceOutcome:
    source_id: str
    status: Outcome
    listings: list[RawListing] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    skipped_reason: str | None = None
    duration_ms: int = 0
    past: int = 0
    """Events the source still shows that already ended (see ParseResult.past)."""
    latest_past: datetime | None = None


@dataclass
class RunResult:
    outcomes: list[SourceOutcome]
    statuses: dict[str, SourceStatus]
    """Run health for every source: updated for attempted sources, unchanged for the rest."""

    @property
    def metrics(self) -> dict[str, int]:
        return {
            "sources": len(self.outcomes),
            "ok": sum(o.status == "ok" for o in self.outcomes),
            "failed": sum(o.status == "failed" for o in self.outcomes),
            "skipped": sum(o.status == "skipped" for o in self.outcomes),
            "listings": sum(len(o.listings) for o in self.outcomes),
        }


def stderr_sink(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def run_sources(
    sources: Sequence[Source],
    connectors: Mapping[str, Connector],
    http: HttpClient,
    previous: Mapping[str, SourceStatus],
    *,
    now: datetime,
    log: LogSink = stderr_sink,
    force: bool = False,
    source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS,
    max_listings_per_source: int = DEFAULT_MAX_LISTINGS_PER_SOURCE,
    clock: Callable[[], float] = time.monotonic,
) -> RunResult:
    """Run each source; never raises for a source's failure (Ctrl-C still stops the run)."""
    logger = _JsonLog(log, now)
    statuses = dict(previous)
    outcomes: list[SourceOutcome] = []
    run_started = clock()

    for source in sources:
        status = previous.get(source.id, SourceStatus())
        reason = _skip_reason(source, status, now, force)
        if reason is not None:
            outcomes.append(SourceOutcome(source.id, "skipped", skipped_reason=reason))
            logger.write("info", "source_skipped", source_id=source.id, reason=reason)
            continue

        logger.write("info", "source_start", source_id=source.id, connector=source.connector)
        started = clock()
        try:
            connector = connectors.get(source.connector)
            if connector is None:
                raise LookupError(f"no connector for kind {source.connector!r}")
            result = _with_timeout(
                lambda c=connector, s=source: _fetch_and_parse(c, s, http),  # type: ignore[misc]
                source_timeout_seconds,
            )
            listings, warnings = _check_output(result, max_listings_per_source)
            past, latest_past = _past_events(result)
        except Exception as exc:
            duration = _ms(clock() - started)
            error = safe_error_message(exc)
            statuses[source.id] = SourceStatus(
                last_attempt=now,
                last_success=status.last_success,
                last_error=error,
                consecutive_failures=status.consecutive_failures + 1,
                events_found_last_run=None,
            )
            outcomes.append(SourceOutcome(source.id, "failed", error=error, duration_ms=duration))
            logger.write(
                "error",
                "source_failed",
                source_id=source.id,
                error=error,
                consecutive_failures=status.consecutive_failures + 1,
                duration_ms=duration,
            )
            continue

        duration = _ms(clock() - started)
        statuses[source.id] = SourceStatus(
            last_attempt=now,
            last_success=now,
            last_error=None,
            consecutive_failures=0,
            events_found_last_run=len(listings),
        )
        outcomes.append(
            SourceOutcome(
                source.id,
                "ok",
                listings=listings,
                warnings=warnings,
                duration_ms=duration,
                past=past,
                latest_past=latest_past,
            )
        )
        logger.write(
            "warning" if warnings else "info",
            "source_done",
            source_id=source.id,
            listings=len(listings),
            warnings=len(warnings),
            duration_ms=duration,
        )

    result = RunResult(outcomes, statuses)
    logger.write("info", "run_done", duration_ms=_ms(clock() - run_started), **result.metrics)
    return result


# Query strings and fragments can carry tokens (e.g. ?api_key=...): drop them from messages.
_URL_TAIL: Final = re.compile(r"(https?://[^\s?#\"'<>]+)[?#][^\s\"'<>]*")


def safe_error_message(exc: BaseException) -> str:
    """A short, plain-text description of ``exc`` that is safe to publish in data/."""
    text = f"{type(exc).__name__}: {exc}"[:_MAX_RAW_ERROR]
    text = _URL_TAIL.sub(r"\1", text)
    # Scrub before and after cleaning: removing control characters can join a phone number
    # to the text after it, and cleaning can also reveal text hidden in markup.
    cleaned = to_plain_text(scrub_pii(text), MAX_ERROR_LENGTH)
    return scrub_pii(cleaned) or type(exc).__name__


# ---------------------------------------------------------------- helpers


def _skip_reason(source: Source, status: SourceStatus, now: datetime, force: bool) -> str | None:
    if source.status != "active":
        return source.status
    if force or status.last_attempt is None:
        return None
    interval = timedelta(hours=source.check_interval_hours)
    due_at = status.last_attempt + interval - RUN_GAP - DUE_SLACK
    return None if now >= due_at else "not_due"


def _fetch_and_parse(connector: Connector, source: Source, http: HttpClient) -> object:
    payload = connector.fetch(source, http)
    return connector.parse(source, payload)


def _past_events(result: object) -> tuple[int, datetime | None]:
    """The past-event summary, ignored unless well formed (connector output is untrusted)."""
    past = getattr(result, "past", 0)
    latest = getattr(result, "latest_past", None)
    if not isinstance(past, int) or isinstance(past, bool) or past < 0:
        return 0, None
    if not isinstance(latest, datetime) or latest.tzinfo is None:
        latest = None
    return past, latest


def _check_output(result: object, cap: int) -> tuple[list[RawListing], list[str]]:
    if not isinstance(result, ParseResult):
        raise InvalidConnectorOutputError(f"invalid connector output: {type(result).__name__}")
    listings = result.listings
    if not isinstance(listings, list) or not all(isinstance(x, RawListing) for x in listings):
        raise InvalidConnectorOutputError("invalid connector output: listings are not RawListings")
    warnings = [str(w) for w in result.warnings] if isinstance(result.warnings, list) else []
    if len(listings) > cap:
        warnings.append(f"kept the first {cap} of {len(listings)} listings")
        listings = listings[:cap]
    return list(listings), warnings


def _with_timeout(fn: Callable[[], object], seconds: float) -> object:
    """Run ``fn`` in a daemon thread and give up after ``seconds``.

    A thread cannot be killed; one that overruns keeps running in the background until it
    finishes on its own, but the run no longer waits for it and the process can still exit.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    worker = threading.Thread(target=target, name="netc-source", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise SourceTimeoutError(f"timed out after {seconds:g} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


class _JsonLog:
    def __init__(self, sink: LogSink, now: datetime) -> None:
        self._sink = sink
        self._ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    def write(self, level: str, event: str, **fields: Any) -> None:
        record = {"ts": self._ts, "level": level, "event": event, **fields}
        self._sink(json.dumps(record, sort_keys=True, ensure_ascii=False))
