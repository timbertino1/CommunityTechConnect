"""Feed detection (T084; research R5; contracts/connectors-and-finders.md "Feed detector").

When discovery finds a new site, the evaluator fetches its page once and asks which connector
can read it, in priority order: an iCal feed (an ``.ics`` or ``webcal://`` link, or a
``text/calendar`` alternate link), then event data on the page itself (JSON-LD or microdata
``Event``), then an RSS/Atom feed. A URL that is itself a calendar or a feed is read as one.
A site with none of these becomes a candidate that needs review, never custom code.

Only https links are accepted (``webcal://`` is the same feed over https). Detection says how
to read a site, not whether it is relevant: the evaluator judges its sample events next.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from urllib.parse import urlsplit

import feedparser
from selectolax.lexbor import LexborHTMLParser

from netc.connectors.base import RawPayload
from netc.connectors.jsonld import page_listings
from netc.fetch import DEFAULT_CONTENT_TYPES, FetchError, HttpClient
from netc.fetch.urls import join_url
from netc.pipeline.sanitize import safe_url, to_plain_text

type DetectedKind = Literal["ical", "jsonld", "rss", "none"]

DETECT_CONTENT_TYPES: Final = DEFAULT_CONTENT_TYPES["page"] | DEFAULT_CONTENT_TYPES["feed"]
_CALENDAR_TYPES: Final = frozenset({"text/calendar", "text/x-vcalendar", "application/ics"})
_FEED_TYPES: Final = frozenset(
    {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}
)


@dataclass(frozen=True)
class Detection:
    kind: DetectedKind
    feed_url: str | None
    """The feed to read; None when the page itself is read (jsonld) or nothing was found."""
    reason: str
    title: str | None = None
    """The page's name (its <title>), plain text, for naming a new source."""


def detect(url: str, http: HttpClient, *, delay_seconds: float | None = None) -> Detection:
    """Fetch ``url`` once and detect how to read it. Errors come back as kind "none"."""
    try:
        response = http.get(
            url, kind="page", allowed_types=DETECT_CONTENT_TYPES, delay_seconds=delay_seconds
        )
    except FetchError as exc:
        return Detection("none", None, f"page could not be read: {type(exc).__name__}")
    if response.status >= 400:
        return Detection("none", None, f"page returned HTTP {response.status}")
    return detect_in(RawPayload.from_response(response, fetched_at=_epoch()))


def detect_in(page: RawPayload) -> Detection:
    """Detect from an already fetched page. Pure; never raises for bad data."""
    content_type = page.content_type.lower()
    text = page.text.lstrip()
    if content_type in _CALENDAR_TYPES or text.startswith("BEGIN:VCALENDAR"):
        return Detection("ical", page.url, "the URL is an iCal feed")
    if content_type in _FEED_TYPES or text.startswith("<?xml"):
        if feedparser.parse(page.text).get("version"):
            return Detection("rss", page.url, "the URL is an RSS or Atom feed")
        return Detection("none", None, "XML that is not an RSS or Atom feed")

    try:
        tree = LexborHTMLParser(page.text)
    except Exception:
        return Detection("none", None, "the page could not be parsed")

    title_node = tree.css_first("title")
    title = to_plain_text(title_node.text() if title_node else "", 200) or None
    calendar = _calendar_link(tree, page.url)
    if calendar is not None:
        return Detection("ical", calendar, "the page links an iCal feed", title)
    if page_listings(page):
        return Detection("jsonld", None, "the page has schema.org Event data", title)
    feed = _alternate(tree, page.url, ("application/rss+xml", "application/atom+xml"))
    if feed is not None:
        return Detection("rss", feed, "the page links an RSS or Atom feed", title)
    return Detection("none", None, "no calendar feed, event data or RSS/Atom feed found", title)


# ---------------------------------------------------------------- helpers


def _calendar_link(tree: LexborHTMLParser, base: str) -> str | None:
    found = _alternate(tree, base, ("text/calendar",))
    if found is not None:
        return found
    for node in tree.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if href.lower().startswith("webcal://"):
            href = "https://" + href[len("webcal://") :]
        url = safe_url(join_url(base, href))
        if url is not None and _looks_like_ics(url):
            return url
    return None


def _alternate(tree: LexborHTMLParser, base: str, types: tuple[str, ...]) -> str | None:
    for node in tree.css("link[href]"):
        rel = (node.attributes.get("rel") or "").lower().split()
        kind = (node.attributes.get("type") or "").strip().lower()
        if "alternate" in rel and kind in types:
            url = safe_url(join_url(base, node.attributes.get("href") or ""))
            if url is not None:
                return url
    return None


def _looks_like_ics(url: str) -> bool:
    parts = urlsplit(url)
    query = parts.query.lower()
    return parts.path.lower().endswith(".ics") or any(
        f"{key}=ics" in query or f"{key}=ical" in query for key in ("format", "type")
    )


def _epoch() -> datetime:
    """Detection doesn't use the date window, so any fixed time will do."""
    return datetime(1970, 1, 1, tzinfo=UTC)
