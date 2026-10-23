"""Eventbrite organizer connector (T104; gate V2).

Reads one organizer's public, live events through the Eventbrite API with the
EVENTBRITE_TOKEN secret. The source URL is the organizer's public page,
``https://www.eventbrite.com/o/<name>-<organizer id>``; the events come from
``/v3/organizers/{organizer id}/events/``. (The task named ``/organizations/{id}/events/``,
but an organization id is internal to an Eventbrite account and can't be found from a public
page; T103 confirms with a real token that the organizer endpoint lists another organizer's
public events.)

Unlike the other connectors this one never uses SafeHttp: it calls a fixed, keyed API, so it
goes through SafeApi (allow-listed host, no redirects, the token only in a header and never in
an error). Calls stop at MAX_CALLS_PER_RUN, far under the terms' 1,000 an hour (3.5). The other
two term rules live elsewhere: ended Eventbrite-only events are deleted (pipeline/lifecycle.py,
3.1) and every Eventbrite listing is linked from its event page without ``nofollow`` (3.2).
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Final, Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

from netc.connectors.base import WINDOW_AHEAD, WINDOW_BEHIND, ParseResult, RawPayload
from netc.fetch import FetchError, HttpClient
from netc.fetch.api import RawApiResponse, SafeApi
from netc.models import RawListing, Source

EVENTBRITE_API: Final = "https://www.eventbriteapi.com/v3"
MAX_CALLS_PER_RUN: Final = 200
MAX_PAGES_PER_SOURCE: Final = 4
PAGE_SIZE: Final = 50
MAX_TITLE_CHARS: Final = 2_000
MAX_DESCRIPTION_CHARS: Final = 20_000
MAX_SHORT_CHARS: Final = 2_000
MAX_WARNINGS: Final = 50

_ORGANIZER_PATH: Final = re.compile(r"/o/(?:[^/]*-)?(\d{5,20})/?")


class ApiGetter(Protocol):
    def get(
        self, url: str, *, headers: Mapping[str, str], max_bytes: int = ...
    ) -> RawApiResponse: ...


def organizer_id(url: str) -> str | None:
    """The organizer id in a public Eventbrite organizer page URL, or None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").removeprefix("www.")
    if parts.scheme != "https" or host != "eventbrite.com":
        return None
    match = _ORGANIZER_PATH.fullmatch(parts.path)
    return match.group(1) if match else None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EventbriteOrgConnector:
    kind: ClassVar[str] = "eventbrite_org"

    def __init__(
        self,
        clock: Callable[[], datetime] = _utc_now,
        *,
        api: ApiGetter | None = None,
        env: Mapping[str, str] = os.environ,
    ) -> None:
        self._clock = clock
        self._api = api
        self._env = env
        self.calls = 0

    def fetch(self, source: Source, http: HttpClient) -> RawPayload:
        token = self._env.get("EVENTBRITE_TOKEN", "").strip()
        if not token:
            raise FetchError("EVENTBRITE_TOKEN is not set")
        organizer = organizer_id(source.url)
        if organizer is None:
            raise FetchError(f"{source.url} is not an Eventbrite organizer page")
        if self._api is None:
            self._api = SafeApi()
        fetched_at = self._clock()
        first_url = ""
        events: list[Any] = []
        warnings: list[str] = []
        continuation: str | None = None
        for _ in range(MAX_PAGES_PER_SOURCE):
            if self.calls >= MAX_CALLS_PER_RUN:
                raise FetchError(f"the Eventbrite call limit for this run ({MAX_CALLS_PER_RUN})")
            query = {"status": "live", "order_by": "start_asc", "expand": "venue",
                     "page_size": str(PAGE_SIZE)}  # fmt: skip
            if continuation:
                query["continuation"] = continuation
            url = f"{EVENTBRITE_API}/organizers/{organizer}/events/?{urlencode(query)}"
            first_url = first_url or url
            self.calls += 1
            response = self._api.get(url, headers={"Authorization": f"Bearer {token}"})
            if response.status >= 400:
                raise FetchError(f"Eventbrite returned HTTP {response.status}")
            try:
                page = json.loads(response.content)
            except ValueError:
                warnings.append("Eventbrite returned something other than JSON")
                break
            if not isinstance(page, dict) or not isinstance(page.get("events"), list):
                warnings.append("Eventbrite returned no list of events")
                break
            events.extend(page["events"])
            pagination = page.get("pagination")
            continuation = None
            if isinstance(pagination, dict) and pagination.get("has_more_items") is True:
                value = pagination.get("continuation")
                continuation = value if isinstance(value, str) and value else None
            if continuation is None:
                break
        else:
            warnings.append(f"stopped after {MAX_PAGES_PER_SOURCE} pages of events")
        return dataclasses.replace(
            RawPayload(
                url=first_url,
                content=json.dumps({"events": events}).encode(),
                content_type="application/json",
                fetched_at=fetched_at,
            ),
            warnings=tuple(warnings),
        )

    def parse(self, source: Source, payload: RawPayload) -> ParseResult:
        warnings = list(payload.warnings)
        try:
            data = json.loads(payload.content)
        except ValueError:
            data = None
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, list):
            warnings.append("no list of events to read")
            return ParseResult([], warnings[:MAX_WARNINGS])

        earliest = payload.fetched_at - WINDOW_BEHIND
        latest = payload.fetched_at + WINDOW_AHEAD
        listings: list[RawListing] = []
        past = 0
        latest_past: datetime | None = None
        for i, item in enumerate(events):
            listing = _listing(item, f"event {i + 1}", warnings)
            if listing is None:
                continue
            if (listing.end or listing.start) < earliest:
                past += 1
                latest_past = max(latest_past or listing.start, listing.start)
                continue
            if listing.start > latest:
                continue
            listings.append(listing)
        if not events:
            warnings.append("the organizer has no live events")
        return ParseResult(listings, warnings[:MAX_WARNINGS], past=past, latest_past=latest_past)


