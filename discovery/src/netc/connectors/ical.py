"""iCal (.ics) connector (T056; research R5).

Reads a calendar feed and turns each event (with recurrences expanded up to 180 days ahead)
into a RawListing. Times keep their source zone. Text is passed through untouched apart from
length caps; cleaning happens in normalize. Private events, organizer e-mail addresses, and
anything unreadable are skipped, with a warning.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, ClassVar, Final
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

from netc.connectors.base import WINDOW_AHEAD, WINDOW_BEHIND, ParseResult, RawPayload
from netc.fetch import FetchError, HttpClient
from netc.models import RawListing, Source

MAX_TITLE_CHARS: Final = 2_000
MAX_DESCRIPTION_CHARS: Final = 20_000
MAX_SHORT_CHARS: Final = 2_000
MAX_WARNINGS: Final = 50

ICAL_CONTENT_TYPES: Final = frozenset(
    {
        "text/calendar",
        "text/x-vcalendar",
        "application/ics",
        "text/plain",
        "application/octet-stream",
    }
)
_ONLINE: Final = re.compile(
    r"(?i)\b(online|virtual|zoom|webinar|livestream|teams\.microsoft|meet\.google)\b"
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IcalConnector:
    kind: ClassVar[str] = "ical"

    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock

    def fetch(self, source: Source, http: HttpClient) -> RawPayload:
        url = source.feed_url or source.url
        response = http.get(
            url,
            kind="feed",
            allowed_types=ICAL_CONTENT_TYPES,
            delay_seconds=source.rate_limit_seconds,
        )
        if response.status >= 400:
            raise FetchError(f"{url} returned HTTP {response.status}")
        return RawPayload.from_response(response, fetched_at=self._clock())

    def parse(self, source: Source, payload: RawPayload) -> ParseResult:
        warnings: list[str] = []
        try:
            calendar = icalendar.Calendar.from_ical(payload.text)
        except Exception as exc:
            return ParseResult([], [f"not a readable iCal feed: {type(exc).__name__}"])
        if not isinstance(calendar, icalendar.Calendar) or calendar.name != "VCALENDAR":
            return ParseResult([], ["not a readable iCal feed: no VCALENDAR"])

        calendar_tz = _text(calendar.get("X-WR-TIMEZONE"), 100) or None
        repeating = _repeating_uids(calendar)
        components = _expand(calendar, payload.fetched_at, warnings)

        listings: list[RawListing] = []
        seen: set[tuple[str | None, str]] = set()
        for component in components:
            listing = _listing(component, calendar_tz, repeating, warnings)
            if listing is None:
                continue
            key = (listing.external_id, listing.start.isoformat())
            if key in seen:
                continue
            seen.add(key)
            listings.append(listing)
        if not listings and not warnings and not calendar.walk("VEVENT"):
            warnings.append("feed contains no events")
        return ParseResult(listings, warnings[:MAX_WARNINGS])


def _expand(
    calendar: icalendar.Calendar, fetched_at: datetime, warnings: list[str]
) -> Iterable[icalendar.cal.Component]:
    start, end = fetched_at - WINDOW_BEHIND, fetched_at + WINDOW_AHEAD
    try:
        return list(recurring_ical_events.of(calendar, skip_bad_series=True).between(start, end))
    except Exception as exc:
        warnings.append(
            f"recurrences could not be expanded ({type(exc).__name__}); used events as written"
        )
        return list(calendar.walk("VEVENT"))


def _repeating_uids(calendar: icalendar.Calendar) -> set[str]:
    """UIDs of events that occur more than once (a rule, extra dates, or overrides)."""
    uids: set[str] = set()
    for event in calendar.walk("VEVENT"):
        if any(event.get(key) is not None for key in ("RRULE", "RDATE", "RECURRENCE-ID")):
            uids.add(_text(event.get("UID"), 500))
    return uids


def _listing(
    event: icalendar.cal.Component,
    calendar_tz: str | None,
    repeating: set[str],
    warnings: list[str],
) -> RawListing | None:
    uid = _text(event.get("UID"), 500) or None
    label = uid or "an event"
    title = _text(event.get("SUMMARY"), MAX_TITLE_CHARS)
    if not title:
        warnings.append(f"skipped {label}: no title")
        return None
    if str(event.get("CLASS", "")).upper() in {"PRIVATE", "CONFIDENTIAL"}:
        warnings.append(f"skipped {label}: marked private")
        return None

    start = _when(event.get("DTSTART"))
    if start is None:
        warnings.append(f"skipped {label}: missing or invalid start date")
        return None
    end = _when(event.get("DTEND"))
    duration = event.get("DURATION")
    if end is None and duration is not None:
        try:
            delta = duration.dt
        except Exception:
            delta = None
        if isinstance(delta, timedelta):
            end = start + delta
    all_day = not isinstance(start, datetime)

    start_dt = _as_datetime(start)
    end_dt = _as_datetime(end) if end is not None else None

    # Occurrences of a repeating event share its UID; tell them apart by their start.
    external_id = uid
    if uid and uid in repeating:
        external_id = f"{uid}#{start_dt.isoformat()}"

    description = _text(event.get("DESCRIPTION"), None)
    if description is not None and len(description) > MAX_DESCRIPTION_CHARS:
        warnings.append(f"{label}: description truncated to {MAX_DESCRIPTION_CHARS} characters")
        description = description[:MAX_DESCRIPTION_CHARS]
    location = _text(event.get("LOCATION"), MAX_SHORT_CHARS) or None
    status = str(event.get("STATUS", "")).upper()

    return RawListing(
        external_id=external_id,
        url=_text(event.get("URL"), MAX_SHORT_CHARS) or None,
        title=title,
        start=start_dt,
        end=end_dt,
        tz=_zone_name(start)
        or (None if isinstance(start, datetime) and start.tzinfo else calendar_tz),
        all_day=all_day,
        location_text=location,
        online=bool(location and _ONLINE.search(location)),
        organizer_text=_organizer(event.get("ORGANIZER")),
        description_text=description or None,
        cancelled=status == "CANCELLED",
    )


def _when(prop: Any) -> datetime | date | None:
    try:
        value = getattr(prop, "dt", None)
    except Exception:
        return None
    return value if isinstance(value, (datetime, date)) else None


def _as_datetime(value: datetime | date) -> datetime:
    return value if isinstance(value, datetime) else datetime.combine(value, time())


def _zone_name(value: datetime | date) -> str | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    if isinstance(value.tzinfo, ZoneInfo):
        return value.tzinfo.key
    if value.utcoffset() == timedelta(0):
        return "UTC"
    return None


def _organizer(prop: Any) -> str | None:
    """Only the organizer's display name (CN); never the mailto: address."""
    if prop is None:
        return None
    params = getattr(prop, "params", {})
    name = params.get("CN") if hasattr(params, "get") else None
    return _text(name, MAX_SHORT_CHARS) or None


def _text(value: Any, limit: int | None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text if limit is None else text[:limit]
