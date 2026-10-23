"""Event times: source times to UTC for storage, and Central Time for display (T034).

Events are stored in UTC with the source's time zone kept alongside (Constitution IV) and are
always displayed in Central Time, labeled "CT" (FR-027). When a source gives no usable zone,
America/Chicago is assumed and the event records ``tz_assumed: true``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CENTRAL_NAME: Final = "America/Chicago"
CENTRAL: Final = ZoneInfo(CENTRAL_NAME)

# Zone names that calendar exports (Outlook, Exchange) and some pages use instead of IANA names.
_ZONE_ALIASES: Final = {
    "central standard time": "America/Chicago",
    "central daylight time": "America/Chicago",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "ct": "America/Chicago",
    "eastern standard time": "America/New_York",
    "eastern daylight time": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "mountain standard time": "America/Denver",
    "mountain daylight time": "America/Denver",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "pacific standard time": "America/Los_Angeles",
    "pacific daylight time": "America/Los_Angeles",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "utc": "UTC",
    "gmt": "UTC",
    "z": "UTC",
}


@dataclass(frozen=True)
class EventTimes:
    start: datetime
    """UTC, whole seconds."""
    end: datetime | None
    """UTC, whole seconds; for all-day events the exclusive end (midnight after the last day)."""
    source_tz: str
    tz_assumed: bool
    all_day: bool


def resolve_zone(name: str | None) -> tuple[ZoneInfo, str, bool]:
    """Return (zone, IANA name, assumed). Unknown or missing names fall back to Central."""
    cleaned = (name or "").strip()
    if cleaned:
        candidate = _ZONE_ALIASES.get(cleaned.lower(), cleaned)
        try:
            return ZoneInfo(candidate), candidate, False
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return CENTRAL, CENTRAL_NAME, True


def to_event_times(
    start: datetime | date,
    end: datetime | date | None,
    *,
    tz: str | None,
    all_day: bool,
) -> EventTimes:
    """Convert a source's start/end to UTC.

    Naive times are read in ``tz`` (or Central when missing). Aware times keep their instant;
    their zone name is recorded when the source states one. A plain ``date`` means an all-day
    event. An end earlier than the start on the same local date is taken to be on the next day
    ("10 PM to 1 AM"); any other end before the start is dropped.
    """
    zone, zone_name, assumed = _source_zone(start, tz)
    if all_day or not isinstance(start, datetime):
        return _all_day(start, end, zone, zone_name, assumed)

    start_utc = _to_utc(start, zone)
    end_utc = None
    if end is not None:
        end_dt = end if isinstance(end, datetime) else datetime.combine(end, time())
        end_utc = _to_utc(end_dt, zone)
        if end_utc < start_utc:
            local_start, local_end = start_utc.astimezone(zone), end_utc.astimezone(zone)
            if local_end.date() == local_start.date():
                end_utc = _to_utc(local_end.replace(tzinfo=None) + timedelta(days=1), zone)
            else:
                end_utc = None
    return EventTimes(start_utc, end_utc, zone_name, assumed, all_day=False)


def to_central(instant: datetime) -> datetime:
    return instant.astimezone(CENTRAL)


def is_upcoming(start: datetime, end: datetime | None, now: datetime) -> bool:
    """An event is upcoming until it ends (or starts, when it has no end) (FR-035)."""
    return now < (end or start)


def format_central(start: datetime, end: datetime | None, *, all_day: bool) -> str:
    """Human-readable Central Time, e.g. "Tue, Oct 20, 2026, 6:30 PM to 8:30 PM CT" (with an
    en dash between the times)."""
    first = to_central(start)
    dash = " \N{EN DASH} "
    if all_day:
        last = to_central(end) - timedelta(days=1) if end is not None else first
        if last.date() <= first.date():
            return f"{_day(first)}, {first.year} (all day)"
        if last.year == first.year:
            return f"{_day(first)}{dash}{_day(last)}, {last.year} (all day)"
        return f"{_day(first)}, {first.year}{dash}{_day(last)}, {last.year} (all day)"

    text = f"{_day(first)}, {first.year}, {_clock(first)}"
    if end is not None and end > start:
        last = to_central(end)
        if last.date() == first.date():
            text += f"{dash}{_clock(last)}"
        elif last.year == first.year:
            text += f"{dash}{_day(last)}, {_clock(last)}"
        else:
            text += f"{dash}{_day(last)}, {last.year}, {_clock(last)}"
    return f"{text} CT"


def short_day(value: date | datetime) -> str:
    """ "Tue, Oct 20": a day label for calendar pages."""
    return _day(value)


def clock_time(value: datetime) -> str:
    """ "6:30 PM", for a time already in Central Time."""
    return _clock(value)


# ---------------------------------------------------------------- helpers


def _source_zone(start: datetime | date, tz: str | None) -> tuple[ZoneInfo, str, bool]:
    if tz and tz.strip():
        return resolve_zone(tz)
    if isinstance(start, datetime) and isinstance(start.tzinfo, ZoneInfo):
        return start.tzinfo, start.tzinfo.key, False
    return resolve_zone(None)


def _to_utc(value: datetime, zone: tzinfo) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=zone)  # fold=0: ambiguous times take the first occurrence
    return value.astimezone(UTC).replace(microsecond=0)


def _all_day(
    start: datetime | date,
    end: datetime | date | None,
    zone: ZoneInfo,
    zone_name: str,
    assumed: bool,
) -> EventTimes:
    first = _as_date(start)
    start_utc = _to_utc(datetime.combine(first, time()), zone)
    end_utc = None
    if end is not None:
        last_exclusive = _as_date(end)
        if last_exclusive > first:
            end_utc = _to_utc(datetime.combine(last_exclusive, time()), zone)
    return EventTimes(start_utc, end_utc, zone_name, assumed, all_day=True)


def _as_date(value: datetime | date) -> date:
    return value.date() if isinstance(value, datetime) else value


_DAYS: Final = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _day(value: date) -> str:
    """ "Tue, Oct 20" (no zero padding, independent of the OS locale)."""
    return f"{_DAYS[value.weekday()]}, {_MONTHS[value.month - 1]} {value.day}"


def _clock(value: datetime) -> str:
    """ "6:30 PM" (12-hour, no zero padding)."""
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d} {'AM' if value.hour < 12 else 'PM'}"
