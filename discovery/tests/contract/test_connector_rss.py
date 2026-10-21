"""RSS/Atom connector: items become articles for the news finder unless they carry event data
(T077; research R5)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from netc.connectors.base import RawPayload
from netc.connectors.rss import RssConnector, read_feed
from netc.models import Source
from tests.connector_support import FETCHED_AT, payload
from tests.data_samples import make_source

pytestmark = pytest.mark.contract

FINDERS = Path(__file__).resolve().parents[1] / "fixtures" / "finders"
CHICAGO = ZoneInfo("America/Chicago")


def news(text: str | None = None) -> RawPayload:
    body = text if text is not None else (FINDERS / "rss" / "local_news.xml").read_text("utf-8")
    return payload(body, url="https://news.example.com/feed/", content_type="application/rss+xml")


def rss_source() -> Source:
    return make_source("src_test-rss", connector="rss", url="https://news.example.com/feed/")


def test_items_with_event_data_become_listings() -> None:
    feed = read_feed(news())
    [listing] = feed.listings
    assert listing.title == "Omaha Data Engineers: Streaming Night"
    assert listing.start == datetime(2026, 11, 10, 18, 0, tzinfo=CHICAGO).astimezone(
        listing.start.tzinfo
    )
    assert listing.end is not None and (listing.end - listing.start).total_seconds() == 7200
    assert listing.location_text == "Kiewit Luminarium, Omaha, NE"
    assert listing.organizer_text == "Omaha Data Engineers"
    assert listing.url == "https://news.example.com/events/streaming-night"
    assert listing.external_id == "evt-streaming-night"
    assert listing.all_day is False


def test_other_items_become_articles_not_events() -> None:
    feed = read_feed(news())
    titles = [a.title for a in feed.articles]
    assert titles == [
        "Lincoln Security Collective plans Cyber Night at The Mill",
        "Startup raises seed round",
    ]
    cyber = feed.articles[0]
    assert cyber.url == "https://news.example.com/2026/10/cyber-night-the-mill"
    assert cyber.published is not None and cyber.published.year == 2026
    assert "Cyber Night on Nov 12" in cyber.summary
    assert "<p>" not in cyber.summary
    assert cyber.links == ["https://lincolnsec.example.org/events"]


def test_past_events_are_counted_not_listed() -> None:
    feed = read_feed(news())
    assert feed.past == 1
    assert feed.latest_past is not None and feed.latest_past.month == 1


def test_items_without_a_safe_link_are_skipped_with_a_warning() -> None:
    feed = read_feed(news())
    assert all("javascript" not in a.url for a in feed.articles)
    assert any("no safe link" in w for w in feed.warnings)


def test_the_connector_returns_events_and_counts_the_articles() -> None:
    result = RssConnector().parse(rss_source(), news())
    assert [x.title for x in result.listings] == ["Omaha Data Engineers: Streaming Night"]
    assert any("2 items without event data" in w for w in result.warnings)
    assert result.past == 1


def test_atom_entries_are_read() -> None:
    atom = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title><id>urn:x</id>
<updated>2026-10-19T00:00:00Z</updated>
<entry><title>Meetup recap</title><id>urn:1</id><link href="https://blog.example.org/recap"/>
<updated>2026-10-18T00:00:00Z</updated><summary>Great turnout.</summary></entry></feed>"""
    feed = read_feed(news(atom))
    assert [a.title for a in feed.articles] == ["Meetup recap"]
    assert feed.listings == []


@pytest.mark.parametrize("text", ["", "not xml at all", "<html><body>hi</body></html>"])
def test_unreadable_feeds_return_nothing_without_raising(text: str) -> None:
    feed = read_feed(news(text))
    assert feed.listings == [] and feed.articles == []
    assert feed.warnings


def test_external_entities_are_not_resolved() -> None:
    evil = """<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e SYSTEM "file:///etc/passwd">]>
<rss version="2.0"><channel><item><title>&e;</title><link>https://x.example.org/</link></item>
</channel></rss>"""
    feed = read_feed(news(evil))
    assert all("root:" not in a.title for a in feed.articles)


def test_the_fetch_time_sets_the_window() -> None:
    assert FETCHED_AT.year == 2026  # the window runs from Oct 17, 2026 to mid-April 2027
