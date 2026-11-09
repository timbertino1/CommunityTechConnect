"""Source text can't become markup in a feed (feature 002 T012; research R9; contracts/feeds.md
rule 10). Event text is already validated as plain text by the model; these tests also bypass
that validation (``model_construct``) to prove the feed writer is safe on its own."""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

import feedparser
import pytest

from netc.models import Event
from netc.site.build import _view
from netc.site.feeds import atom_feed, entry_for
from tests.data_samples import make_event


def tree(data: bytes) -> ET.Element:
    """Parse a feed this build wrote (our own output, never fetched)."""
    return ET.fromstring(data)  # noqa: S314 - our own generated XML, not untrusted input


pytestmark = pytest.mark.security

SITE = "https://netechconnect.example"
ATOM = "{http://www.w3.org/2005/Atom}"
HOSTILE = [
    "<script>alert(1)</script>",
    "</summary><entry><title>Injected</title></entry>",
    "]]><evil/>",
    "Tom &amp; Jerry &lt;b&gt;",
    "\"quotes\" and 'apostrophes'",
    "<![CDATA[x]]>",
    "<?xml-stylesheet href='https://evil.example/x.xsl'?>",
    "&xxe; <!DOCTYPE x [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>",
]
FORBIDDEN = "a\x00b\x01c\x08d\x0be\x0cf\x1fg￾h￿i"
EXPECTED_CLEAN = "abcdefghi"


def unchecked(**fields: Any) -> Event:
    """An event built without validation, as if a check upstream had been missed."""
    base = make_event()
    return Event.model_construct(**{**base.__dict__, **fields})


def render(e: Event, organizer: str | None = "Org") -> tuple[bytes, Any]:
    view = _view(e, organizer, {"software-dev": "Software Development"}, {"omaha": "Omaha"})
    data = atom_feed(key="all", title="t", site_url=SITE, entries=[entry_for(e, view, SITE)])
    parsed = feedparser.parse(data)
    assert parsed.bozo == 0, parsed.get("bozo_exception")
    return data, parsed


def structure(data: bytes) -> list[str]:
    return [el.tag for el in tree(data).iter()]


@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_text_stays_literal_text(text: str) -> None:
    clean = render(unchecked(title="Talk"))[0]
    data, parsed = render(unchecked(title=text, summary=text), organizer=text)
    (item,) = parsed.entries
    assert item.title == text
    assert item.summary.endswith(text)
    assert item.author == text
    assert structure(data) == structure(clean)  # nothing injected
    assert b"<script" not in data and b"<evil" not in data and b"<!DOCTYPE" not in data


def test_characters_xml_forbids_are_removed() -> None:
    data, parsed = render(unchecked(title=FORBIDDEN, summary=FORBIDDEN), organizer=FORBIDDEN)
    tree(data)  # well-formed
    (item,) = parsed.entries
    assert item.title == EXPECTED_CLEAN
    assert item.author == EXPECTED_CLEAN
    assert item.summary.endswith(EXPECTED_CLEAN)


def test_lone_surrogates_are_removed() -> None:
    data, parsed = render(unchecked(title="a\ud800b"))
    assert parsed.entries[0].title == "ab"
    data.decode("utf-8")


def test_overlong_text_is_kept_whole_but_harmless() -> None:
    long = "<b>" * 2000
    _, parsed = render(unchecked(title="Talk", summary=long))
    assert parsed.entries[0].summary.endswith(long)


def test_links_are_only_the_original_page_and_the_site_page() -> None:
    e = make_event(url="https://organizer.example.org/e?utm=no")
    data, parsed = render(e)
    hrefs = [link.href for link in parsed.entries[0].links]
    assert hrefs[0] == e.original_url
    assert all(h.startswith("https://") for h in hrefs)
    assert b"javascript:" not in data


def test_category_labels_are_text_too() -> None:
    e = make_event(categories=["software-dev"])
    view = _view(e, None, {"software-dev": "<i>Dev</i> & Ops"}, {"omaha": "Omaha"})
    data = atom_feed(key="all", title="<b>t</b>", site_url=SITE, entries=[entry_for(e, view, SITE)])
    parsed = feedparser.parse(data)
    assert parsed.bozo == 0
    assert parsed.entries[0].tags[0].label == "<i>Dev</i> & Ops"
    assert parsed.feed.title == "<b>t</b>"
    assert tree(data).find(f"{ATOM}entry/{ATOM}category") is not None
