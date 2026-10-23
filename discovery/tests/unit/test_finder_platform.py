"""The platform finder: Meetup groups and Luma calendar feeds linked from what is already on
file become candidates, read only the ways each platform allows (T101-T102; research R6,
gates V1 and V3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from netc.finders.base import FinderContext, candidate_url, luma_calendar_feed, site_key
from netc.finders.platform import MAX_MEETUP_PER_RUN, PlatformFinder
from netc.models import AreaConfig, KnownGroup, Organizer
from netc.storage import DataStore
from tests.ai_support import NOW
from tests.data_samples import make_event, make_source

pytestmark = pytest.mark.unit

AREAS: AreaConfig = DataStore(Path(__file__).resolve().parents[3] / "data").read_areas()  # type: ignore[assignment]
FEED = "https://api.lu.ma/ics/get?entity=calendar&id=cal-AbC123xyz"


def ctx(**kw: object) -> FinderContext:
    return FinderContext(now=NOW, areas=AREAS, **kw)  # type: ignore[arg-type]


def urls(context: FinderContext) -> list[str]:
    return [c.url for c in PlatformFinder().run(context).candidates]


# --- Luma calendar feeds (gate V3)


@pytest.mark.parametrize(
    "url",
    [
        FEED,
        "webcal://api.lu.ma/ics/get?entity=calendar&id=cal-AbC123xyz",
        "https://api.lu.ma/ics/get?id=cal-AbC123xyz&entity=calendar&utm_source=x",
        "https://api.luma.com/ics/get?entity=calendar&id=cal-AbC123xyz",
    ],
)
def test_luma_calendar_feeds_are_recognized(url: str) -> None:
    assert luma_calendar_feed(url) is not None
    assert site_key(url) == "luma.com/cal-abc123xyz"
    assert candidate_url(url) == luma_calendar_feed(url)


def test_the_feed_keeps_only_the_calendar() -> None:
    url = "webcal://api.lu.ma/ics/get?entity=calendar&id=cal-AbC123xyz&utm_source=x"
    assert luma_calendar_feed(url) == FEED


@pytest.mark.parametrize(
    "url",
    [
        "https://api.lu.ma/ics/get?entity=event&id=evt-AbC123xyz",
        "https://api.lu.ma/ics/get?entity=user&id=usr-AbC123xyz",
        "https://api.lu.ma/ics/get?entity=calendar&id=../../x",
        "https://api.lu.ma/ics/other?entity=calendar&id=cal-AbC123xyz",
        "http://api.lu.ma/ics/get?entity=calendar&id=cal-AbC123xyz",
        "https://api.lu.ma.evil.example/ics/get?entity=calendar&id=cal-AbC123xyz",
        "https://luma.com/omaha-builders",
    ],
)
def test_other_luma_urls_are_not_feeds(url: str) -> None:
    assert luma_calendar_feed(url) is None


# --- Meetup (gate V1)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.meetup.com/find/?keywords=python",
        "https://www.meetup.com/gql",
        "https://www.meetup.com/gql2",
        "https://www.meetup.com/api/v3/groups",
        "https://www.meetup.com/meetup_api/",
        "https://www.meetup.com/members/12345/",
    ],
)
def test_meetup_search_api_and_member_urls_are_never_candidates(url: str) -> None:
    assert site_key(url) is None and candidate_url(url) is None


# --- The finder


def test_a_known_groups_meetup_link_becomes_a_candidate() -> None:
    group = KnownGroup(
        name="Omaha Go", area="omaha", links=["https://www.meetup.com/omaha-golang/events/"]
    )
    [candidate] = PlatformFinder().run(ctx(known_groups=[group])).candidates
    assert candidate.url == "https://www.meetup.com/omaha-golang/"
    assert candidate.found_via == "platform"
    assert "Omaha Go" in candidate.evidence[0]


def test_a_known_groups_luma_feed_becomes_a_candidate() -> None:
    group = KnownGroup(name="Omaha Builders Club", links=[FEED])
    assert urls(ctx(known_groups=[group])) == [FEED]


def test_an_events_meetup_page_points_to_its_group() -> None:
    event = make_event(url="https://www.meetup.com/lincoln-js/events/311/")
    assert urls(ctx(events=[event])) == ["https://www.meetup.com/lincoln-js/"]


def test_an_organizers_meetup_page_becomes_a_candidate() -> None:
    org = Organizer(id="org_nwct", name="NE Women in Tech", url="https://www.meetup.com/ne-wit/")
    assert urls(ctx(organizers=[org])) == ["https://www.meetup.com/ne-wit/"]


def test_groups_already_read_or_already_candidates_are_skipped() -> None:
    source = make_source("src_omaha-golang", url="https://www.meetup.com/omaha-golang/events/")
    luma = make_source("src_luma-cal-abc123xyz", url=FEED, feed_url=FEED)
    group = KnownGroup(
        name="Both",
        links=["https://www.meetup.com/omaha-golang/", FEED.replace("lu.ma", "luma.com")],
    )
    assert urls(ctx(known_groups=[group], sources=[source, luma])) == []


def test_luma_pages_and_other_sites_are_left_to_the_other_finders() -> None:
    group = KnownGroup(
        name="Pages",
        links=["https://luma.com/omaha-builders", "https://omahabuilders.example.org/"],
    )
    assert urls(ctx(known_groups=[group])) == []


def test_meetup_groups_per_run_are_capped() -> None:
    links = [f"https://www.meetup.com/group-{i}/" for i in range(MAX_MEETUP_PER_RUN + 2)]
    result = PlatformFinder().run(ctx(known_groups=[KnownGroup(name="Many", links=links)]))
    assert len(result.candidates) == MAX_MEETUP_PER_RUN
    assert result.stats["meetup_left_for_later"] == 2
    assert MAX_MEETUP_PER_RUN <= 5


def test_the_finder_fetches_and_searches_nothing() -> None:
    group = KnownGroup(name="Omaha Go", links=["https://www.meetup.com/omaha-golang/"])
    # No http client and no search provider: it still finds the group.
    assert urls(ctx(known_groups=[group], http=None, search=None)) == [
        "https://www.meetup.com/omaha-golang/"
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://jobs.lincolnfinancial.com/go/Information-Technology-&-Digital-Jobs/7746400",
        "https://portal.lincolntech.edu/dashboard",
        "https://www.lincolnshirecybersecurityforum.net/",
        "https://www.meetup.com/de-de/",
        "https://cms.erepublic.com/common/events/add_event_to_calendar/144627",
    ],
)
def test_obvious_non_sources_never_become_candidates(url: str) -> None:
    assert candidate_url(url) is None
