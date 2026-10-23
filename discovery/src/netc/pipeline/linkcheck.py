"""The monthly check of past events' original pages (T118; US5 scenario 3, FR-040).

On the first day of each month, discover-events re-reads up to MAX_CHECKS past events'
original pages and sets ``original_unavailable`` when one answers 404 or 410, so the site can
say the page may be gone; a page that answers again is unflagged. Anything unclear (a timeout,
403, 5xx, robots.txt saying no) leaves the flag as it was.

Pages are fetched with GET through SafeHttp, the only HTTP path for untrusted URLs; it caps
the body and keeps to robots.txt, the rate limit and the per-host budget. Each month checks a
different slice of the past events, so every link comes round. A host whose budget the source
reads already spent is skipped until next month.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from urllib.parse import urlsplit

from netc.fetch import (
    BudgetExceededError,
    ContentTypeNotAllowedError,
    FetchError,
    HttpClient,
    ResponseTooLargeError,
)
from netc.models import Event
from netc.pipeline.runner import LogSink, stderr_sink

MAX_CHECKS: Final = 50
GONE: Final = frozenset({404, 410})


@dataclass(frozen=True)
class LinkCheckReport:
    checked: int
    """Pages that gave a clear answer (there, or gone)."""
    unavailable: int
    """Of those, the ones that are gone."""


def due(now: datetime) -> bool:
    """The check runs on the first day of each month (UTC), in both of that day's runs."""
    return now.day == 1


def check_links(
    events: list[Event], http: HttpClient, *, now: datetime, log: LogSink = stderr_sink
) -> tuple[list[Event], LinkCheckReport]:
    """The events with ``original_unavailable`` updated for the pages checked, in their order."""
    past = sorted(
        (e for e in events if e.is_public and (e.end or e.start) <= now), key=lambda e: e.id
    )
    answers: dict[str, bool] = {}
    out_of_budget: set[str] = set()
    for event in _this_months_slice(past, now):
        host = urlsplit(event.original_url).hostname or ""
        if host in out_of_budget:
            continue
        try:
            response = http.get(event.original_url, kind="page")
        except BudgetExceededError:
            out_of_budget.add(host)
            continue
        except (ContentTypeNotAllowedError, ResponseTooLargeError):
            answers[event.id] = False  # it answered with something other than a web page
            continue
        except FetchError:
            continue
        if response.status in GONE:
            answers[event.id] = True
        elif 200 <= response.status < 300:
            answers[event.id] = False

    updated = [
        e.model_copy(update={"original_unavailable": answers[e.id]})
        if e.id in answers and answers[e.id] != e.original_unavailable
        else e
        for e in events
    ]
    report = LinkCheckReport(len(answers), sum(answers.values()))
    log(json.dumps({"event": "link_check_done", "checked": report.checked,
                    "unavailable": report.unavailable,
                    "hosts_out_of_budget": sorted(out_of_budget)}))  # fmt: skip
    return updated, report


def _this_months_slice(past: list[Event], now: datetime) -> list[Event]:
    """Up to MAX_CHECKS events, starting where last month's slice ended, wrapping around."""
    if len(past) <= MAX_CHECKS:
        return past
    start = ((now.year * 12 + now.month - 1) * MAX_CHECKS) % len(past)
    return (past + past)[start : start + MAX_CHECKS]
