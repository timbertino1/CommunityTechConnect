"""De-duplication (T051; FR-006, research R11)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from netc.models import Event, event_id_for
from netc.pipeline.dedupe import deduplicate, same_event
from tests.data_samples import HASH, make_event, utc

pytestmark = pytest.mark.unit

START = utc(2026, 11, 10, 23, 30)  # 5:30 PM CST


def ev(
    url: str = "https://www.meetup.com/prairie-python/events/316649529/",
    title: str = "Prairie Python Meetup",
    start: datetime = START,
    city: str | None = "Omaha",
    online: bool = False,
    source_id: str = "src_prairie-python",
    first_seen: datetime | None = None,
    **overrides: Any,
) -> Event:
    event = make_event(
        slug="prairie-python-meetup-2026-11-10",
        start=start,
        url=url,
        source_id=source_id,
        title=title,
        location={"venue": "Improving", "city": city, "state": "NE", "online": online},
        area="online" if online and city is None else "omaha",
        **overrides,
    )
    if first_seen is not None:
        event = event.model_copy(update={"first_seen": first_seen})
    return event


# --- Matching rules


def test_same_canonical_url_is_the_same_event() -> None:
    a = ev()
    b = ev(
        url="https://www.meetup.com/prairie-python/events/316649529/?utm_source=newsletter",
        title="Totally different",
    )
    assert a.id == b.id
    assert same_event(a, b)


def test_close_time_similar_title_same_city_is_the_same_event() -> None:
    a = ev()
    b = ev(
        url="https://prairiepython.example.org/nov",
        title="Prairie Python Meetup - November",
        start=START + timedelta(minutes=30),
    )
    assert same_event(a, b)


@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"start": START + timedelta(minutes=31)}, "more than 30 minutes apart"),
        ({"title": "Omaha Azure User Group"}, "different title"),
        ({"city": "Lincoln"}, "different city"),
        ({"online": True, "city": None}, "online vs in person"),
    ],
)
def test_events_that_differ_are_not_merged(changes: dict[str, Any], why: str) -> None:
    a = ev()
    b = ev(url="https://other.example.org/e", **changes)
    assert not same_event(a, b), why


def test_same_time_window_but_different_central_day_is_not_merged() -> None:
    # 11:50 PM and 12:10 AM Central are 20 minutes apart but on different days.
    a = ev(start=utc(2026, 11, 11, 5, 50))
    b = ev(url="https://other.example.org/e", start=utc(2026, 11, 11, 6, 10))
    assert not same_event(a, b)


def test_both_online_matches() -> None:
    a = ev(online=True, city=None)
    b = ev(url="https://other.example.org/e", online=True, city=None)
    assert same_event(a, b)


# --- Merging


def test_duplicates_merge_into_one_event_keeping_every_listing() -> None:
    a = ev()
    b = ev(
        url="https://prairiepython.example.org/nov",
        source_id="src_prairie-python-site",
        title="Prairie Python Meetup!",
    )
    merged = deduplicate([a, b])
    assert len(merged) == 1
    assert {x.source_id for x in merged[0].listings} == {
        "src_prairie-python",
        "src_prairie-python-site",
    }


def test_the_organizers_own_page_is_preferred_over_platforms_and_aggregators() -> None:
    meetup = ev()
    own_site = ev(url="https://prairiepython.example.org/nov", source_id="src_pp-site")
    aggregator = ev(url="https://dev.events/meetups/prairie-python-nov", source_id="src_devevents")
    for order in ([meetup, own_site, aggregator], [aggregator, own_site, meetup]):
        (merged,) = deduplicate(order)
        assert merged.original_url == "https://prairiepython.example.org/nov"


def test_a_platform_page_is_preferred_over_an_aggregator() -> None:
    meetup = ev()
    aggregator = ev(url="https://dev.events/meetups/prairie-python-nov", source_id="src_devevents")
    (merged,) = deduplicate([aggregator, meetup])
    assert merged.original_url == meetup.original_url


def test_the_oldest_event_keeps_its_id() -> None:
    old = ev(url="https://dev.events/meetups/prairie-python-nov", first_seen=utc(2026, 10, 1))
    new = ev(url="https://prairiepython.example.org/nov", first_seen=utc(2026, 10, 15))
    (merged,) = deduplicate([new, old])
    assert merged.id == old.id == event_id_for("https://dev.events/meetups/prairie-python-nov")
    assert merged.first_seen == utc(2026, 10, 1)
    assert merged.original_url == "https://prairiepython.example.org/nov"  # better link, same id


def test_merged_event_combines_categories_and_latest_verification() -> None:
    a = ev(categories=["software-dev"], last_verified=utc(2026, 10, 10))
    b = ev(
        url="https://prairiepython.example.org/nov",
        categories=["data-analytics"],
        last_verified=utc(2026, 10, 17),
    )
    (merged,) = deduplicate([a, b])
    assert set(merged.categories) == {"software-dev", "data-analytics"}
    assert merged.last_verified == utc(2026, 10, 17)


def test_the_same_listing_is_not_kept_twice() -> None:
    a = ev()
    (merged,) = deduplicate([a, a.model_copy()])
    assert len(merged.listings) == 1


def test_matches_chain_across_more_than_two_events() -> None:
    a = ev()
    b = ev(url="https://b.example.org/e", source_id="src_b", start=START + timedelta(minutes=20))
    c = ev(url="https://c.example.org/e", source_id="src_c", start=START + timedelta(minutes=40))
    merged = deduplicate([a, b, c])
    assert len(merged) == 1
    assert len(merged[0].listings) == 3


def test_unrelated_events_stay_separate_and_in_order() -> None:
    a = ev()
    b = ev(
        url="https://azure.example.org/e",
        title="Omaha Azure User Group",
        start=START + timedelta(days=1),
    )
    assert [e.id for e in deduplicate([a, b])] == [a.id, b.id]


def test_listing_hashes_survive_merging() -> None:
    (merged,) = deduplicate([ev(), ev(url="https://b.example.org/e", source_id="src_b")])
    assert all(x.content_hash == HASH for x in merged.listings)


# --- Cost (T157; FR-052): stated beats inferred beats unknown


def test_a_stated_cost_wins_when_listings_merge() -> None:
    a = ev(cost="free", inferred=["cost"])  # from a source default
    b = ev(
        url="https://prairiepython.example.org/nov",
        source_id="src_prairie-python-site",
        cost="paid",
        price="$10",
    )
    [merged] = deduplicate([a, b])
    assert (merged.cost, merged.price) == ("paid", "$10") and "cost" not in merged.inferred


def test_a_known_cost_wins_over_an_unknown_one() -> None:
    a = ev()
    b = ev(
        url="https://prairiepython.example.org/nov",
        source_id="src_prairie-python-site",
        cost="free",
    )
    [merged] = deduplicate([a, b])
    assert merged.cost == "free"
