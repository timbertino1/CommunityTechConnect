"""contracts/feeds.md rules on a built site (feature 002 T011): Atom only, plain text, no
tracking, stable identity, the 100-entry cap."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import feedparser
import pytest

from netc.site.build import build_site
from tests.data_samples import utc
from tests.site_support import NOW_DT, WEB, make_data, site_event


def tree(data: bytes) -> ET.Element:
    """Parse a feed this build wrote (our own output, never fetched)."""
    return ET.fromstring(data)  # noqa: S314 - our own generated XML, not untrusted input


pytestmark = pytest.mark.contract

ATOM_NS = "http://www.w3.org/2005/Atom"
DOMAIN = "netechconnect.example"


@pytest.fixture(scope="module")
def feeds(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    root = tmp_path_factory.mktemp("feeds")
    events = [
        site_event(
            f"https://organizer.example.org/e/{n}",
            f"Talk {n}",
            utc(2026, 11, 10, 23) + timedelta(days=n % 40),
            f"talk-{n}-2026-11-{10 + n % 15:02d}",
            published_at=utc(2026, 10, 11) + timedelta(minutes=n),
            categories=["software-dev"] if n % 2 else ["ai-ml"],
        )
        for n in range(120)
    ]
    out = root / "out"
    build_site(make_data(root / "data", events), out, WEB, now=NOW_DT, site_domain=DOMAIN)
    return {p.name: p.read_bytes() for p in sorted((out / "feeds").glob("*.xml"))}


def test_rule1_every_feed_parses_cleanly(feeds: dict[str, bytes]) -> None:
    for name, data in feeds.items():
        assert data.startswith(b"<?xml version='1.0' encoding='utf-8'?>"), name
        assert feedparser.parse(data).bozo == 0, name
        assert tree(data).tag == f"{{{ATOM_NS}}}feed", name


def test_rule2_only_atom_elements_and_plain_text(feeds: dict[str, bytes]) -> None:
    for name, data in feeds.items():
        for el in tree(data).iter():
            assert el.tag.startswith(f"{{{ATOM_NS}}}"), (name, el.tag)
            assert not el.tag.endswith("}content"), name
            if el.tag.rsplit("}", 1)[1] in ("title", "subtitle", "summary"):
                assert el.attrib.get("type") == "text", (name, el.tag)


def test_rule3_cap_and_order(feeds: dict[str, bytes]) -> None:
    entries = feedparser.parse(feeds["all.xml"]).entries
    assert len(entries) == 100
    published = [e.published for e in entries]
    assert published == sorted(published, reverse=True)
    assert entries[0].title == "Talk 119"


def test_rule4_ids_do_not_depend_on_the_domain(feeds: dict[str, bytes]) -> None:
    for e in feedparser.parse(feeds["all.xml"]).entries:
        assert e.id.startswith("tag:netechconnect.com,2026:event/evt_")


def test_rule9_no_query_strings_or_tracking(feeds: dict[str, bytes]) -> None:
    for name, data in feeds.items():
        for el in tree(data).iter(f"{{{ATOM_NS}}}link"):
            href = el.attrib["href"]
            assert urlsplit(href).scheme == "https", (name, href)
            assert not urlsplit(href).query, (name, href)


def test_rule5_original_page_first(feeds: dict[str, bytes]) -> None:
    for e in feedparser.parse(feeds["ai-ml.xml"]).entries:
        assert e.link.startswith("https://organizer.example.org/e/")


def test_feed_files_are_small(feeds: dict[str, bytes]) -> None:
    assert max(len(d) for d in feeds.values()) < 150_000


def test_contract_file_lists_these_paths() -> None:
    contract = Path(__file__).parents[3] / "specs" / "002-event-feeds" / "contracts" / "feeds.md"
    text = contract.read_text(encoding="utf-8")
    assert "/feeds/all.xml" in text and "/feeds/<category-id>.xml" in text
