"""Calendar periods and days, in Central Time (T106; US3, FR-033, R3).

Weeks run Monday to Sunday in both views: week pages are ISO weeks (contracts/site-urls.md), so
each row of a month grid is exactly one week page. An event covers every Central Time day from
its start day to its end day; an end at exactly midnight doesn't reach into the next day (that
is how all-day events are stored, with the end the day after).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from netc.site.calendar import (
    current_month,
    days_spanned,
    events_by_day,
    iso_week,
    month_weeks,
    months_around,
    next_month,
    next_week,
    prev_month,
    prev_week,
    week_days,
    weeks_around,
)
from tests.data_samples import make_event, utc

pytestmark = pytest.mark.unit


def event(start: datetime, end: datetime | None = None, **kw: Any) -> Any:
    slug = kw.pop("slug", f"e-{start:%Y%m%d%H%M}")
    return make_event(slug=slug, start=start, end=end, url=f"https://ex.example.org/{slug}", **kw)


# --- Grids


def test_a_month_grid_is_whole_weeks_from_monday_to_sunday() -> None:
    weeks = month_weeks(2026, 11)
    assert weeks[0][0] == date(2026, 10, 26)  # the Monday on or before Nov 1 (a Sunday)
    assert weeks[-1][-1] == date(2026, 12, 6)  # the Sunday on or after Nov 30 (a Monday)
    assert all(len(w) == 7 for w in weeks)
    assert all(w[0].weekday() == 0 for w in weeks)
    days = [d for w in weeks for d in w]
    assert days == sorted(days) and len(set(days)) == len(days)


def test_a_month_starting_on_monday_has_no_leading_days() -> None:
    weeks = month_weeks(2027, 2)  # Feb 1, 2027 is a Monday; 28 days
    assert weeks[0][0] == date(2027, 2, 1)
    assert weeks[-1][-1] == date(2027, 2, 28)
    assert len(weeks) == 4


def test_each_row_of_a_month_grid_is_one_iso_week() -> None:
    for week in month_weeks(2026, 11):
        year, number = iso_week(week[0])
        assert week_days(year, number) == week


def test_a_week_is_its_seven_iso_days() -> None:
    assert week_days(2026, 45) == [date(2026, 11, d) for d in range(2, 9)]


def test_iso_weeks_cross_the_new_year() -> None:
    assert iso_week(date(2026, 12, 31)) == (2026, 53)  # 2026 has 53 ISO weeks
    assert iso_week(date(2027, 1, 3)) == (2026, 53)
    assert iso_week(date(2027, 1, 4)) == (2027, 1)


# --- Previous and next


@pytest.mark.parametrize(
    ("year", "month", "before", "after"),
    [
        (2026, 11, (2026, 10), (2026, 12)),
        (2026, 12, (2026, 11), (2027, 1)),
        (2027, 1, (2026, 12), (2027, 2)),
    ],
)
def test_previous_and_next_month(
    year: int, month: int, before: tuple[int, int], after: tuple[int, int]
) -> None:
    assert prev_month(year, month) == before
    assert next_month(year, month) == after


@pytest.mark.parametrize(
    ("year", "week", "before", "after"),
    [
        (2026, 45, (2026, 44), (2026, 46)),
        (2026, 53, (2026, 52), (2027, 1)),  # a 53-week year
        (2027, 1, (2026, 53), (2027, 2)),
        (2027, 52, (2027, 51), (2028, 1)),  # 2027 has 52
    ],
)
def test_previous_and_next_week(
    year: int, week: int, before: tuple[int, int], after: tuple[int, int]
) -> None:
    assert prev_week(year, week) == before
    assert next_week(year, week) == after


def test_the_current_month_is_central_time() -> None:
    # 10 PM on Oct 31 in Omaha is already Nov 1 in UTC.
    assert current_month(utc(2026, 11, 1, 3)) == (2026, 10)
    assert current_month(utc(2026, 11, 1, 6)) == (2026, 11)


def test_pages_run_from_twelve_months_back_to_twelve_ahead() -> None:
    months = months_around(utc(2026, 10, 18, 12))
    assert months[0] == (2025, 10) and months[-1] == (2027, 10)
    assert len(months) == 25 and (2026, 10) in months


def test_week_pages_cover_every_day_of_those_months() -> None:
    weeks = weeks_around(utc(2026, 10, 18, 12))
    first, last = week_days(*weeks[0]), week_days(*weeks[-1])
    assert first[0] <= date(2025, 10, 1) <= first[-1]
    assert last[0] <= date(2027, 10, 31) <= last[-1]
    assert len(set(weeks)) == len(weeks) and weeks == sorted(weeks)


# --- Which days an event is on


def test_an_event_is_on_its_central_time_start_day() -> None:
    # 11:30 PM on Tue Oct 20 in Omaha is 04:30 on Oct 21 in UTC.
    assert days_spanned(utc(2026, 10, 21, 4, 30), None, all_day=False) == [date(2026, 10, 20)]


def test_an_event_crossing_midnight_is_on_both_days() -> None:
    # 10 PM Oct 20 to 1 AM Oct 21, Central.
    spans = days_spanned(utc(2026, 10, 21, 3), utc(2026, 10, 21, 6), all_day=False)
    assert spans == [date(2026, 10, 20), date(2026, 10, 21)]


def test_an_event_ending_at_midnight_does_not_reach_the_next_day() -> None:
    # 6 PM to 12 AM Central, Oct 20.
    spans = days_spanned(utc(2026, 10, 20, 23), utc(2026, 10, 21, 5), all_day=False)
    assert spans == [date(2026, 10, 20)]


def test_a_two_day_event_is_on_both_days() -> None:
    # A conference, 8 AM Nov 5 to 5 PM Nov 6, Central.
    spans = days_spanned(utc(2026, 11, 5, 14), utc(2026, 11, 6, 23), all_day=False)
    assert spans == [date(2026, 11, 5), date(2026, 11, 6)]


def test_an_all_day_event_covers_its_days_but_not_its_end_date() -> None:
    # Stored like a calendar feed: Oct 20 to Oct 22 at midnight Central, end not included.
    spans = days_spanned(utc(2026, 10, 20, 5), utc(2026, 10, 22, 5), all_day=True)
    assert spans == [date(2026, 10, 20), date(2026, 10, 21)]
    assert days_spanned(utc(2026, 10, 20, 5), None, all_day=True) == [date(2026, 10, 20)]


@pytest.mark.parametrize(
    ("start", "day"),
    [
        (utc(2026, 11, 1, 4, 30), date(2026, 10, 31)),  # 11:30 PM CDT, Sat Oct 31
        (utc(2026, 11, 1, 6, 30), date(2026, 11, 1)),  # 1:30 AM CDT, the first one
        (utc(2026, 11, 1, 7, 30), date(2026, 11, 1)),  # 1:30 AM CST, the second one
        (utc(2026, 11, 2, 5, 30), date(2026, 11, 1)),  # 11:30 PM CST, Sun Nov 1
        (utc(2027, 3, 14, 7, 30), date(2027, 3, 14)),  # 1:30 AM CST, before spring forward
        (utc(2027, 3, 15, 4, 30), date(2027, 3, 14)),  # 11:30 PM CDT, Sun Mar 14
    ],
)
def test_dst_weeks_put_events_on_the_right_day(start: datetime, day: date) -> None:
    assert days_spanned(start, None, all_day=False) == [day]


def test_dst_weeks_still_have_seven_days() -> None:
    fall_back = week_days(*iso_week(date(2026, 11, 1)))
    assert fall_back == [date(2026, 10, 26) + timedelta(days=i) for i in range(7)]
    spring_forward = week_days(*iso_week(date(2027, 3, 14)))
    assert spring_forward == [date(2027, 3, 8) + timedelta(days=i) for i in range(7)]


# --- Bucketing events into the days shown


def test_events_are_bucketed_by_day_soonest_first() -> None:
    late = event(utc(2026, 11, 6, 1), slug="late")  # 7 PM Nov 5
    early = event(utc(2026, 11, 5, 18), slug="early")  # noon Nov 5
    conference = event(utc(2026, 11, 5, 14), utc(2026, 11, 6, 23), slug="conf")
    days = week_days(2026, 45)
    buckets = events_by_day([late, early, conference], days)
    assert set(buckets) == set(days)
    assert [e.slug for e in buckets[date(2026, 11, 5)]] == ["conf", "early", "late"]
    assert [e.slug for e in buckets[date(2026, 11, 6)]] == ["conf"]
    assert buckets[date(2026, 11, 2)] == []


def test_events_outside_the_days_shown_are_left_out() -> None:
    elsewhere = event(utc(2026, 12, 15, 18))
    assert all(v == [] for v in events_by_day([elsewhere], week_days(2026, 45)).values())
