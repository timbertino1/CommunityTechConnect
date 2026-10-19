"""The connector interface (contracts/connectors-and-finders.md).

A connector turns one source into raw listings in two steps: ``fetch`` (network, only through
SafeHttp) and ``parse`` (pure, no I/O). ``parse`` must not raise for bad data: it returns the
listings it could read plus warnings describing what it skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import ClassVar, Final, Protocol

from netc.fetch import FetchResponse, HttpClient
from netc.models import RawListing, Source

# Every connector reports events from one day before the fetch to 180 days after it.
WINDOW_BEHIND: Final = timedelta(days=1)
WINDOW_AHEAD: Final = timedelta(days=180)


@dataclass(frozen=True)
class RawPayload:
    """What a connector fetched for one source, before parsing."""

    url: str
    """Final URL after redirects."""
    content: bytes
    content_type: str
    fetched_at: datetime
    text: str = ""
    """Decoded body (charset from the response, UTF-8 otherwise)."""
    linked: tuple[RawPayload, ...] = ()
    """Further pages fetched by following links from this one (jsonld ``follow_links``)."""
    warnings: tuple[str, ...] = ()
    """Problems met while fetching (e.g. a linked page that could not be read)."""

    @classmethod
    def from_response(cls, response: FetchResponse, fetched_at: datetime) -> RawPayload:
        return cls(
            url=response.url,
            content=response.content,
            content_type=response.content_type,
            fetched_at=fetched_at,
            text=response.text,
        )


@dataclass(frozen=True)
class ParseResult:
    listings: list[RawListing]
    warnings: list[str] = field(default_factory=list)
    past: int = 0
    """Events the source still shows that ended before the window (not listed)."""
    latest_past: datetime | None = None
    """Start of the most recent of those (UTC), so a quiet source can be told from a broken one."""


class Connector(Protocol):
    kind: ClassVar[str]
    """"ical" | "rss" | "jsonld" | "eventbrite_org" | "html_rules"."""

    def fetch(self, source: Source, http: HttpClient) -> RawPayload: ...

    def parse(self, source: Source, payload: RawPayload) -> ParseResult: ...
