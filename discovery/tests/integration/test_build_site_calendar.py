"""`netc build-site` writes the month and week calendar pages (T107; US3, FR-033, FR-050, R3).

Static, semantic tables: a `<caption>`, `<th scope>` headings, and one cell per day carrying
its date in `data-date`. Each event links to its detail page and to the organizer's page, and
every period links to the one before and after. Pages run from 12 months back to 12 months
ahead; `/calendar/` sends visitors to the current Central Time month.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from selectolax.lexbor import LexborHTMLParser

from netc.models import Event
from tests.data_samples import utc
from tests.site_support import build, html_files, make_data, site_event

pytestmark = pytest.mark.integration

CONFERENCE = "heartland-dev-conference-2026-11-05"
HACK_NIGHT = "late-hack-night-2026-11-12"
NOVEMBER = "prairie-python-november-2026-11-10"
OCTOBER = "october-meetup-2026-10-06"


def events() -> list[Event]:
    return [
        site_event("https://prairiepython.example.org/nov", "Prairie Python November",
                   utc(2026, 11, 10, 23, 30), NOVEMBER),
        # 8 AM Nov 5 to 5 PM Nov 6, Central: a two-day conference.
        site_event("https://heartlanddev.example.org/2026", "Heartland Dev Conference",
                   utc(2026, 11, 5, 14), CONFERENCE, end=utc(2026, 11, 6, 23), cost="free"),
        # 10 PM Nov 12 to 1 AM Nov 13, Central.
        site_event("https://hacknight.example.org/nov", "Late Hack Night",
                   utc(2026, 11, 13, 4), HACK_NIGHT, end=utc(2026, 11, 13, 7), cost="paid"),
        # Before the build's "now" (Oct 18): past, but still on October's page.
        site_event("https://prairiepython.example.org/oct", "October Meetup",
                   utc(2026, 10, 6, 23, 30), OCTOBER),
        site_event("https://pending.example.org/e", "Waiting for review", utc(2026, 11, 3, 23),
                   "waiting-2026-11-03", review_state="pending_review"),
    ]  # fmt: skip


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("calendar")
    data = make_data(root / "data", events())
    out = root / "dist"
    assert build(data, out) == 0
    return out


def page(site: Path, path: str) -> Any:
    return LexborHTMLParser((site / path / "index.html").read_text(encoding="utf-8"))


def flat(node: Any) -> str:
    return " ".join(node.text(separator=" ").split())


def hrefs(node: Any) -> set[str]:
    return {a.attributes.get("href") or "" for a in node.css("a")}


def cell(tree: Any, day: str) -> Any:
    [found] = tree.css(f'td[data-date="{day}"]')
    return found


# --- /calendar/


def test_the_calendar_index_sends_visitors_to_the_current_month(site: Path) -> None:
    tree = page(site, "calendar")
    assert "/calendar/2026/10/" in hrefs(tree)  # a plain link, for anyone without redirects
    [refresh] = tree.css('meta[http-equiv="refresh"]')
    assert refresh.attributes["content"].replace(" ", "") == "0;url=/calendar/2026/10/"


def test_the_main_nav_links_to_the_calendar(site: Path) -> None:
    home = LexborHTMLParser((site / "index.html").read_text(encoding="utf-8"))
    assert "/calendar/" in hrefs(home.css_first("header nav"))
    nav = page(site, "calendar/2026/11").css_first("header nav")
    [current] = [a for a in nav.css("a") if a.attributes.get("aria-current") == "page"]
    assert current.attributes["href"] == "/calendar/"


# --- Month pages


def test_a_month_is_a_semantic_table(site: Path) -> None:
    tree = page(site, "calendar/2026/11")
    [table] = tree.css("main table")
    assert "November 2026" in flat(table.css_first("caption"))
    headings = [flat(th) for th in table.css('th[scope="col"]')]
    assert len(headings) == 7 and headings[0].startswith("Mon") and headings[6].startswith("Sun")
    assert len(table.css("td[data-date]")) == 6 * 7  # Oct 26 to Dec 6: six whole weeks


def test_events_are_on_their_central_time_days(site: Path) -> None:
    tree = page(site, "calendar/2026/11")
    assert f"/events/{NOVEMBER}/" in hrefs(cell(tree, "2026-11-10"))
    assert f"/events/{NOVEMBER}/" not in hrefs(cell(tree, "2026-11-11"))


def test_a_two_day_event_is_on_both_days(site: Path) -> None:
    tree = page(site, "calendar/2026/11")
    for day in ("2026-11-05", "2026-11-06"):
        assert f"/events/{CONFERENCE}/" in hrefs(cell(tree, day))
    assert f"/events/{CONFERENCE}/" not in hrefs(cell(tree, "2026-11-07"))


def test_an_event_crossing_midnight_is_on_both_days(site: Path) -> None:
    tree = page(site, "calendar/2026/11")
    for day in ("2026-11-12", "2026-11-13"):
        assert f"/events/{HACK_NIGHT}/" in hrefs(cell(tree, day))


def test_each_event_links_to_its_page_and_the_organizers(site: Path) -> None:
    entry = cell(page(site, "calendar/2026/11"), "2026-11-10")
    assert f"/events/{NOVEMBER}/" in hrefs(entry)
    [original] = [a for a in entry.css("a") if a.attributes.get("href", "").startswith("https://")]
    assert original.attributes["href"] == "https://prairiepython.example.org/nov"
    assert "noopener" in (original.attributes.get("rel") or "")


def test_past_months_still_show_their_events(site: Path) -> None:
    assert f"/events/{OCTOBER}/" in hrefs(cell(page(site, "calendar/2026/10"), "2026-10-06"))


def test_only_public_events_appear(site: Path) -> None:
    pages = {n: h for n, h in html_files(site).items() if n.startswith("calendar/")}
    assert len(pages) > 25  # months and weeks
    for name, html in pages.items():
        assert "Waiting for review" not in html, name


def test_months_link_to_the_previous_next_and_each_weeks_page(site: Path) -> None:
    links = hrefs(page(site, "calendar/2026/11").css_first("main"))
    assert {"/calendar/2026/10/", "/calendar/2026/12/"} <= links
    assert {f"/calendar/2026/week/{w}/" for w in range(44, 50)} <= links


# --- Week pages


def test_a_week_is_a_semantic_table_with_a_row_per_day(site: Path) -> None:
    tree = page(site, "calendar/2026/week/45")
    [table] = tree.css("main table")
    assert "Week 45" in flat(table.css_first("caption"))
    days = [flat(th) for th in table.css('th[scope="row"]')]
    assert len(days) == 7 and days[0].startswith("Mon") and "Nov 2" in days[0]
    assert [td.attributes["data-date"] for td in table.css("td[data-date]")] == [
        f"2026-11-0{d}" for d in range(2, 9)
    ]


def test_a_week_shows_its_events_on_each_day(site: Path) -> None:
    tree = page(site, "calendar/2026/week/45")
    for day in ("2026-11-05", "2026-11-06"):
        assert f"/events/{CONFERENCE}/" in hrefs(cell(tree, day))


def test_weeks_link_to_the_previous_and_next_week(site: Path) -> None:
    links = hrefs(page(site, "calendar/2026/week/45").css_first("main"))
    assert {"/calendar/2026/week/44/", "/calendar/2026/week/46/"} <= links


def test_week_numbers_are_two_digits_and_cross_the_year(site: Path) -> None:
    assert (site / "calendar" / "2027" / "week" / "01" / "index.html").exists()
    links = hrefs(page(site, "calendar/2026/week/53").css_first("main"))
    assert "/calendar/2027/week/01/" in links


# --- Range


def test_pages_run_from_twelve_months_back_to_twelve_ahead(site: Path) -> None:
    calendar = site / "calendar"
    assert (calendar / "2025" / "10" / "index.html").exists()
    assert (calendar / "2027" / "10" / "index.html").exists()
    assert not (calendar / "2025" / "09").exists()
    assert not (calendar / "2027" / "11").exists()


def test_no_calendar_link_points_at_a_missing_page(site: Path) -> None:
    checked = 0
    for name, html in html_files(site).items():
        for href in hrefs(LexborHTMLParser(html)):
            if href.startswith("/calendar/"):
                assert (site / href.strip("/") / "index.html").exists(), (name, href)
                checked += 1
    assert checked > 100  # every month and week page links to its neighbours


def test_calendar_entries_carry_what_the_filters_need(site: Path) -> None:
    tree = page(site, "calendar/2026/11")
    [entry] = cell(tree, "2026-11-06").css("li.cal-event")
    assert entry.attributes["data-start"] == "2026-11-05"  # the conference's first day
    assert entry.attributes["data-end"] == "2026-11-06"
    assert entry.attributes["data-cats"] and entry.attributes["data-area"]
    assert tree.css_first("form[data-filters]") is not None
    assert [s.attributes["src"] for s in tree.css("script")] == ["/js/filters.js"]


def test_the_nav_calendar_link_knows_the_current_month(site: Path) -> None:
    home = LexborHTMLParser((site / "index.html").read_text(encoding="utf-8"))
    [link] = [a for a in home.css("header nav a") if a.attributes.get("href") == "/calendar/"]
    assert link.attributes["data-current-month"] == "/calendar/2026/10/"


def test_calendar_entries_say_free_or_paid(site: Path) -> None:
    tree = page(site, "calendar/2026/11")

    def label(day: str, slug: str) -> str | None:
        for entry in cell(tree, day).css("li.cal-event"):
            if f"/events/{slug}/" in hrefs(entry):
                found = entry.css_first(".cost")
                return flat(found) if found else None
        raise AssertionError(f"{slug} not on {day}")

    assert label("2026-11-05", CONFERENCE) == "Cost: Free"
    assert label("2026-11-12", HACK_NIGHT) == "Cost: Paid"  # no price given
    assert label("2026-11-10", NOVEMBER) is None
