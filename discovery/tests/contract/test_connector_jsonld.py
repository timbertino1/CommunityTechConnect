"""Contract tests for the JSON-LD / microdata connector (T048; research R5)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from netc.connectors.jsonld import JsonLdConnector
from tests.connector_support import by_title, fixture_text, jsonld_source, payload
from tests.fetch_support import make_http, mocked_web

pytestmark = pytest.mark.contract

CONNECTOR = JsonLdConnector()
CST = timezone(timedelta(hours=-6))
HTML = {"content-type": "text/html; charset=utf-8"}


def parse(relative: str, url: str = "https://www.example.org/events"):  # type: ignore[no-untyped-def]
    return CONNECTOR.parse(
        jsonld_source(), payload(fixture_text(relative), url=url, content_type="text/html")
    )


def test_kind_is_jsonld() -> None:
    assert JsonLdConnector.kind == "jsonld"


# --- JSON-LD


def test_single_event_page() -> None:
    result = parse("jsonld/event_page.html")
    (event,) = result.listings
    assert event.title == "Omaha Azure User Group Meeting - November 2026"
    assert event.start == datetime(2026, 11, 18, 18, 0, tzinfo=CST)
    assert event.end == datetime(2026, 11, 18, 19, 30, tzinfo=CST)
    assert event.url == "https://www.meetup.com/omaha-azure-user-group/events/316105999/"
    assert event.external_id == event.url
    assert event.organizer_text == "Omaha Azure User Group"
    assert event.online is False  # mixed: there is a physical place
    assert event.location_text is not None
    for part in ("Mutual of Omaha Tech Center", "3300 Dodge St", "Omaha", "NE", "68131"):
        assert part in event.location_text
    assert (
        event.description_text == "Monthly meeting with a talk on Azure networking. Food provided."
    )
    assert event.cancelled is False
    assert event.all_day is False
    assert event.tz is None  # only an offset, not a named zone


def test_graph_arrays_subtypes_and_item_lists() -> None:
    result = parse("jsonld/graph_multiple.html")
    events = by_title(result.listings)
    assert set(events) == {
        "AI Demo Night",
        "Intro to RAG workshop",
        "Startup pitch night",
        "Hackathon weekend",
    }
    assert events["AI Demo Night"].organizer_text == "AI Builders Lincoln/Omaha"  # resolved via @id
    assert (
        events["AI Demo Night"].external_id
        == "https://lincoln-omaha.example.org/p/demo-night#event"
    )
    assert events["AI Demo Night"].location_text == "FUSE Coworking, 1033 O St, Lincoln, NE 68508"
    assert any("No start date here" in w for w in result.warnings)


def test_event_status_and_attendance_mode() -> None:
    events = by_title(parse("jsonld/graph_multiple.html").listings)
    assert events["Intro to RAG workshop"].online is True
    assert events["AI Demo Night"].online is False
    assert events["Hackathon weekend"].cancelled is True
    assert events["Startup pitch night"].cancelled is True  # postponed with no new date


def test_postponed_events_are_flagged_in_warnings() -> None:
    result = parse("jsonld/graph_multiple.html")
    assert any("postponed" in w.lower() for w in result.warnings)


def test_date_only_start_is_an_all_day_event() -> None:
    pitch = by_title(parse("jsonld/graph_multiple.html").listings)["Startup pitch night"]
    assert pitch.all_day is True
    assert pitch.start.date() == date(2026, 11, 20)


def test_event_without_its_own_url_uses_the_page_url() -> None:
    (event,) = parse(
        "jsonld/nenug_event.html", url="https://www.usnua.example/live/nenug-omaha-fall-event-2026"
    ).listings
    assert event.url == "https://www.usnua.example/live/nenug-omaha-fall-event-2026"
    assert event.title == "(NE)NUG Omaha Fall Event 2026"
    assert event.location_text == "Smash Park, 8121 S 125th St, La Vista, NE 68128"


# --- Microdata


def test_microdata_events() -> None:
    result = parse("jsonld/microdata.html", url="https://dotnet.example.org/")
    events = by_title(result.listings)
    blazor = events["Lincoln .NET User Group: Blazor in practice"]
    assert blazor.start == datetime(2026, 11, 10, 18, 0, tzinfo=CST)
    assert blazor.end == datetime(2026, 11, 10, 20, 0, tzinfo=CST)
    assert blazor.url == "https://dotnet.example.org/events/blazor"
    assert blazor.location_text == "Nelnet Campus, 121 S 13th St, Lincoln, NE"
    assert blazor.description_text == "An evening of Blazor demos."
    social = events["Holiday social"]
    assert social.online is True
    assert social.start == datetime(2026, 12, 15, 18, 0, tzinfo=CST)


# --- Broken and hostile input


def test_broken_json_blocks_are_skipped_without_raising() -> None:
    result = parse("jsonld/broken_json.html")
    assert [x.title for x in result.listings] == ["Good event after broken ones"]
    assert len(result.warnings) >= 2


def test_malicious_page_is_parsed_without_raising() -> None:
    result = parse("jsonld/malicious.html")
    titles = [x.title for x in result.listings]
    assert any("Totally normal meetup" in t for t in titles)
    assert "Deep" in titles
    evil = next(x for x in result.listings if "Totally normal" in x.title)
    assert evil.organizer_text is None  # a Person, not an organization: not kept
    assert result.warnings  # the event with an object as its name was skipped


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not html at all",
        '<script type="application/ld+json">' + "[" * 5000 + "]" * 5000 + "</script>",
        '<script type="application/ld+json">'
        '{"@type":"Event","name":"x","startDate":"2026-13-45"}</script>',
    ],
)
def test_odd_pages_never_raise(text: str) -> None:
    CONNECTOR.parse(jsonld_source(), payload(text, content_type="text/html"))


def test_duplicate_events_on_a_page_are_listed_once() -> None:
    block = fixture_text("jsonld/broken_json.html")
    result = CONNECTOR.parse(jsonld_source(), payload(block + block, content_type="text/html"))
    assert len(result.listings) == 1


# --- Fetching, including follow_links


def test_fetch_reads_the_source_page() -> None:
    with mocked_web("www.example.org") as web, make_http() as http:
        web.get("https://www.example.org/events").respond(
            200, text=fixture_text("jsonld/event_page.html"), headers=HTML
        )
        fetched = CONNECTOR.fetch(jsonld_source(), http)
    assert fetched.linked == ()
    assert len(CONNECTOR.parse(jsonld_source(), fetched).listings) == 1


def nenug_source(max_pages: int = 10):  # type: ignore[no-untyped-def]
    return jsonld_source(
        url="https://www.usnua.example/",
        follow_links={"path_glob": "/live/nenug-*", "max_pages": max_pages},
    )


def test_follow_links_reads_only_matching_same_site_pages() -> None:
    with mocked_web("www.usnua.example") as web, make_http() as http:
        web.get("https://www.usnua.example/").respond(
            200, text=fixture_text("jsonld/listing.html"), headers=HTML
        )
        omaha = web.get("https://www.usnua.example/live/nenug-omaha-fall-event-2026").respond(
            200, text=fixture_text("jsonld/nenug_event.html"), headers=HTML
        )
        lincoln = web.get("https://www.usnua.example/live/nenug-lincoln-winter-event-2027").respond(
            404
        )
        texas = web.get(url__regex=r".*txnug.*").respond(200, text="", headers=HTML)
        offsite = web.get(url__regex=r"https://other-site\.example/.*").respond(
            200, text="", headers=HTML
        )
        fetched = CONNECTOR.fetch(nenug_source(), http)
        assert omaha.call_count == 1  # the duplicate link and the ?hsLang=en variant count once
        assert lincoln.called
        assert not texas.called
        assert not offsite.called
    assert len(fetched.linked) == 1
    assert any("404" in w for w in fetched.warnings)
    result = CONNECTOR.parse(nenug_source(), fetched)
    assert [x.url for x in result.listings] == [
        "https://www.usnua.example/live/nenug-omaha-fall-event-2026"
    ]
    assert any("404" in w for w in result.warnings)


def test_follow_links_respects_max_pages() -> None:
    with mocked_web("www.usnua.example") as web, make_http() as http:
        web.get("https://www.usnua.example/").respond(
            200, text=fixture_text("jsonld/listing.html"), headers=HTML
        )
        web.get(url__regex=r"https://www\.usnua\.example/live/.*").respond(
            200, text=fixture_text("jsonld/nenug_event.html"), headers=HTML
        )
        fetched = CONNECTOR.fetch(nenug_source(max_pages=1), http)
    assert len(fetched.linked) == 1


def test_follow_links_finds_urls_written_in_embedded_page_data() -> None:
    # Meetup builds its event links with JavaScript; the URLs exist only in embedded JSON.
    page = (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        '{"events":[{"link":"https://www.meetup.example/omaha-azure/events/316105999/"},'
        '{"link":"https://www.meetup.example/omaha-azure/events/calendar/"}]}'
        "</script></body></html>"
    )
    source = jsonld_source(
        url="https://www.meetup.example/omaha-azure/events/",
        follow_links={"path_glob": "/omaha-azure/events/[0-9]*", "max_pages": 5},
    )
    with mocked_web("www.meetup.example") as web, make_http() as http:
        web.get("https://www.meetup.example/omaha-azure/events/").respond(
            200, text=page, headers=HTML
        )
        event = web.get("https://www.meetup.example/omaha-azure/events/316105999/").respond(
            200, text=fixture_text("jsonld/event_page.html"), headers=HTML
        )
        calendar = web.get("https://www.meetup.example/omaha-azure/events/calendar/").respond(200)
        fetched = CONNECTOR.fetch(source, http)
        assert event.called
        assert not calendar.called
    assert len(CONNECTOR.parse(source, fetched).listings) == 1


def test_events_outside_the_window_are_left_out() -> None:
    past = (
        '<script type="application/ld+json">{"@type":"Event","name":"Last year",'
        '"startDate":"2025-11-19T18:00:00-06:00"}</script>'
    )
    far = (
        '<script type="application/ld+json">{"@type":"Event","name":"Next decade",'
        '"startDate":"2036-01-01T18:00:00-06:00"}</script>'
    )
    soon = (
        '<script type="application/ld+json">{"@type":"Event","name":"Next week",'
        '"startDate":"2026-10-25T18:00:00-05:00"}</script>'
    )
    result = CONNECTOR.parse(jsonld_source(), payload(past + far + soon, content_type="text/html"))
    assert [x.title for x in result.listings] == ["Next week"]


def test_past_events_are_counted_with_the_latest_start() -> None:
    # A group with nothing scheduled still shows its past meetings; the run report uses these
    # to tell a quiet group from a broken reader.
    def event(name: str, start: str) -> str:
        return (
            f'<script type="application/ld+json">{{"@type":"Event","name":"{name}",'
            f'"startDate":"{start}"}}</script>'
        )

    page = (
        event("August", "2026-08-11T17:30:00-05:00")
        + event("October", "2026-10-13T17:30:00-05:00")
        + event("October", "2026-10-13T17:30:00-05:00")  # same event on a linked page
        + event("Next decade", "2036-01-01T18:00:00-06:00")  # ahead of the window: not past
    )
    result = CONNECTOR.parse(jsonld_source(), payload(page, content_type="text/html"))
    assert result.listings == []
    assert result.past == 2
    assert result.latest_past == datetime(2026, 10, 13, 22, 30, tzinfo=UTC)


def test_no_past_events_means_no_latest_past() -> None:
    result = parse("jsonld/event_page.html")
    assert result.past == 0
    assert result.latest_past is None


def test_address_parts_already_in_the_street_line_are_not_repeated() -> None:
    # Meetup puts city and state inside streetAddress as well as in their own fields.
    page = (
        '<script type="application/ld+json">{"@type":"Event","name":"Prairie Python Meetup",'
        '"startDate":"2026-11-10T17:30:00-06:00","location":{"@type":"Place","name":"Improving",'
        '"address":{"@type":"PostalAddress",'
        '"streetAddress":"18881 W Dodge Road Suite 120E, Omaha, NE",'
        '"addressLocality":"Omaha","addressRegion":"NE"}}}</script>'
    )
    (event,) = CONNECTOR.parse(jsonld_source(), payload(page, content_type="text/html")).listings
    assert event.location_text == "Improving, 18881 W Dodge Road Suite 120E, Omaha, NE"


def test_malformed_links_on_a_page_are_skipped_not_fatal() -> None:
    from netc.connectors.jsonld import page_listings

    html = (
        '<html><body><a href="http://[bad">x</a><script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Event","name":"Rust Night",'
        '"startDate":"2026-11-18T18:30:00-06:00","url":"http://[bad",'
        '"image":"https://[::1"}</script></body></html>'
    )
    listings = page_listings(
        payload(html, url="https://www.example.org/e", content_type="text/html")
    )
    assert [item.title for item in listings] == ["Rust Night"]


# --- Cost (T157; FR-052)


def _cost(extra: str) -> tuple[str | None, str | None]:
    from netc.connectors.jsonld import page_listings

    html = (
        '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Event",'
        '"name":"Rust Night","startDate":"2026-11-18T18:30:00-06:00"' + extra + "}</script>"
    )
    page = payload(html, url="https://www.example.org/e", content_type="text/html")
    [listing] = page_listings(page)
    return listing.cost, listing.price


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ("", (None, None)),
        (',"isAccessibleForFree":true', ("free", None)),
        (',"isAccessibleForFree":"True"', ("free", None)),
        (',"offers":{"@type":"Offer","price":"0","priceCurrency":"USD"}', ("free", None)),
        (',"offers":[{"price":0},{"price":"0.00"}]', ("free", None)),
        (',"offers":{"price":"25","priceCurrency":"USD"}', ("paid", "$25")),
        (',"offers":{"price":"7.50","priceCurrency":"USD"}', ("paid", "$7.50")),
        (',"offers":[{"price":"10"},{"price":"25.00"}]', ("paid", "$10\N{EN DASH}$25")),
        (
            ',"offers":{"@type":"AggregateOffer","lowPrice":"0","highPrice":"15"}',
            ("paid", "Free\N{EN DASH}$15"),
        ),
        (',"offers":{"price":"20","priceCurrency":"EUR"}', ("paid", None)),
        (',"isAccessibleForFree":false', ("paid", None)),
        (',"offers":{"price":"call us"}', (None, None)),
    ],
)
def test_cost_comes_from_free_flags_and_offers(
    extra: str, expected: tuple[str | None, str | None]
) -> None:
    assert _cost(extra) == expected


# --- Country: Lincoln, England is not Lincoln, Nebraska


def _country(address: str) -> str | None:
    from netc.connectors.jsonld import page_listings

    html = (
        '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Event",'
        '"name":"AWS night","startDate":"2026-10-27T18:30:00+00:00","location":{"@type":"Place",'
        '"name":"The Hub","address":{"@type":"PostalAddress","addressLocality":"Lincoln"'
        + address
        + "}}}</script>"
    )
    page = payload(html, url="https://www.example.org/e", content_type="text/html")
    [listing] = page_listings(page)
    return listing.country


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (',"addressRegion":"H7","addressCountry":"gb"', "gb"),
        (',"addressRegion":"NE","addressCountry":"US"', "US"),
        (',"addressCountry":{"@type":"Country","name":"United Kingdom"}', "United Kingdom"),
        (',"addressRegion":"NE"', None),
    ],
)
def test_the_places_country_is_read(address: str, expected: str | None) -> None:
    assert _country(address) == expected
