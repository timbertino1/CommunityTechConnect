"""Feed detection: which connector reads a newly found site (T077; research R5).

Priority: iCal, then JSON-LD/microdata Event, then RSS/Atom; otherwise "none".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from netc.connectors.base import RawPayload
from netc.connectors.detect import detect, detect_in
from netc.fetch import FixtureHttp
from tests.connector_support import payload

pytestmark = pytest.mark.contract

PAGES = Path(__file__).resolve().parents[1] / "fixtures" / "finders" / "pages"
CANDIDATES = PAGES.parent / "candidates"


def page(
    name: str, url: str = "https://site.example.org/events", folder: Path = PAGES
) -> RawPayload:
    text = (folder / name).read_text(encoding="utf-8")
    return payload(text, url=url, content_type="text/html")


def test_an_ical_link_wins_over_an_rss_link() -> None:
    found = detect_in(page("coworking_calendar.html", "https://cowork.example.org/events"))
    assert found.kind == "ical"
    assert found.feed_url == "https://cowork.example.org/events.ics"  # webcal:// becomes https://


def test_event_data_wins_over_an_rss_link() -> None:
    found = detect_in(page("jsonld_events.html", "https://heartlandrust.example.org/"))
    assert found.kind == "jsonld"
    assert found.feed_url is None


def test_an_rss_or_atom_link_is_the_last_choice() -> None:
    found = detect_in(page("blog_with_rss.html", "https://blog.example.org/"))
    assert found.kind == "rss"
    assert found.feed_url == "https://blog.example.org/atom.xml"


def test_a_page_with_no_signals_is_none() -> None:
    found = detect_in(page("no_signals.html"))
    assert found.kind == "none"
    assert found.feed_url is None
    assert found.reason


def test_relative_and_alternate_calendar_links_are_resolved() -> None:
    html = """<html><head><link rel="alternate" type="text/calendar" href="/cal/all.ics">
    </head><body></body></html>"""
    found = detect_in(
        payload(html, url="https://group.example.org/about", content_type="text/html")
    )
    assert (found.kind, found.feed_url) == ("ical", "https://group.example.org/cal/all.ics")


def test_insecure_feed_links_are_ignored() -> None:
    html = """<html><head><link rel="alternate" type="application/rss+xml" href="http://x.example.org/feed">
    </head><body><a href="ftp://x.example.org/a.ics">cal</a></body></html>"""
    found = detect_in(payload(html, url="https://x.example.org/", content_type="text/html"))
    assert found.kind == "none"


def test_microdata_events_count_as_event_data() -> None:
    html = """<html><body><div itemscope itemtype="https://schema.org/Event">
    <span itemprop="name">Hack night</span>
    <meta itemprop="startDate" content="2026-11-20T18:00:00-06:00">
    </div></body></html>"""
    found = detect_in(payload(html, url="https://hack.example.org/", content_type="text/html"))
    assert found.kind == "jsonld"


def test_a_url_that_is_itself_a_calendar_or_feed() -> None:
    ics = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
    found = detect_in(payload(ics, url="https://g.example.org/e.ics", content_type="text/calendar"))
    assert (found.kind, found.feed_url) == ("ical", "https://g.example.org/e.ics")
    rss = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'
    found = detect_in(
        payload(rss, url="https://g.example.org/feed", content_type="application/rss+xml")
    )
    assert (found.kind, found.feed_url) == ("rss", "https://g.example.org/feed")


def test_candidate_pages_with_events_are_jsonld() -> None:
    # Detection only says how to read a site; relevance and place are judged later.
    for name in ("out_of_state.html", "non_tech.html"):
        assert detect_in(page(name, folder=CANDIDATES)).kind == "jsonld"


def fixture_http(tmp_path: Path, entries: dict[str, dict[str, object]]) -> FixtureHttp:
    (tmp_path / "index.json").write_text(json.dumps(entries), encoding="utf-8")
    return FixtureHttp(tmp_path)


def test_detect_fetches_the_page_once(tmp_path: Path) -> None:
    url = "https://blog.example.org/"
    http = fixture_http(
        tmp_path,
        {url: {"file": str(PAGES / "blog_with_rss.html"), "content_type": "text/html"}},
    )
    found = detect(url, http)
    assert found.kind == "rss"
    assert http.requested == [url]


def test_detect_reports_errors_as_none(tmp_path: Path) -> None:
    http = fixture_http(tmp_path, {"https://gone.example.org/": {"status": 404}})
    found = detect("https://gone.example.org/", http)
    assert found.kind == "none" and "404" in found.reason
    missing = detect("https://unknown.example.org/", http)
    assert missing.kind == "none" and "could not be read" in missing.reason
