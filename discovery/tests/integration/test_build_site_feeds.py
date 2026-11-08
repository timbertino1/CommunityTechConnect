"""`netc build-site` writes the event feeds and the feeds page (feature 002 T011, T013, T018,
T020; contracts/feeds.md)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import feedparser
import pytest
import yaml
from selectolax.lexbor import LexborHTMLParser

from netc.models import Event
from netc.site.build import build_site
from netc.storage import DataStore
from tests.data_samples import make_override, utc
from tests.site_support import NOW_DT, WEB, build, html_files, make_data, site_event

pytestmark = pytest.mark.integration

DOMAIN = "netechconnect.example"
SITE = f"https://{DOMAIN}"


def events() -> list[Event]:
    return [
        site_event(
            "https://prairiepython.example.org/dec",
            "Prairie Python December",
            utc(2026, 12, 8, 23, 30),
            "prairie-python-december-2026-12-08",
            categories=["software-dev", "ai-ml"],
            published_at=utc(2026, 10, 15),
        ),
        site_event(
            "https://www.meetup.com/prairie-python/events/1/",
            "Prairie Python November",
            utc(2026, 11, 10, 23, 30),
            "prairie-python-november-2026-11-10",
        ),
        site_event(
            "https://example.org/held",
            "Held talk",
            utc(2026, 11, 12, 23, 30),
            "held-talk-2026-11-12",
            review_state="pending_review",
        ),
        site_event(
            "https://example.org/rejected",
            "Rejected talk",
            utc(2026, 11, 13, 23, 30),
            "rejected-talk-2026-11-13",
            review_state="rejected",
        ),
        site_event(
            "https://example.org/past",
            "Past talk",
            utc(2026, 10, 1, 23, 30),
            "past-talk-2026-10-01",
            first_seen=utc(2026, 9, 1),
            last_verified=utc(2026, 9, 1),
        ),
        site_event(
            "https://example.org/hidden",
            "Hidden talk",
            utc(2026, 11, 14, 23, 30),
            "hidden-talk-2026-11-14",
        ),
    ]


def site(tmp_path: Path, now: Any = NOW_DT, data: Path | None = None, name: str = "out") -> Path:
    if data is None:
        data = make_data(tmp_path / "data", events())
        DataStore(data).write_overrides([make_override(events()[-1].id, reason="spam")])
    out = tmp_path / name
    build_site(data, out, WEB, now=now, site_domain=DOMAIN)
    return out


def parse(path: Path) -> Any:
    parsed = feedparser.parse(path.read_bytes())
    assert parsed.bozo == 0, parsed.get("bozo_exception")
    return parsed


def titles(parsed: Any) -> list[str]:
    return [e.title for e in parsed.entries]


def category_labels() -> dict[str, str]:
    path = Path(__file__).parents[3] / "data" / "categories.yaml"
    return {c["id"]: c["label"] for c in yaml.safe_load(path.read_text(encoding="utf-8"))}


def category_ids() -> list[str]:
    return list(category_labels())


# ---------------------------------------------------------------- US1: all events


def test_all_feed_lists_the_public_upcoming_events(tmp_path: Path) -> None:
    out = site(tmp_path)
    parsed = parse(out / "feeds" / "all.xml")
    assert titles(parsed) == ["Prairie Python December", "Prairie Python November"]
    upcoming = json.loads((out / "data" / "upcoming.json").read_text(encoding="utf-8"))
    ids = {e.id.rsplit("/", 1)[1] for e in parsed.entries}
    assert ids == {e["id"] for e in upcoming}


def test_feed_links_and_identity(tmp_path: Path) -> None:
    parsed = parse(site(tmp_path) / "feeds" / "all.xml")
    first = parsed.entries[0]
    assert first.link == "https://prairiepython.example.org/dec"
    assert any(
        link.rel == "related" and link.href == f"{SITE}/events/prairie-python-december-2026-12-08/"
        for link in first.links
    )
    assert first.author == "Prairie Python"
    assert any(link.href == f"{SITE}/feeds/all.xml" for link in parsed.feed.links)


def test_rebuilding_with_the_same_events_gives_the_same_bytes(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", events())
    one = site(tmp_path, now=NOW_DT, data=data, name="one")
    two = site(tmp_path, now=utc(2026, 10, 18, 23), data=data, name="two")
    for path in sorted((one / "feeds").glob("*.xml")):
        assert path.read_bytes() == (two / "feeds" / path.name).read_bytes(), path.name


def test_headers_give_feeds_their_content_type(tmp_path: Path) -> None:
    headers = (site(tmp_path) / "_headers").read_text(encoding="utf-8")
    assert re.search(
        r"^/feeds/\*\.xml\n  Content-Type: application/atom\+xml; charset=utf-8$",
        headers,
        re.MULTILINE,
    )


def test_the_cli_build_writes_feeds(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", events())
    assert build(data, tmp_path / "cli") == 0
    assert (tmp_path / "cli" / "feeds" / "all.xml").is_file()


# ---------------------------------------------------------------- US2: categories


def test_one_feed_per_category_and_no_others(tmp_path: Path) -> None:
    out = site(tmp_path)
    names = sorted(p.stem for p in (out / "feeds").glob("*.xml"))
    assert names == sorted(["all", *category_ids()])


def test_category_feeds_hold_only_their_events(tmp_path: Path) -> None:
    out = site(tmp_path)
    assert titles(parse(out / "feeds" / "ai-ml.xml")) == ["Prairie Python December"]
    assert titles(parse(out / "feeds" / "software-dev.xml")) == [
        "Prairie Python December",
        "Prairie Python November",
    ]
    security = parse(out / "feeds" / "security.xml")
    assert security.entries == []
    assert security.feed.title == f"NETechConnect: {category_labels()['security']}"


def test_a_new_category_gets_a_feed(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", events())
    path = data / "categories.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.append({"id": "quantum", "label": "Quantum", "keywords": ["quantum computing"]})
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    out = site(tmp_path, data=data)
    assert parse(out / "feeds" / "quantum.xml").feed.title == "NETechConnect: Quantum"


# ---------------------------------------------------------------- US3: finding the feeds


AUTODISCOVERY = (
    '<link rel="alternate" type="application/atom+xml" '
    'title="NETechConnect: all events" href="/feeds/all.xml">'
)


def test_every_page_advertises_the_all_events_feed_and_links_follow(tmp_path: Path) -> None:
    pages = html_files(site(tmp_path))
    assert "feeds/index.html" in pages
    for name, html in pages.items():
        assert html.count(AUTODISCOVERY) == 1, name
        footer = LexborHTMLParser(html).css_first("footer nav")
        assert footer is not None, name
        assert any(a.attributes.get("href") == "/feeds/" for a in footer.css("a")), name


def test_feeds_page_lists_every_feed_in_order(tmp_path: Path) -> None:
    html = html_files(site(tmp_path))["feeds/index.html"]
    tree = LexborHTMLParser(html)
    hrefs = [a.attributes.get("href") for a in tree.css("main .feed-list a")]
    assert hrefs == [f"{SITE}/feeds/all.xml"] + [f"{SITE}/feeds/{c}.xml" for c in category_ids()]
    head = [
        link.attributes.get("href")
        for link in tree.css('head link[rel="alternate"][type="application/atom+xml"]')
    ]
    assert head == ["/feeds/all.xml"] + [f"/feeds/{c}.xml" for c in category_ids()]
    footer_follow = tree.css_first('footer a[href="/feeds/"]')
    assert footer_follow is not None
    assert footer_follow.attributes.get("aria-current") == "page"


def test_home_page_has_a_follow_link_and_past_does_not(tmp_path: Path) -> None:
    pages = html_files(site(tmp_path))
    home = LexborHTMLParser(pages["index.html"]).css("main a")
    assert any(a.attributes.get("href") == "/feeds/" for a in home)
    past = LexborHTMLParser(pages["past/index.html"]).css("main a")
    assert not any(a.attributes.get("href") == "/feeds/" for a in past)
