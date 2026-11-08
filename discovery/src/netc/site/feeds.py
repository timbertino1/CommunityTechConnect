"""Atom feeds of public upcoming events (feature 002; specs/002-event-feeds/contracts/feeds.md).

Pure functions: the site build (``build.py``) picks the events and writes the bytes.

Every text construct is ``type="text"`` and the XML is written by ElementTree, never by a
template, so text from a source is escaped exactly once and can't become markup in a reader
(research R1, R3). Characters XML 1.0 forbids are dropped as a second line of defence; the
model already refuses them. Nothing here depends on the build time, so the same events give
the same bytes (SC-007).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from xml.etree import ElementTree as ET

from netc.models import Event

FEED_LIMIT: Final = 100
EMPTY_FEED_UPDATED: Final = datetime(2026, 11, 1, tzinfo=UTC)
"""A fixed time for a feed with no entries, so an empty feed is stable too."""
TAG: Final = "tag:netechconnect.com,2026:"
"""RFC 4151 ids: independent of the serving domain, so preview builds have the same ids."""
SUBTITLE: Final = "New community tech events in Nebraska. Each links to the organizer's own page."
ATOM_NS: Final = "http://www.w3.org/2005/Atom"

_NOT_XML = re.compile("[^\t\n\r -퟿-�\U00010000-\U0010ffff]")


@dataclass(frozen=True)
class FeedEntry:
    event_id: str
    title: str
    published: datetime
    updated: datetime
    original_url: str
    page_url: str
    author: str | None
    categories: tuple[tuple[str, str], ...]
    summary: str


def entry_for(event: Event, view: Mapping[str, Any], site_url: str) -> FeedEntry:
    """One event as a feed entry, using the same strings as its card on the site (``_view``)."""
    published = event.published_at or event.first_seen
    updated = max(published, event.changed_at) if event.changed_at else published
    title = f"Cancelled: {event.title}" if event.status == "cancelled" else event.title
    organizer: str | None = view["organizer"]
    lines = [f"{view['when']} · {view['where']}"]
    if organizer:
        lines.append(f"Organizer: {organizer}")
    summary = "\n".join(lines) + "\n\n" + event.summary
    return FeedEntry(
        event_id=event.id,
        title=title,
        published=published,
        updated=updated,
        original_url=event.original_url,
        page_url=f"{site_url}/events/{event.slug}/",
        author=organizer or None,
        categories=tuple(zip(event.categories, view["category_labels"], strict=True)),
        summary=summary,
    )


def atom_feed(*, key: str, title: str, site_url: str, entries: Sequence[FeedEntry]) -> bytes:
    """The feed at ``/feeds/<key>.xml``: newest-listed first, at most FEED_LIMIT entries."""
    chosen = sorted(entries, key=lambda e: e.event_id)
    chosen = sorted(chosen, key=lambda e: e.published, reverse=True)[:FEED_LIMIT]
    updated = max((e.updated for e in chosen), default=EMPTY_FEED_UPDATED)

    feed = ET.Element(_q("feed"))
    _text(feed, "id", f"{TAG}feed/{key}")
    _text(feed, "title", title, typed=True)
    _text(feed, "subtitle", SUBTITLE, typed=True)
    _text(feed, "updated", _when(updated))
    author = ET.SubElement(feed, _q("author"))
    _text(author, "name", "NETechConnect")
    _link(feed, "self", f"{site_url}/feeds/{key}.xml", "application/atom+xml")
    _link(feed, "alternate", f"{site_url}/", "text/html")
    for entry in chosen:
        el = ET.SubElement(feed, _q("entry"))
        _text(el, "id", f"{TAG}event/{entry.event_id}")
        _text(el, "title", entry.title, typed=True)
        _text(el, "published", _when(entry.published))
        _text(el, "updated", _when(entry.updated))
        _link(el, "alternate", entry.original_url, "text/html")
        _link(el, "related", entry.page_url, "text/html")
        if entry.author:
            _text(ET.SubElement(el, _q("author")), "name", entry.author)
        for term, label in entry.categories:
            ET.SubElement(el, _q("category"), {"term": _clean(term), "label": _clean(label)})
        _text(el, "summary", entry.summary, typed=True)

    ET.register_namespace("", ATOM_NS)
    tree = ET.ElementTree(feed)
    ET.indent(tree)
    data: bytes = ET.tostring(feed, encoding="utf-8", xml_declaration=True)
    return data + b"\n"


def _q(tag: str) -> str:
    return f"{{{ATOM_NS}}}{tag}"


def _text(parent: ET.Element, tag: str, value: str, *, typed: bool = False) -> None:
    el = ET.SubElement(parent, _q(tag), {"type": "text"} if typed else {})
    el.text = _clean(value)


def _link(parent: ET.Element, rel: str, href: str, media: str) -> None:
    ET.SubElement(parent, _q("link"), {"rel": rel, "type": media, "href": _clean(href)})


def _clean(value: str) -> str:
    """Drop what XML 1.0 can't carry (controls, U+FFFE/FFFF, lone surrogates)."""
    return _NOT_XML.sub("", value)


def _when(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
