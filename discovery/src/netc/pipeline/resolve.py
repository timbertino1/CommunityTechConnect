"""Resolving mentions to the organizer's event page (T091; research R6; FR-014).

A mention (from a newsletter, a news post or a search snippet) is only a title and hints. It is
resolved when one of its links, or one result of a targeted search when it has none, is a page
whose event data has an event with a matching title (and the same day, when the hint gives
one). The page's site then becomes a candidate source, so its other events can be found the
normal way. Nothing is published here: the event reaches the site only through that source.

A mention is discarded once its date has passed or after MAX_ATTEMPTS weekly tries.

Each try can fetch pages from slow or unreachable sites, so a run tries at most MAX_RESOLVE
mentions, MAX_PAGES_PER_MENTION pages each, and starts none once ``should_stop`` says the
stage's time is up (the Oct 23 run spent 52 of its 58 minutes here). The rest wait, without
using up a try, and each mention tried is logged with its time.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final, Literal
from urllib.parse import urlsplit

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from netc.connectors.base import RawPayload
from netc.connectors.jsonld import page_listings
from netc.fetch import FetchError, HttpClient
from netc.finders.base import PLATFORMS, candidate_url, make_candidate
from netc.models import CandidateSource, Event, EventMention
from netc.pipeline.runner import LogSink
from netc.pipeline.sanitize import safe_url
from netc.pipeline.timeutil import to_central
from netc.search.base import BudgetedSearch, SearchBudgetExhaustedError, SearchError

MAX_ATTEMPTS: Final = 4
MATCH_SCORE: Final = 80
MAX_PAGES_PER_MENTION: Final = 3
MAX_RESOLVE: Final = 10
_MONTHS: Final = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)
_DATE: Final = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?"
    r"(?:,?\s+(\d{4}))?\b",
    re.IGNORECASE,
)
Channel = Literal["newsletter", "news", "web_search"]


@dataclass
class ResolveResult:
    mentions: list[EventMention]
    candidates: list[CandidateSource] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    stopped_for_time: bool = False
    """``should_stop`` ended the stage early; the deferred mentions wait for the next run."""


def resolve_mentions(
    mentions: Sequence[EventMention],
    *,
    http: HttpClient,
    now: datetime,
    search: BudgetedSearch | None = None,
    events: Iterable[Event] = (),
    should_stop: Callable[[], bool] | None = None,
    log: LogSink | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ResolveResult:
    by_url = {e.original_url: e.id for e in events}
    result = ResolveResult(list(mentions))
    tried = 0
    for i, mention in enumerate(mentions):
        if mention.resolution != "unresolved":
            continue
        when = parse_date_hint(mention.date_hint, now)
        if (when is not None and when < to_central(now).date()) or mention.attempts >= MAX_ATTEMPTS:
            result.mentions[i] = mention.model_copy(update={"resolution": "discarded"})
            result.counts["discarded"] += 1
            continue
        if tried >= MAX_RESOLVE:
            result.counts["deferred"] += 1
            continue
        if result.stopped_for_time or (should_stop is not None and should_stop()):
            result.stopped_for_time = True
            result.counts["deferred"] += 1
            continue
        tried += 1
        started = clock()
        urls = list(mention.links)
        if not urls and search is not None:
            urls = _search(mention, search, result)
        pages: list[str] = []
        try:
            found = _find(mention, urls[:MAX_PAGES_PER_MENTION], when, http, now, pages)
        except Exception:  # one strange page must not stop the run; the mention tries again
            result.counts["errors"] += 1
            found = None
        if log is not None:
            log(
                json.dumps(
                    {
                        "event": "mention_tried",
                        "channel": mention.channel,
                        "result": "unresolved" if found is None else "resolved",
                        "pages": len(pages),
                        "seconds": round(clock() - started, 1),
                    }
                )
            )
        if found is None:
            result.mentions[i] = mention.model_copy(update={"attempts": mention.attempts + 1})
            result.counts["unresolved"] += 1
            continue
        page, event_url = found
        result.mentions[i] = mention.model_copy(
            update={
                "resolution": "resolved",
                "event_id": by_url.get(event_url),
                "attempts": mention.attempts + 1,
            }
        )
        result.counts["resolved"] += 1
        target = _site(page)
        if target is not None:
            result.candidates.append(
                make_candidate(
                    target,
                    found_via=mention.channel,
                    now=now,
                    evidence=[f"resolved mention: {mention.title}", f"event page: {event_url}"],
                )
            )
    return result


def parse_date_hint(hint: str | None, now: datetime) -> date | None:
    """The date in a hint like "Thu, Nov 12" or "November 5, 2026", or None. Without a year,
    a date more than two months gone is read as next year's."""
    if not hint:
        return None
    match = _DATE.search(hint)
    if match is None:
        return None
    month = _MONTHS.index(match.group(1)[:3].lower()) + 1
    today = to_central(now).date()
    year = int(match.group(3)) if match.group(3) else today.year
    try:
        when = date(year, month, int(match.group(2)))
    except ValueError:
        return None
    if not match.group(3) and when < today - timedelta(days=60):
        when = when.replace(year=year + 1)
    return when


def _search(mention: EventMention, search: BudgetedSearch, result: ResolveResult) -> list[str]:
    query = f'"{mention.title}" {mention.place_hint or "Nebraska"}'
    try:
        hits = search.search(query, count=5)
    except SearchBudgetExhaustedError:
        result.counts["budget_exhausted"] += 1
        return []
    except SearchError:
        result.counts["search_errors"] += 1
        return []
    return [h.url for h in hits]


def _find(
    mention: EventMention,
    urls: Sequence[str],
    when: date | None,
    http: HttpClient,
    now: datetime,
    fetched: list[str],
) -> tuple[str, str] | None:
    """(page URL, event URL) for the first page with a matching event. Each page asked for is
    added to ``fetched``."""
    for url in urls:
        safe = safe_url(url)
        if safe is None:
            continue
        fetched.append(safe)
        try:
            response = http.get(safe, kind="page")
        except FetchError:
            continue
        if response.status >= 400:
            continue
        page = RawPayload.from_response(response, fetched_at=now)
        for listing in page_listings(page):
            score = fuzz.token_set_ratio(mention.title, listing.title, processor=default_process)
            if score < MATCH_SCORE:
                continue
            if when is not None and _day(listing.start) != when:
                continue
            return response.url, safe_url(listing.url) or response.url
    return None


def _site(page: str) -> str | None:
    """The candidate for a resolved page: the group page on a platform, else the site's home."""
    target = candidate_url(page)
    if target is None:
        return None
    parts = urlsplit(target)
    if (parts.hostname or "").removeprefix("www.") in PLATFORMS:
        return target
    return f"https://{parts.netloc}/"


def _day(value: datetime) -> date:
    return to_central(value).date() if value.tzinfo is not None else value.date()
