"""RSS/Atom connector (T084; research R5).

Most feed items are posts, not events. An item becomes a RawListing only when it carries event
data (the RSS event module: ``ev:startdate``, with optional end, location and organizer).
Every other item is kept as a FeedArticle with plain-text summary and its https links, for the
news finder to read for event mentions (T088); the connector itself returns only the events
and says how many articles it left for the finder.

feedparser reads RSS 0.9x/1.0/2.0 and Atom, never fetches anything, and does not resolve
external entities. Text stays untrusted: listings are cleaned in normalize, and article
summaries are reduced to plain text here.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any, ClassVar, Final
from urllib.parse import urljoin

import feedparser
from selectolax.lexbor import LexborHTMLParser

from netc.connectors.base import WINDOW_AHEAD, WINDOW_BEHIND, ParseResult, RawPayload
from netc.fetch import FetchError, HttpClient
from netc.models import RawListing, Source
from netc.pipeline.sanitize import safe_url, to_plain_text

MAX_TITLE_CHARS: Final = 2_000
MAX_DESCRIPTION_CHARS: Final = 20_000
MAX_SUMMARY_CHARS: Final = 4_000
MAX_LINKS: Final = 20
MAX_ITEMS: Final = 500
MAX_WARNINGS: Final = 50

RSS_CONTENT_TYPES: Final = frozenset(
    {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}
)


@dataclass(frozen=True)
class FeedArticle:
    """A feed item that isn't an event: a post the news finder may find events in."""

    title: str
    url: str
    published: datetime | None
    summary: str
    """Plain text."""
    links: list[str] = field(default_factory=list)
    """Safe https links found in the item's content."""


@dataclass(frozen=True)
class FeedRead:
    listings: list[RawListing]
    articles: list[FeedArticle]
    warnings: list[str]
    past: int = 0
    latest_past: datetime | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RssConnector:
    kind: ClassVar[str] = "rss"

    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock

    def fetch(self, source: Source, http: HttpClient) -> RawPayload:
        url = source.feed_url or source.url
        response = http.get(
            url,
            kind="feed",
            allowed_types=RSS_CONTENT_TYPES,
            delay_seconds=source.rate_limit_seconds,
        )
        if response.status >= 400:
            raise FetchError(f"{url} returned HTTP {response.status}")
        return RawPayload.from_response(response, fetched_at=self._clock())

    def parse(self, source: Source, payload: RawPayload) -> ParseResult:
        feed = read_feed(payload)
        warnings = list(feed.warnings)
        if feed.articles:
            n = len(feed.articles)
            warnings.append(
                f"{n} item{'s' if n != 1 else ''} without event data (left for the news finder)"
            )
        return ParseResult(feed.listings, warnings[:MAX_WARNINGS], feed.past, feed.latest_past)


def read_feed(payload: RawPayload) -> FeedRead:
    """Events and articles from an RSS or Atom document. Never raises for bad data."""
    if not payload.text.strip():
        return FeedRead([], [], ["empty feed"])
    try:
        parsed = feedparser.parse(payload.text, sanitize_html=False, resolve_relative_uris=False)
    except Exception as exc:  # feedparser is lenient, but a reader must never crash a run
        return FeedRead([], [], [f"not a readable feed: {type(exc).__name__}"])
    if not parsed.get("version"):
        return FeedRead([], [], ["not an RSS or Atom feed"])

    earliest = payload.fetched_at - WINDOW_BEHIND
    latest = payload.fetched_at + WINDOW_AHEAD
    listings: list[RawListing] = []
    articles: list[FeedArticle] = []
    warnings: list[str] = []
    past = 0
    latest_past: datetime | None = None
    entries = parsed.entries[:MAX_ITEMS]
    if len(parsed.entries) > MAX_ITEMS:
        warnings.append(f"feed has {len(parsed.entries)} items; read the first {MAX_ITEMS}")

    for entry in entries:
        title = _text(entry.get("title"), MAX_TITLE_CHARS)
        link = _link(entry, payload.url)
        start = _when(entry.get("ev_startdate"))
        if start is None:
            article_url = safe_url(link)
            if article_url is None or not title:
                warnings.append(f"skipped an item with no safe link or title: {title[:80]!r}")
                continue
            body = _content(entry)
            articles.append(
                FeedArticle(
                    title=to_plain_text(title, 300),
                    url=article_url,
                    published=_published(entry),
                    summary=to_plain_text(body, MAX_SUMMARY_CHARS),
                    links=_links(body, payload.url),
                )
            )
            continue

        begin, all_day = start
        end = _when(entry.get("ev_enddate"))
        finish = _aware(end[0] if end else begin)
        if finish < earliest:
            past += 1
            latest_past = _aware(begin) if latest_past is None else max(latest_past, _aware(begin))
            continue
        if _aware(begin) > latest:
            continue
        if not title or link is None:
            warnings.append(f"skipped an event item with no title or link: {title[:80]!r}")
            continue
        listings.append(
            RawListing(
                external_id=_text(entry.get("id"), 500) or None,
                url=link,
                title=title,
                start=begin,
                end=end[0] if end else None,
                tz=None,
                all_day=all_day,
                location_text=_text(entry.get("ev_location"), 2_000) or None,
                online=False,
                organizer_text=_text(entry.get("ev_organizer"), 2_000) or None,
                description_text=_content(entry)[:MAX_DESCRIPTION_CHARS] or None,
                cancelled=False,
            )
        )
    return FeedRead(listings, articles, warnings[:MAX_WARNINGS], past, latest_past)


# ---------------------------------------------------------------- helpers


def _text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if value else ""


def _link(entry: Any, base: str) -> str | None:
    """The item's http(s) link, made absolute; None for anything else (javascript:, mailto:)."""
    raw = _text(entry.get("link"), 2_048)
    if not raw:
        return None
    url = urljoin(base, raw)
    return url if url.startswith(("https://", "http://")) else None


def _content(entry: Any) -> str:
    for item in entry.get("content") or []:
        value = item.get("value") if isinstance(item, dict) else None
        if value:
            return str(value)
    return str(entry.get("summary") or "")


def _links(html: str, base: str) -> list[str]:
    if "<" not in html:
        return []
    found: list[str] = []
    for node in LexborHTMLParser(html).css("a[href]"):
        url = safe_url(urljoin(base, node.attributes.get("href") or ""))
        if url and url not in found:
            found.append(url)
        if len(found) >= MAX_LINKS:
            break
    return found


def _when(value: Any) -> tuple[datetime, bool] | None:
    """(start, all_day) from an ISO 8601 date or date-time (the RSS event module's format)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), time()), True
        return datetime.fromisoformat(text.replace("Z", "+00:00")), False
    except ValueError:
        return None


def _published(entry: Any) -> datetime | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if stamp is None:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(stamp), tz=UTC)
    except (OverflowError, ValueError, TypeError):
        return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
