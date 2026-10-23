"""`netc build-site`: the past-events archive (T115; FR-034, FR-035, FR-040)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from selectolax.lexbor import LexborHTMLParser

from netc.models import Event
from tests.data_samples import utc
from tests.site_support import build, make_data, site_event

pytestmark = pytest.mark.integration

# The build's clock (tests/site_support.NOW) is 2026-10-18 12:00 UTC.


def events() -> list[Event]:
    return [
        site_event("https://a.example.org/e", "September Security Night", utc(2026, 9, 16, 0),
                   "september-security-night-2026-09-15", categories=["security"]),
        site_event("https://b.example.org/e", "Lincoln AI Lunch", utc(2026, 10, 1, 17),
                   "lincoln-ai-lunch-2026-10-01", categories=["ai-ml"], area="lincoln",
                   location={"venue": "Union", "city": "Lincoln", "state": "NE", "online": False}),
        site_event("https://c.example.org/e", "Yesterday's Hack Night", utc(2026, 10, 17, 23),
                   "yesterdays-hack-night-2026-10-17", end=utc(2026, 10, 18, 2)),
        # Started before the build's clock but still running: upcoming until it ends (FR-035).
        site_event("https://d.example.org/e", "Saturday Workshop", utc(2026, 10, 18, 10),
                   "saturday-workshop-2026-10-18", end=utc(2026, 10, 18, 14)),
        site_event("https://e.example.org/e", "Holiday Demo Day", utc(2025, 12, 10, 0),
                   "holiday-demo-day-2025-12-09", original_unavailable=True),
        site_event("https://f.example.org/e", "November Meetup", utc(2026, 11, 10, 23),
                   "november-meetup-2026-11-10"),
        site_event("https://g.example.org/e", "Unreviewed Past Thing", utc(2026, 10, 2, 0),
                   "unreviewed-past-thing-2026-10-01", review_state="pending_review"),
    ]  # fmt: skip


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("netc.site.build.PAST_PAGE_SIZE", 2)
    data = make_data(tmp_path / "data", events())
    out = tmp_path / "dist"
    assert build(data, out) == 0
    return out


def page(out: Path, path: str) -> Any:
    return LexborHTMLParser((out / path / "index.html").read_text(encoding="utf-8"))


def titles(tree: Any) -> list[str]:
    return [h.text(strip=True) for h in tree.css("article.event h3")]


def test_ended_events_leave_the_upcoming_list(site: Path) -> None:
    home = LexborHTMLParser((site / "index.html").read_text(encoding="utf-8"))
    assert titles(home) == ["Saturday Workshop", "November Meetup"]


def test_past_events_are_listed_most_recent_first_across_pages(site: Path) -> None:
    first, second = page(site, "past"), page(site, "past/page/2")
    assert titles(first) == ["Yesterday's Hack Night", "Lincoln AI Lunch"]
    assert titles(second) == ["September Security Night", "Holiday Demo Day"]
    assert not (site / "past" / "page" / "3").exists()
    assert not (site / "past" / "page" / "1").exists()  # page 1 is /past/ itself


def test_unpublished_past_events_stay_out(site: Path) -> None:
    for path in ("past", "past/page/2"):
        assert "Unreviewed Past Thing" not in page(site, path).html


def test_pages_link_to_older_and_newer_events(site: Path) -> None:
    older = page(site, "past").css_first('a[rel="next"]')
    assert older is not None and older.attributes["href"] == "/past/page/2/"
    assert page(site, "past").css_first('a[rel="prev"]') is None
    newer = page(site, "past/page/2").css_first('a[rel="prev"]')
    assert newer is not None and newer.attributes["href"] == "/past/"
    assert page(site, "past/page/2").css_first('a[rel="next"]') is None


def test_months_are_headed_newest_first(site: Path) -> None:
    names = [
        h.css_first(".month-name").text(strip=True) for h in page(site, "past").css(".month h2")
    ]
    assert names == ["October 2026"]
    later = [
        h.css_first(".month-name").text(strip=True)
        for h in page(site, "past/page/2").css(".month h2")
    ]
    assert later == ["September 2026", "December 2025"]


def test_past_cards_link_to_the_original_page_without_offering_registration(site: Path) -> None:
    card = page(site, "past").css_first("article.event")
    cta = card.css_first(".cta a")
    assert cta.attributes["href"] == "https://c.example.org/e"
    assert "register" not in cta.text().lower()
    assert "c.example.org" in cta.text()


def test_past_events_keep_their_detail_pages(site: Path) -> None:
    assert (site / "events" / "holiday-demo-day-2025-12-09" / "index.html").exists()


def test_the_filters_work_on_past_pages(site: Path) -> None:
    tree = page(site, "past")
    assert tree.css_first("form[data-filters]") is not None
    assert tree.css_first('script[src="/js/filters.js"]') is not None
    lunch = next(c for c in tree.css("article.event") if "Lincoln AI Lunch" in c.text())
    assert lunch.attributes["data-area"] == "lincoln"
    assert lunch.attributes["data-cats"] == "ai-ml"


def test_the_nav_links_to_past_events(site: Path) -> None:
    link = page(site, "past").css_first('header nav a[href="/past/"]')
    assert link is not None and link.attributes.get("aria-current") == "page"
    home = LexborHTMLParser((site / "index.html").read_text(encoding="utf-8"))
    assert home.css_first('header nav a[href="/past/"]') is not None


def test_past_events_still_show_on_their_calendar_month(site: Path) -> None:
    september = page(site, "calendar/2026/09")
    assert "September Security Night" in september.css_first('td[data-date="2026-09-15"]').text()


def test_yearly_past_data_files_most_recent_first(site: Path) -> None:
    def read(year: int) -> list[str]:
        path = site / "data" / "past" / f"{year}.json"
        return [r["title"] for r in json.loads(path.read_text(encoding="utf-8"))]

    assert read(2026) == ["Yesterday's Hack Night", "Lincoln AI Lunch", "September Security Night"]
    assert read(2025) == ["Holiday Demo Day"]
    assert not (site / "data" / "past" / "2024.json").exists()


def test_without_past_events_the_page_says_so(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", [e for e in events() if e.title == "November Meetup"])
    out = tmp_path / "dist"
    assert build(data, out) == 0
    text = " ".join(page(out, "past").text().split())
    assert "No past events yet." in text
    assert not (out / "data" / "past").exists() or not any((out / "data" / "past").iterdir())


def test_a_gone_original_page_is_noted_on_the_card_and_the_event_page(site: Path) -> None:
    note = "The original page may no longer be available."
    cards = {
        c.css_first("h3").text(strip=True): c
        for c in page(site, "past/page/2").css("article.event")
    }
    assert note in " ".join(cards["Holiday Demo Day"].text().split())
    assert note not in " ".join(cards["September Security Night"].text().split())
    detail = page(site, "events/holiday-demo-day-2025-12-09")
    assert note in " ".join(detail.text().split())
