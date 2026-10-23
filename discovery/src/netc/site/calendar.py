"""Calendar periods and days in Central Time, for the month and week pages (T108; US3,
FR-033, research R3).

Weeks run Monday to Sunday in both views: week pages are ISO weeks (contracts/site-urls.md), so
each row of a month grid is exactly one week page. An event covers every Central Time day from
its start day to its end day; an end at exactly midnight doesn't reach into the next day, which
is also how all-day events are stored (the end is the day after, not included).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, time, timedelta
from typing import Final

from netc.models import Event
from netc.pipeline.timeutil import to_central

MONTHS_BEFORE: Final = 12
MONTHS_AFTER: Final = 12
MAX_SPAN_DAYS: Final = 62
"""An event is shown on at most this many days, so a bad end date can't fill a year."""

type Month = tuple[int, int]
"""(year, month)"""
type Week = tuple[int, int]
"""(ISO year, ISO week)"""


def month_weeks(year: int, month: int) -> list[list[date]]:
    """The month as whole weeks: from the Monday on or before the 1st to the Sunday on or
    after the last day."""
    first = date(year, month, 1)
    last = date(*next_month(year, month), 1) - timedelta(days=1)
    day = first - timedelta(days=first.weekday())
    weeks: list[list[date]] = []
    while day <= last:
        weeks.append([day + timedelta(days=i) for i in range(7)])
        day += timedelta(days=7)
    return weeks


def week_days(iso_year: int, iso_week_number: int) -> list[date]:
    monday = date.fromisocalendar(iso_year, iso_week_number, 1)
    return [monday + timedelta(days=i) for i in range(7)]


def iso_week(day: date) -> Week:
    year, week, _ = day.isocalendar()
    return year, week


def prev_month(year: int, month: int) -> Month:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def next_month(year: int, month: int) -> Month:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def prev_week(iso_year: int, iso_week_number: int) -> Week:
    return iso_week(date.fromisocalendar(iso_year, iso_week_number, 1) - timedelta(days=7))


def next_week(iso_year: int, iso_week_number: int) -> Week:
    return iso_week(date.fromisocalendar(iso_year, iso_week_number, 1) + timedelta(days=7))


def current_month(now: datetime) -> Month:
    today = to_central(now).date()
    return today.year, today.month


def months_around(
    now: datetime, before: int = MONTHS_BEFORE, after: int = MONTHS_AFTER
) -> list[Month]:
    """The months that get a page: ``before`` months back to ``after`` ahead, in order."""
    month = current_month(now)
    for _ in range(before):
        month = prev_month(*month)
    months = [month]
    for _ in range(before + after):
        month = next_month(*month)
        months.append(month)
    return months


def weeks_around(
    now: datetime, before: int = MONTHS_BEFORE, after: int = MONTHS_AFTER
) -> list[Week]:
    """Every ISO week that has a day in one of ``months_around``, in order."""
    months = months_around(now, before, after)
    first = date(*months[0], 1)
    last = date(*next_month(*months[-1]), 1) - timedelta(days=1)
    week, end = iso_week(first), iso_week(last)
    weeks = [week]
    while week != end:
        week = next_week(*week)
        weeks.append(week)
    return weeks


def days_spanned(start: datetime, end: datetime | None, *, all_day: bool) -> list[date]:
    """The Central Time days an event is on, in order."""
    first = to_central(start).date()
    if end is None or end <= start:
        return [first]
    local_end = to_central(end)
    last = local_end.date()
    if local_end.time() == time(0) or all_day:
        last -= timedelta(
            days=1
        )  # an end at midnight (or all-day's exclusive end) ends the day before
    last = min(max(last, first), first + timedelta(days=MAX_SPAN_DAYS - 1))
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def events_by_day(events: Iterable[Event], days: Sequence[date]) -> dict[date, list[Event]]:
    """The events on each of ``days`` (every day present, empty or not), soonest first."""
    shown: dict[date, list[Event]] = {d: [] for d in days}
    for event in sorted(events, key=lambda e: (e.start, e.id)):
        for day in days_spanned(event.start, event.end, all_day=event.all_day):
            if day in shown:
                shown[day].append(event)
    return shown
