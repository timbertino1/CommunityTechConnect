"""Contract tests for the iCal connector (T047; research R5)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from netc.connectors.ical import MAX_DESCRIPTION_CHARS, IcalConnector
from netc.fetch import ContentTypeNotAllowedError, FetchError
from tests.connector_support import FETCHED_AT, by_title, fixture_text, ical_source, payload
from tests.fetch_support import FakeClock, make_http, mocked_web

pytestmark = pytest.mark.contract

CHICAGO = ZoneInfo("America/Chicago")
CONNECTOR = IcalConnector()


def parse(relative: str, **replace: str):  # type: ignore[no-untyped-def]
    return CONNECTOR.parse(ical_source(), payload(fixture_text(relative, **replace)))


# --- Valid feeds


def test_kind_is_ical() -> None:
    assert IcalConnector.kind == "ical"


def test_valid_feed_parses_events_to_raw_listings() -> None:
    result = parse("ical/valid.ics")
    events = by_title(result.listings)
    assert set(events) == {
        "Industry in Residence: Nelnet",
        "School of Computing Showcase",
        "Fall Semester Break",
    }
    nelnet = events["Industry in Residence: Nelnet"]
    assert nelnet.start == datetime(2026, 10, 22, 11, 0, tzinfo=CHICAGO)
    assert nelnet.end == datetime(2026, 10, 22, 12, 0, tzinfo=CHICAGO)
    assert nelnet.tz == "America/Chicago"
    assert nelnet.all_day is False
    assert nelnet.url == "https://events.unl.edu/cse/2026/10/22/123456/"
    assert nelnet.external_id == "industry-residence-nelnet@events.unl.edu"
    assert nelnet.location_text == "Avery Hall 115, 1144 T St, Lincoln, NE 68588"
    assert nelnet.organizer_text == "School of Computing"
    assert nelnet.description_text is not None and "Pizza provided." in nelnet.description_text
    assert nelnet.cancelled is False
    assert nelnet.online is False


def test_duration_sets_the_end() -> None:
    showcase = by_title(parse("ical/valid.ics").listings)["School of Computing Showcase"]
    assert showcase.end is not None
    assert showcase.end - showcase.start == timedelta(hours=2)


def test_all_day_events_keep_their_dates() -> None:
    fall_break = by_title(parse("ical/valid.ics").listings)["Fall Semester Break"]
    assert fall_break.all_day is True
    assert fall_break.start.date() == date(2026, 10, 19)
    assert fall_break.end is not None and fall_break.end.date() == date(2026, 10, 21)


def test_private_events_are_skipped_with_a_warning() -> None:
    result = parse("ical/valid.ics")
    assert "Private planning meeting" not in by_title(result.listings)
    assert any("private" in w.lower() for w in result.warnings)


def test_organizer_email_addresses_are_never_kept() -> None:
    result = parse("ical/valid.ics")
    for listing in result.listings:
        assert "@unl.example" not in str(listing.model_dump())


# --- Recurrences


def test_recurrences_are_expanded_up_to_180_days_ahead() -> None:
    listings = parse("ical/recurring_monthly.ics").listings
    monthly = [x for x in listings if x.title == "ISACA Omaha chapter meeting"]
    assert [x.start.date() for x in monthly] == [
        date(2026, 11, 10),  # Oct 13 is before the window; Dec 8 is excluded (EXDATE)
        date(2027, 1, 12),
        date(2027, 2, 9),
        date(2027, 3, 9),
        date(2027, 4, 13),
    ]
    assert all(x.start.tzinfo == CHICAGO and x.start.hour == 18 for x in monthly)
    assert len({x.external_id for x in monthly}) == len(monthly)


def test_endless_recurrences_stop_at_the_window() -> None:
    listings = parse("ical/recurring_monthly.ics").listings
    weekly = [x for x in listings if x.title == "Weekly hack night"]
    window_end = FETCHED_AT + timedelta(days=180)
    assert len(weekly) == 26
    assert all(x.start <= window_end for x in weekly)


# --- Time zones


def test_source_time_zone_is_kept() -> None:
    assert all(x.tz == "America/Chicago" for x in parse("ical/valid.ics").listings if not x.all_day)


def test_floating_times_have_no_zone() -> None:
    (listing,) = parse("ical/missing_tz.ics").listings
    assert listing.start == datetime(2026, 10, 21, 18, 30)
    assert listing.start.tzinfo is None
    assert listing.tz is None
    assert listing.online is True  # LOCATION:Online


def test_utc_times_are_marked_utc() -> None:
    (listing,) = parse("ical/cancelled.ics").listings
    assert listing.tz == "UTC"
    assert listing.start.utcoffset() == timedelta(0)


# --- Status


def test_status_cancelled_maps_to_cancelled() -> None:
    (listing,) = parse("ical/cancelled.ics").listings
    assert listing.cancelled is True


# --- Hostile and broken input


def test_malicious_feed_is_parsed_without_raising_and_bounded() -> None:
    result = parse("ical/malicious.ics", HUGE="A" * 3_000_000)
    (listing,) = result.listings
    assert listing.description_text is not None
    assert len(listing.description_text) <= MAX_DESCRIPTION_CHARS
    assert any("truncated" in w for w in result.warnings)
    assert "organizer.person@example.org" not in str(listing.model_dump())
    # Cleaning (HTML, javascript: links) is normalize's job; the connector passes text through.
    assert listing.url == "javascript:alert(document.cookie)"


def test_invalid_dates_are_skipped_with_warnings() -> None:
    result = parse("ical/invalid_dates.ics")
    assert [x.title for x in result.listings] == ["The one good event"]
    assert len(result.warnings) >= 4


@pytest.mark.parametrize(
    "text",
    [
        "",
        "garbage, not a calendar",
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\n",
        "\x00\x01\x02",
        "<html>404</html>",
    ],
)
def test_unparseable_input_returns_a_warning_and_no_listings(text: str) -> None:
    result = CONNECTOR.parse(ical_source(), payload(text))
    assert result.listings == []
    assert result.warnings


# --- Fetching


def test_fetch_prefers_feed_url_and_accepts_calendar_content_types() -> None:
    source = ical_source(url="https://example.org/events", feed_url="https://example.org/cal.ics")
    with mocked_web("example.org") as web, make_http() as http:
        web.get("https://example.org/cal.ics").respond(
            200,
            text=fixture_text("ical/missing_tz.ics"),
            headers={"content-type": "text/plain; charset=utf-8"},
        )
        fetched = CONNECTOR.fetch(source, http)
    assert fetched.url == "https://example.org/cal.ics"
    assert "BEGIN:VCALENDAR" in fetched.text


def test_fetch_refuses_an_html_page() -> None:
    with mocked_web("example.org") as web, make_http() as http:
        web.get("https://example.org/feed.ics").respond(
            200, text="<html></html>", headers={"content-type": "text/html"}
        )
        with pytest.raises(ContentTypeNotAllowedError):
            CONNECTOR.fetch(ical_source(), http)


def test_fetch_uses_the_source_rate_limit() -> None:
    clock = FakeClock()
    with mocked_web("example.org") as web, make_http(clock=clock) as http:
        web.get("https://example.org/feed.ics").respond(
            200, text=fixture_text("ical/missing_tz.ics"), headers={"content-type": "text/calendar"}
        )
        CONNECTOR.fetch(ical_source(rate_limit_seconds=10), http)
    assert clock.sleeps == [10.0]  # robots.txt first, then the feed 10 s later


def test_fetch_treats_an_http_error_as_a_failure() -> None:
    with mocked_web("example.org") as web, make_http() as http:
        web.get("https://example.org/feed.ics").respond(404)
        with pytest.raises(FetchError, match="404"):
            CONNECTOR.fetch(ical_source(), http)