def _listing(item: Any, label: str, warnings: list[str]) -> RawListing | None:
    if not isinstance(item, dict):
        warnings.append(f"{label}: not an event object")
        return None
    title = _text(_field(item, "name", "text"), MAX_TITLE_CHARS)
    start = _time(_field(item, "start", "utc"))
    if not title or start is None:
        warnings.append(f"{label}: no title or start time")
        return None
    venue = item.get("venue") if isinstance(item.get("venue"), dict) else None
    place = None
    if venue is not None:
        parts = [
            _text(venue.get("name"), MAX_SHORT_CHARS),
            _text(_field(venue, "address", "localized_address_display"), MAX_SHORT_CHARS),
        ]
        place = ", ".join(dict.fromkeys(p for p in parts if p)) or None
    description = _text(_field(item, "description", "text"), MAX_DESCRIPTION_CHARS) or _text(
        item.get("summary"), MAX_DESCRIPTION_CHARS
    )
    tz = _text(_field(item, "start", "timezone"), 100) or None
    return RawListing(
        external_id=_text(item.get("id"), 100) or None,
        url=_event_url(item.get("url")),
        title=title,
        start=start,
        end=_time(_field(item, "end", "utc")),
        tz=tz,
        all_day=False,
        location_text=place,
        online=item.get("online_event") is True,
        organizer_text=None,
        description_text=description or None,
        cancelled=item.get("status") == "canceled",
        country=_text(_field(venue, "address", "country"), 100) or None if venue else None,
    )


def _field(item: Mapping[str, Any], outer: str, inner: str) -> Any:
    value = item.get(outer)
    return value.get(inner) if isinstance(value, dict) else None


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _event_url(value: Any) -> str | None:
    """The event page without tracking parameters (``?aff=...``)."""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
