"""`netc build-site`: the upcoming list, detail pages, and public data (T054; FR-024-FR-026,
FR-031, FR-032)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from selectolax.lexbor import LexborHTMLParser

from netc.models import Event
from netc.storage import DataStore
from tests.data_samples import make_override, utc
from tests.site_support import build, html_files, make_data, site_event

pytestmark = pytest.mark.integration

PUBLIC_FIELDS = {
    "id", "slug", "title", "start", "end", "all_day", "area", "location", "organizer", "summary",
    "categories", "original_url", "status", "last_verified", "inferred", "original_unavailable",
}  # fmt: skip


def events() -> list[Event]:
    return [
        site_event(
            "https://prairiepython.example.org/dec",
            "Prairie Python December",
            utc(2026, 12, 8, 23, 30),
            "prairie-python-december-2026-12-08",
        ),
        site_event(
            "https://www.meetup.com/prairie-python/events/1/",
            "Prairie Python November",
            utc(2026, 11, 10, 23, 30),
            "prairie-python-november-2026-11-10",
        ),
        site_event(
            "https://online.example.org/e",
            "Remote Rust night",
            utc(2026, 11, 20, 0, 0),
            "remote-rust-night-2026-11-19",
            location={"venue": None, "city": None, "state": None, "online": True},
            area="online",
            categories=["software-dev", "web-mobile"],
        ),
        site_event(
            "https://cancel.example.org/e",
            "Cancelled CTF",
            utc(2026, 11, 21, 0, 0),
            "cancelled-ctf-2026-11-20",
            status="cancelled",
            categories=["security"],
        ),
        site_event(
            "https://pending.example.org/e",
            "Waiting for review",
            utc(2026, 11, 1),
            "waiting-2026-10-31",
            review_state="pending_review",
        ),
        site_event(
            "https://hidden.example.org/e",
            "Hidden by admin",
            utc(2026, 11, 2),
            "hidden-2026-11-01",
            visibility="hidden",
        ),
        site_event(
            "https://past.example.org/e",
            "Already happened",
            utc(2026, 10, 1),
            "already-happened-2026-10-01",
        ),
    ]


@pytest.fixture
def site(tmp_path: Path) -> Path:
    data = make_data(tmp_path / "data", events())
    # Events are hidden only by an override (FR-019); the stored "hidden" is what the last run
    # applied.
    hidden = next(e for e in events() if e.title == "Hidden by admin")
    DataStore(data).write_overrides([make_override(hidden.id, reason="spam")])
    out = tmp_path / "dist"
    assert build(data, out) == 0
    return out


def cards(out: Path) -> list:  # type: ignore[type-arg]
    tree = LexborHTMLParser((out / "index.html").read_text(encoding="utf-8"))
    return tree.css("article.event")


def test_list_shows_published_shown_upcoming_events_soonest_first(site: Path) -> None:
    titles = [c.css_first("h3").text(strip=True) for c in cards(site)]
    assert titles == [
        "Prairie Python November",
        "Remote Rust night",
        "Cancelled CTF",
        "Prairie Python December",
    ]


def test_each_card_shows_the_essentials(site: Path) -> None:
    first = cards(site)[0]
    text = " ".join(first.text(separator=" ").split())
    assert "Tue, Nov 10, 2026, 5:30 PM CT" in text
    assert "AIM Institute, Omaha" in text
    assert "Prairie Python" in text  # organizer
    assert "Software Development & Programming" in text  # category label


def test_online_events_say_online(site: Path) -> None:
    rust = cards(site)[1]
    assert "Online" in rust.text()


def test_cancelled_events_are_marked(site: Path) -> None:
    assert "Cancelled" in cards(site)[2].text()


def test_primary_link_goes_to_the_original_page(site: Path) -> None:
    link = cards(site)[0].css_first("a.primary")
    assert link.attributes["href"] == "https://www.meetup.com/prairie-python/events/1/"
    assert link.text(strip=True) == "View and register on www.meetup.com"
    assert "nofollow" not in (link.attributes.get("rel") or "")


def test_cards_link_to_detail_pages(site: Path) -> None:
    title_link = cards(site)[0].css_first("h3 a")
    assert title_link.attributes["href"] == "/events/prairie-python-november-2026-11-10/"
    detail = site / "events" / "prairie-python-november-2026-11-10" / "index.html"
    page = detail.read_text(encoding="utf-8")
    assert "Prairie Python November" in page
    assert "View and register on www.meetup.com" in page


def test_unpublished_hidden_and_past_events_have_no_pages(site: Path) -> None:
    pages = html_files(site)
    all_text = " ".join(pages.values())
    for title in ("Waiting for review", "Hidden by admin"):
        assert title not in all_text
    assert not (site / "events" / "waiting-2026-10-31").exists()
    assert "Already happened" not in (site / "index.html").read_text(encoding="utf-8")


def test_no_calendar_downloads_invites_or_rsvp(site: Path) -> None:
    for name, page in html_files(site).items():
        lowered = page.lower()
        for forbidden in (".ics", "webcal:", "rsvp", "invite", "add to calendar", "remind me"):
            assert forbidden not in lowered, (name, forbidden)


def test_about_page_exists_and_names_the_bot(site: Path) -> None:
    about = (site / "about" / "index.html").read_text(encoding="utf-8")
    assert "NETechConnectBot" in about
    assert "robots.txt" in about


def test_not_found_page_exists_and_links_home(site: Path) -> None:
    # Cloudflare Pages answers unknown paths with index.html and a 200 unless 404.html exists.
    page = LexborHTMLParser((site / "404.html").read_text(encoding="utf-8"))
    heading, stylesheet = page.css_first("h1"), page.css_first('link[rel="stylesheet"]')
    assert heading is not None
    assert "not found" in heading.text().lower()
    assert any(a.attributes.get("href") == "/" for a in page.css("main a"))
    # Root-relative, because this page is served at whatever path was requested.
    assert stylesheet is not None
    assert stylesheet.attributes["href"] == "/css/site.css"


def test_empty_data_says_no_events_found(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", [])
    out = tmp_path / "dist"
    assert build(data, out) == 0
    assert "No events found" in (out / "index.html").read_text(encoding="utf-8")


def test_public_data_files_hold_public_fields_only(site: Path) -> None:
    upcoming = json.loads((site / "data" / "upcoming.json").read_text(encoding="utf-8"))
    assert [e["title"] for e in upcoming] == [
        "Prairie Python November", "Remote Rust night", "Cancelled CTF", "Prairie Python December",
    ]  # fmt: skip
    for record in upcoming:
        assert set(record) == PUBLIC_FIELDS
    assert upcoming[0]["organizer"] == "Prairie Python"
    meta = json.loads((site / "data" / "meta.json").read_text(encoding="utf-8"))
    assert meta["categories"][0]["id"] == "ai-ml"
    assert {a["id"] for a in meta["areas"]} == {"omaha", "lincoln", "other_ne", "online"}
    assert meta["generated_at"] == "2026-10-18T12:00:00Z"


def test_web_assets_are_copied_but_not_tooling(site: Path) -> None:
    assert (site / "css" / "site.css").exists()
    assert (site / "_headers").exists()
    for tooling in ("package.json", "eslint.config.js", "node_modules", "tests"):
        assert not (site / tooling).exists()


def test_building_twice_gives_identical_output(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", events())
    first, second = tmp_path / "a", tmp_path / "b"
    build(data, first)
    build(data, second)

    def read(root: Path) -> dict[Path, bytes]:
        return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    assert read(first) == read(second)


def test_an_override_takes_effect_at_the_next_build(tmp_path: Path) -> None:
    # An override merged by PR applies at deploy, without waiting for a discovery run.
    listed = events()
    shown = next(e for e in listed if e.title == "Prairie Python November")
    data = make_data(tmp_path / "data", listed)
    DataStore(data).write_overrides([make_override(shown.id, reason="duplicate listing")])
    out = tmp_path / "dist"
    assert build(data, out) == 0
    assert "Prairie Python November" not in (out / "index.html").read_text(encoding="utf-8")
    assert not (out / "events" / shown.slug).exists()


def test_removing_the_override_shows_the_event_again(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", events())
    out = tmp_path / "dist"
    assert build(data, out) == 0
    assert "Hidden by admin" in (out / "index.html").read_text(encoding="utf-8")


# --- Design direction B (T151; research R15)


def home(out: Path) -> Any:
    return LexborHTMLParser((out / "index.html").read_text(encoding="utf-8"))


def flat(node: Any) -> str:
    return " ".join(node.text(separator=" ").split())


def test_the_hero_has_the_headline_and_real_counts(site: Path) -> None:
    page = home(site)
    hero = page.css_first(".home-hero")
    assert flat(hero.css_first("h1")) == "Every Nebraska tech event, in one place."
    counts = {flat(c.css_first(".count-label")): flat(c.css_first(".count-n"))
              for c in hero.css(".count")}  # fmt: skip
    assert counts["upcoming events"] == str(len(cards(site)))
    assert counts["groups and calendars watched"] == "1"  # make_data's one active source
    cta = hero.css_first("a.hero-cta")
    assert cta.attributes["href"] == "#events"
    assert page.css_first("#events") is not None


def test_the_map_legend_waits_for_the_3d_map(site: Path) -> None:
    legend = home(site).css_first("[data-map-legend]")
    assert "hidden" in legend.attributes


def test_events_are_grouped_by_month_in_central_time(site: Path) -> None:
    months = home(site).css("section.month")
    assert [flat(m.css_first("h2 .month-name")) for m in months] == [
        "November 2026",
        "December 2026",
    ]
    assert [flat(m.css_first("h2 .month-count")) for m in months] == ["3 events", "1 event"]
    assert [len(m.css("article.event")) for m in months] == [3, 1]


def test_each_card_has_a_date_block_hidden_from_screen_readers(site: Path) -> None:
    block = cards(site)[0].css_first(".date-block")
    assert block.attributes["aria-hidden"] == "true"
    assert flat(block) == "NOV 10 Tue"


def test_the_filter_bar_is_markup_only_until_its_script_exists(site: Path) -> None:
    bar = home(site).css_first("[data-filters]")
    assert "hidden" in bar.attributes  # shown by filters.js in Phase 6
    areas = [flat(b) for b in bar.css("button[aria-pressed]")]
    assert areas == ["All areas", "Omaha area", "Lincoln area", "Other Nebraska", "Online"]
    select = bar.css_first("select")
    assert bar.css_first(f"label[for='{select.attributes['id']}']") is not None
    assert flat(select.css_first("option")) == "All topics"


def test_nav_links_only_go_to_pages_that_exist(site: Path) -> None:
    for name, page in html_files(site).items():
        tree = LexborHTMLParser(page)
        for link in tree.css("header a, footer a"):
            href = link.attributes.get("href") or ""
            if href.startswith("/"):
                path = href.split("#")[0].rstrip("/")
                assert (site / path.lstrip("/") / "index.html").exists() or path == "", (name, href)


def test_the_footer_links_to_about_and_the_source(site: Path) -> None:
    footer = home(site).css_first("footer nav")
    links = {flat(a): a.attributes["href"] for a in footer.css("a")}
    assert links["About"] == "/about/"
    assert links["Source on GitHub"].startswith("https://github.com/")


def test_the_site_has_a_favicon(site: Path) -> None:
    # Browsers ask for /favicon.ico on every page; without it each page logs a 404 (T155).
    icon = (site / "favicon.ico").read_bytes()
    assert icon[:4] == b"\x00\x00\x01\x00"  # ICO header
    assert len(icon) <= 4 * 1024
