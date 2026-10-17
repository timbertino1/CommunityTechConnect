"""Time handling: source times to UTC, and Central Time display (T033; FR-027, Constitution IV)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from netc.pipeline.timeutil import (
    CENTRAL,
    format_central,
    is_upcoming,
    resolve_zone,
    to_event_times,
)

pytestmark = pytest.mark.unit


def utc(*parts: int) -> datetime:
    year, month, day, hour, minute = (*parts, 0, 0)[:5]
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# --- Zones


@pytest.mark.parametrize(
    ("given", "name", "assumed"),
    [
        ("America/Chicago", "America/Chicago", False),
        ("America/New_York", "America/New_York", False),
        ("Europe/Berlin", "Europe/Berlin", False),
        ("UTC", "UTC", False),
        ("Central Standard Time", "America/Chicago", False),  # Outlook/Windows names
        ("Eastern Standard Time", "America/New_York", False),
        ("Mountain Standard Time", "America/Denver", False),
        ("Pacific Standard Time", "America/Los_Angeles", False),
        ("CST", "America/Chicago", False),
        ("CDT", "America/Chicago", False),
        ("US/Central", "US/Central", False),
        (None, "America/Chicago", True),
        ("", "America/Chicago", True),
        ("   ", "America/Chicago", True),
        ("Mars/Olympus_Mons", "America/Chicago", True),
        ("../../etc/hosts", "America/Chicago", True),  # path traversal in a zone name
    ],
)
def test_resolve_zone(given: str | None, name: str, assumed: bool) -> None:
    zone, resolved, was_assumed = resolve_zone(given)
    assert resolved == name
    assert was_assumed is assumed
    assert zone == ZoneInfo(name)


# --- Conversion to UTC


def test_naive_time_in_source_zone_converts_to_utc() -> None:
    times = to_event_times(
        datetime(2026, 10, 20, 18, 30), None, tz="America/Chicago", all_day=False
    )
    assert times.start == utc(2026, 10, 20, 23, 30)  # CDT is UTC-5
    assert times.source_tz == "America/Chicago"
    assert times.tz_assumed is False


def test_other_source_zones_convert_correctly() -> None:
    ny = to_event_times(datetime(2026, 10, 20, 19, 0), None, tz="America/New_York", all_day=False)
    assert ny.start == utc(2026, 10, 20, 23, 0)
    berlin = to_event_times(datetime(2026, 10, 20, 19, 0), None, tz="Europe/Berlin", all_day=False)
    assert berlin.start == utc(2026, 10, 20, 17, 0)


def test_missing_zone_assumes_central_and_says_so() -> None:
    times = to_event_times(datetime(2026, 1, 15, 18, 0), None, tz=None, all_day=False)
    assert times.start == utc(2026, 1, 16, 0, 0)  # CST is UTC-6
    assert times.source_tz == "America/Chicago"
    assert times.tz_assumed is True


def test_aware_time_keeps_its_named_zone() -> None:
    start = datetime(2026, 10, 20, 17, 30, tzinfo=ZoneInfo("America/Denver"))
    times = to_event_times(start, None, tz=None, all_day=False)
    assert times.start == utc(2026, 10, 20, 23, 30)
    assert times.source_tz == "America/Denver"
    assert times.tz_assumed is False


def test_aware_time_with_only_an_offset_is_exact_but_zone_is_assumed() -> None:
    start = datetime.fromisoformat("2026-10-20T18:30:00-05:00")
    times = to_event_times(start, None, tz=None, all_day=False)
    assert times.start == utc(2026, 10, 20, 23, 30)
    assert times.source_tz == "America/Chicago"
    assert times.tz_assumed is True


def test_explicit_zone_names_the_source_zone_for_aware_utc_times() -> None:
    start = datetime(2026, 10, 20, 23, 30, tzinfo=UTC)
    times = to_event_times(start, None, tz="America/Chicago", all_day=False)
    assert times.start == utc(2026, 10, 20, 23, 30)
    assert times.source_tz == "America/Chicago"
    assert times.tz_assumed is False


def test_seconds_are_kept_and_microseconds_dropped() -> None:
    times = to_event_times(datetime(2026, 10, 20, 18, 30, 15, 999), None, tz="UTC", all_day=False)
    assert times.start == datetime(2026, 10, 20, 18, 30, 15, tzinfo=UTC)


# --- Ends, midnight, bad ranges


def test_end_converts_too() -> None:
    times = to_event_times(
        datetime(2026, 10, 20, 18, 30),
        datetime(2026, 10, 20, 20, 30),
        tz="America/Chicago",
        all_day=False,
    )
    assert times.end == utc(2026, 10, 21, 1, 30)


def test_event_crossing_midnight() -> None:
    times = to_event_times(
        datetime(2026, 10, 20, 22, 0),
        datetime(2026, 10, 21, 1, 0),
        tz="America/Chicago",
        all_day=False,
    )
    assert times.start == utc(2026, 10, 21, 3, 0)
    assert times.end == utc(2026, 10, 21, 6, 0)
    assert format_central(times.start, times.end, all_day=False) == (
        "Tue, Oct 20, 2026, 10:00 PM \N{EN DASH} Wed, Oct 21, 1:00 AM CT"
    )


def test_end_time_earlier_on_the_same_date_means_the_next_day() -> None:
    # Some feeds give "10 PM to 1 AM" on the same date.
    times = to_event_times(
        datetime(2026, 10, 20, 22, 0),
        datetime(2026, 10, 20, 1, 0),
        tz="America/Chicago",
        all_day=False,
    )
    assert times.end == utc(2026, 10, 21, 6, 0)


def test_end_before_start_on_an_earlier_date_is_dropped() -> None:
    times = to_event_times(
        datetime(2026, 10, 20, 18, 0),
        datetime(2026, 10, 19, 20, 0),
        tz="America/Chicago",
        all_day=False,
    )
    assert times.end is None


def test_end_equal_to_start_is_kept() -> None:
    start = datetime(2026, 10, 20, 18, 0)
    times = to_event_times(start, start, tz="America/Chicago", all_day=False)
    assert times.end == times.start


# --- All-day events


def test_all_day_event_starts_at_local_midnight() -> None:
    times = to_event_times(date(2026, 10, 20), None, tz="America/Chicago", all_day=True)
    assert times.all_day is True
    assert times.start == utc(2026, 10, 20, 5, 0)
    assert times.end is None
    assert format_central(times.start, times.end, all_day=True) == "Tue, Oct 20, 2026 (all day)"


def test_all_day_end_is_exclusive_next_midnight() -> None:
    # iCal: DTSTART;VALUE=DATE:20261020, DTEND;VALUE=DATE:20261022 is a two-day event.
    times = to_event_times(date(2026, 10, 20), date(2026, 10, 22), tz=None, all_day=True)
    assert times.end == utc(2026, 10, 22, 5, 0)
    assert format_central(times.start, times.end, all_day=True) == (
        "Tue, Oct 20 \N{EN DASH} Wed, Oct 21, 2026 (all day)"
    )


def test_one_day_all_day_event_with_exclusive_end_shows_one_date() -> None:
    times = to_event_times(date(2026, 10, 20), date(2026, 10, 21), tz=None, all_day=True)
    assert format_central(times.start, times.end, all_day=True) == "Tue, Oct 20, 2026 (all day)"


def test_all_day_flag_with_datetime_input_uses_the_date() -> None:
    times = to_event_times(datetime(2026, 10, 20, 9, 0), None, tz="America/Chicago", all_day=True)
    assert times.start == utc(2026, 10, 20, 5, 0)


def test_date_input_without_all_day_flag_is_treated_as_all_day() -> None:
    times = to_event_times(date(2026, 10, 20), None, tz=None, all_day=False)
    assert times.all_day is True


def test_all_day_event_spanning_the_fall_dst_change() -> None:
    times = to_event_times(date(2026, 10, 31), date(2026, 11, 2), tz=None, all_day=True)
    assert times.start == utc(2026, 10, 31, 5, 0)  # midnight CDT
    assert times.end == utc(2026, 11, 2, 6, 0)  # midnight CST
    assert format_central(times.start, times.end, all_day=True) == (
        "Sat, Oct 31 \N{EN DASH} Sun, Nov 1, 2026 (all day)"
    )


def test_multi_year_all_day_event() -> None:
    times = to_event_times(date(2026, 12, 31), date(2027, 1, 2), tz=None, all_day=True)
    assert format_central(times.start, times.end, all_day=True) == (
        "Thu, Dec 31, 2026 \N{EN DASH} Fri, Jan 1, 2027 (all day)"
    )


# --- Central Time display across 2026 and 2027 DST transitions


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        # 2026: DST starts Sun Mar 8 at 2:00 AM, ends Sun Nov 1 at 2:00 AM.
        (utc(2026, 3, 8, 7, 59), "Sun, Mar 8, 2026, 1:59 AM CT"),  # last CST minute
        (utc(2026, 3, 8, 8, 0), "Sun, Mar 8, 2026, 3:00 AM CT"),  # first CDT minute
        (utc(2026, 11, 1, 6, 30), "Sun, Nov 1, 2026, 1:30 AM CT"),  # first 1:30 (CDT)
        (utc(2026, 11, 1, 7, 30), "Sun, Nov 1, 2026, 1:30 AM CT"),  # second 1:30 (CST)
        (utc(2026, 11, 1, 8, 0), "Sun, Nov 1, 2026, 2:00 AM CT"),
        # 2027: DST starts Sun Mar 14, ends Sun Nov 7.
        (utc(2027, 3, 14, 7, 59), "Sun, Mar 14, 2027, 1:59 AM CT"),
        (utc(2027, 3, 14, 8, 0), "Sun, Mar 14, 2027, 3:00 AM CT"),
        (utc(2027, 11, 7, 6, 30), "Sun, Nov 7, 2027, 1:30 AM CT"),
        (utc(2027, 11, 7, 7, 30), "Sun, Nov 7, 2027, 1:30 AM CT"),
        # Ordinary times either side of the changes.
        (utc(2026, 1, 16, 0, 0), "Thu, Jan 15, 2026, 6:00 PM CT"),
        (utc(2026, 7, 4, 17, 0), "Sat, Jul 4, 2026, 12:00 PM CT"),
        (utc(2027, 12, 1, 6, 0), "Wed, Dec 1, 2027, 12:00 AM CT"),
    ],
)
def test_central_display_across_dst_changes(instant: datetime, expected: str) -> None:
    assert format_central(instant, None, all_day=False) == expected


def test_same_day_range_shows_the_date_once() -> None:
    assert format_central(utc(2026, 10, 20, 23, 30), utc(2026, 10, 21, 1, 30), all_day=False) == (
        "Tue, Oct 20, 2026, 6:30 PM \N{EN DASH} 8:30 PM CT"
    )


def test_range_spanning_the_fall_change_uses_wall_clock_times() -> None:
    # 12:30 AM CDT to 2:30 AM CST is three real hours.
    assert format_central(utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 8, 30), all_day=False) == (
        "Sun, Nov 1, 2026, 12:30 AM \N{EN DASH} 2:30 AM CT"
    )


@pytest.mark.parametrize(
    ("wall", "expected_utc"),
    [
        (datetime(2026, 3, 7, 18, 0), utc(2026, 3, 8, 0, 0)),  # day before: CST
        (datetime(2026, 3, 9, 18, 0), utc(2026, 3, 9, 23, 0)),  # day after: CDT
        (datetime(2026, 11, 1, 1, 30), utc(2026, 11, 1, 6, 30)),  # ambiguous: first (CDT)
        (datetime(2026, 3, 8, 2, 30), utc(2026, 3, 8, 8, 30)),  # nonexistent: moved forward
        (datetime(2027, 3, 13, 18, 0), utc(2027, 3, 14, 0, 0)),
        (datetime(2027, 3, 15, 18, 0), utc(2027, 3, 15, 23, 0)),
        (datetime(2027, 11, 6, 18, 0), utc(2027, 11, 6, 23, 0)),
        (datetime(2027, 11, 8, 18, 0), utc(2027, 11, 9, 0, 0)),
    ],
)
def test_wall_clock_times_near_dst_changes_convert_correctly(
    wall: datetime, expected_utc: datetime
) -> None:
    assert to_event_times(wall, None, tz="America/Chicago", all_day=False).start == expected_utc


def test_central_constant_is_chicago() -> None:
    assert ZoneInfo("America/Chicago") == CENTRAL


# --- Upcoming (derived, FR-035)


def test_is_upcoming_uses_end_when_present() -> None:
    now = utc(2026, 10, 21, 0, 0)
    assert is_upcoming(utc(2026, 10, 20, 23, 30), utc(2026, 10, 21, 1, 30), now)
    assert not is_upcoming(utc(2026, 10, 20, 23, 30), None, now)
    assert not is_upcoming(utc(2026, 10, 20, 22, 0), utc(2026, 10, 20, 23, 0), now)
    assert is_upcoming(now + timedelta(minutes=1), None, now)
