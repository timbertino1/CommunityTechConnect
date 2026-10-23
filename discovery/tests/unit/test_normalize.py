"""RawListing -> Event fields (T049; FR-003, FR-025, FR-027, FR-029, FR-031, FR-047, FR-048)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from netc.models import AreaConfig, RawListing, Source, event_id_for
from netc.pipeline.normalize import Dropped, Normalized, normalize, to_event
from netc.storage import DataStore
from tests.data_samples import make_source

pytestmark = pytest.mark.unit

AREAS: AreaConfig = DataStore(Path(__file__).resolve().parents[3] / "data").read_areas()  # type: ignore[assignment]
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def raw(**overrides: Any) -> RawListing:
    data: dict[str, Any] = {
        "external_id": "evt-1@example.org",
        "url": "https://www.meetup.com/prairie-python/events/316649529/",
        "title": "Prairie Python Meetup",
        "start": datetime(2026, 11, 10, 17, 30),
        "end": datetime(2026, 11, 10, 19, 30),
        "tz": "America/Chicago",
        "all_day": False,
        "location_text": "Improving, 18881 W Dodge Road Suite 120E, Omaha, NE 68022",
        "online": False,
        "organizer_text": "Prairie Python",
        "description_text": "Talks about Python packaging and testing.",
        "cancelled": False,
    }
    data.update(overrides)
    return RawListing(**data)


def norm(listing: RawListing, source: Source | None = None) -> Normalized:
    result = normalize(listing, source or make_source(default_area=None), AREAS, now=NOW)
    assert isinstance(result, Normalized), result
    return result


def dropped(listing: RawListing, source: Source | None = None) -> Dropped:
    result = normalize(listing, source or make_source(default_area=None), AREAS, now=NOW)
    assert isinstance(result, Dropped), result
    return result


# --- Times


def test_times_are_converted_to_utc_and_source_zone_kept() -> None:
    n = norm(raw())
    assert n.start == datetime(2026, 11, 10, 23, 30, tzinfo=UTC)  # CST after Nov 1
    assert n.end == datetime(2026, 11, 11, 1, 30, tzinfo=UTC)
    assert n.source_tz == "America/Chicago"
    assert n.tz_assumed is False


def test_missing_zone_is_assumed_central_and_marked_inferred() -> None:
    n = norm(raw(tz=None))
    assert n.source_tz == "America/Chicago"
    assert n.tz_assumed is True
    assert "source_tz" in n.inferred


def test_all_day_events() -> None:
    n = norm(raw(all_day=True, start=datetime(2026, 11, 20), end=None))
    assert n.all_day is True
    assert n.start == datetime(2026, 11, 20, 6, 0, tzinfo=UTC)


# --- Text


def test_title_and_summary_are_plain_text_and_bounded() -> None:
    n = norm(
        raw(
            title="<script>alert(1)</script>" + "Python " * 100,
            description_text="<p>Talks</p>" + " word" * 400,
        )
    )
    assert 1 <= len(n.title) <= 200
    assert "<" not in n.title
    assert len(n.summary) <= 500
    assert n.summary.startswith("Talks word")


def test_a_title_that_cleans_to_nothing_is_dropped() -> None:
    assert "title" in dropped(raw(title="<script>x</script>  ")).reason


def test_missing_description_gives_an_empty_summary() -> None:
    assert norm(raw(description_text=None)).summary == ""


# --- Links, id and slug


@pytest.mark.parametrize(
    "url", [None, "javascript:alert(1)", "http://example.org/e", "https://10.0.0.1/e"]
)
def test_listing_without_a_safe_https_link_is_dropped(url: str | None) -> None:
    assert "link" in dropped(raw(url=url)).reason


def test_original_url_id_and_slug() -> None:
    n = norm(raw(url="HTTPS://www.Meetup.com/prairie-python/events/316649529/?utm_source=x"))
    assert n.original_url == "https://www.meetup.com/prairie-python/events/316649529/?utm_source=x"
    assert n.event_id == event_id_for("https://www.meetup.com/prairie-python/events/316649529/")
    assert n.slug == "prairie-python-meetup-2026-11-10"  # Central Time date


def test_slug_uses_the_central_time_date() -> None:
    # 10:30 PM on Nov 30 in Omaha is already Dec 1 in UTC.
    n = norm(raw(start=datetime(2026, 11, 30, 22, 30), end=None))
    assert n.slug.endswith("2026-11-30")


def test_listing_records_source_and_a_content_hash() -> None:
    a = norm(raw())
    b = norm(raw(description_text="Different talk."))
    assert a.listing.source_id == "src_omaha-python"
    assert a.listing.last_seen == NOW
    assert a.listing.missing_runs == 0
    assert len(a.listing.content_hash) == 64
    assert a.listing.content_hash != b.listing.content_hash
    assert norm(raw()).listing.content_hash == a.listing.content_hash


def test_cancelled_listing_sets_cancelled() -> None:
    assert norm(raw(cancelled=True)).cancelled is True


# --- Area (FR-036) from the gazetteer


@pytest.mark.parametrize(
    ("location", "area", "city"),
    [
        ("Improving, 18881 W Dodge Road Suite 120E, Omaha, NE", "omaha", "Omaha"),
        ("Smash Park, 8121 S 125th St, La Vista, NE 68128", "omaha", "La Vista"),
        ("Somewhere, Papillion, Nebraska", "omaha", "Papillion"),
        ("Avery Hall 115, 1144 T St, Lincoln, NE 68588", "lincoln", "Lincoln"),
        ("Main St Coffee, Waverly, NE", "lincoln", "Waverly"),
        ("Library, Kearney, NE 68847", "other_ne", "Kearney"),
        ("Community Center, 68847", "other_ne", None),  # ZIP prefix only
        ("Building 4, 68144", "omaha", None),  # Omaha ZIP prefix 681
        ("Scott Conference Center", "omaha", None),  # venue
        ("Nebraska Innovation Campus, Room 2", "lincoln", None),
    ],
)
def test_area_from_location(location: str, area: str, city: str | None) -> None:
    n = norm(raw(location_text=location))
    assert n.area == area
    assert n.location.city == city
    assert "area" not in n.inferred


def test_online_events_are_in_the_online_area() -> None:
    n = norm(raw(location_text="Online", online=True))
    assert n.area == "online"
    assert n.location.online is True


def test_unknown_location_falls_back_to_the_source_area_as_inferred() -> None:
    n = norm(raw(location_text="Room 101"), make_source(default_area="lincoln"))
    assert n.area == "lincoln"
    assert "area" in n.inferred


def test_unknown_location_without_a_source_area_is_left_open() -> None:
    n = norm(raw(location_text="Room 101"))
    assert n.area is None


def test_council_bluffs_is_excluded_unless_the_host_is_nebraska_based() -> None:
    location = "Mid-America Center, One Arena Way, Council Bluffs, IA 51501"
    assert "outside Nebraska" in dropped(raw(location_text=location)).reason
    n = norm(raw(location_text=location), make_source(default_area="omaha"))
    assert n.area == "omaha"
    assert "area" in n.inferred


def test_state_alone_places_an_event_in_other_nebraska() -> None:
    assert norm(raw(location_text="Event Hall, Ogallala, Nebraska")).area == "other_ne"


def test_location_fields_are_plain_text() -> None:
    n = norm(raw(location_text="<img src=x onerror=alert(1)>Venue, Omaha, NE"))
    assert n.location.venue == "Venue"
    assert n.location.state == "NE"
    assert "<" not in (n.location.address or "")


# --- Building the Event


def test_to_event_builds_a_valid_event() -> None:
    n = norm(raw())
    event = to_event(n, categories=["software-dev"], review_state="published", now=NOW)
    assert event.id == n.event_id
    assert event.slug == n.slug
    assert event.title == "Prairie Python Meetup"
    assert event.area == "omaha"
    assert event.categories == ["software-dev"]
    assert event.status == "scheduled"
    assert event.review_state == "published"
    assert event.visibility == "shown"
    assert event.first_seen == NOW
    assert event.last_verified == NOW
    assert "categories" in event.inferred
    assert event.listings == [n.listing]
    assert event.start.date() == date(2026, 11, 10)


def test_to_event_requires_an_area() -> None:
    n = norm(raw(location_text="Room 101"))
    with pytest.raises(ValueError, match="area"):
        to_event(n, categories=["software-dev"], review_state="published", now=NOW)


def test_to_event_can_take_an_area_from_classification() -> None:
    n = norm(raw(location_text="Room 101"))
    event = to_event(
        n, categories=["software-dev"], review_state="published", now=NOW, area="lincoln"
    )
    assert event.area == "lincoln"
    assert "area" in event.inferred


def test_http_links_on_the_host_we_read_over_https_are_upgraded() -> None:
    # UNL's feed (read over https) writes its own event links as http://.
    source = make_source(
        url="https://events.unl.edu/cse/upcoming/",
        feed_url="https://events.unl.edu/cse/upcoming/?format=ics",
    )
    n = norm(raw(url="http://events.unl.edu/cse/2026/10/22/203007/"), source)
    assert n.original_url == "https://events.unl.edu/cse/2026/10/22/203007/"


def test_http_links_to_other_hosts_are_still_dropped() -> None:
    source = make_source(url="https://events.unl.edu/cse/upcoming/")
    assert "link" in dropped(raw(url="http://other.example.org/e"), source).reason


@pytest.mark.parametrize("placeholder", ["unknown", "Unknown", "N/A", "TBD", ""])
def test_placeholder_organizer_names_are_ignored(placeholder: str) -> None:
    assert norm(raw(organizer_text=placeholder)).organizer is None


def test_a_venue_named_nebraska_does_not_override_the_groups_area() -> None:
    # "Nebraska Union" is a building in Lincoln, not a statewide location.
    n = norm(raw(location_text="Nebraska Union Room"), make_source(default_area="lincoln"))
    assert n.area == "lincoln"
    assert "area" in n.inferred


def test_bare_nebraska_without_a_group_area_is_other_nebraska() -> None:
    assert norm(raw(location_text="Nebraska Union Room")).area == "other_ne"


# --- Cost (T157; FR-052)


def test_the_listings_cost_is_kept() -> None:
    n = norm(raw(cost="paid", price="$25"))
    assert (n.cost, n.price) == ("paid", "$25") and "cost" not in n.inferred


def test_a_sources_free_default_fills_in_an_unknown_cost_and_says_so() -> None:
    n = norm(raw(), make_source(default_area=None, default_cost="free"))
    assert (n.cost, n.price) == ("free", None) and "cost" in n.inferred


def test_what_the_event_says_beats_the_sources_default() -> None:
    n = norm(raw(cost="paid", price="$40"), make_source(default_area=None, default_cost="free"))
    assert (n.cost, n.price) == ("paid", "$40") and "cost" not in n.inferred


def test_without_either_the_cost_stays_unknown() -> None:
    assert norm(raw()).cost is None


def test_a_price_is_cleaned_to_plain_text() -> None:
    assert norm(raw(cost="paid", price=" <b>$25</b>  ")).price == "$25"


def test_the_cost_reaches_the_event() -> None:
    n = norm(raw(), make_source(default_area=None, default_cost="free"))
    event = to_event(n, categories=["software-dev"], review_state="published", now=NOW)
    assert event.cost == "free" and "cost" in event.inferred


# --- Country: Lincoln, England is not Lincoln, Nebraska


@pytest.mark.parametrize("country", ["gb", "GB", "United Kingdom", "CA"])
def test_a_listing_outside_the_united_states_is_dropped(country: str) -> None:
    listing = raw(location_text="The Hub, Lincoln, H7 LN1 1AA", country=country)
    reason = dropped(listing, make_source(default_area="lincoln")).reason
    assert "outside the United States" in reason


@pytest.mark.parametrize("country", ["US", "us", "USA", "United States", None])
def test_a_us_or_unstated_country_is_kept(country: str | None) -> None:
    assert norm(raw(country=country)).area == "omaha"
