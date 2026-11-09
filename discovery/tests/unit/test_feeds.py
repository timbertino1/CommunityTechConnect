"""Atom feed entries and documents (feature 002 T010, T017; contracts/feeds.md, data-model.md)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import feedparser
import pytest

from netc.models import Event
from netc.site.build import _view
from netc.site.feeds import EMPTY_FEED_UPDATED, FEED_LIMIT, FeedEntry, atom_feed, entry_for
from tests.data_samples import make_event, utc

pytestmark = pytest.mark.unit

SITE = "https://netechconnect.example"
CATEGORIES = {"software-dev": "Software Development", "ai-ml": "AI & Machine Learning"}
AREAS = {"omaha": "Omaha"}


def event(n: int = 1, **overrides: Any) -> Event:
    data: dict[str, Any] = {
        "url": f"https://organizer.example.org/events/{n}",
        "slug": f"talk-{n}-2026-11-10",
        "title": f"Talk {n}",
        "start": utc(2026, 11, 10, 23, 30),
    }
    data.update(overrides)
    return make_event(**data)


def entry(e: Event, organizer: str | None = "Prairie Python") -> FeedEntry:
    return entry_for(e, _view(e, organizer, CATEGORIES, AREAS), SITE)


def feed(
    entries: list[FeedEntry], key: str = "all", title: str = "NETechConnect: all events"
) -> tuple[bytes, Any]:
    data = atom_feed(key=key, title=title, site_url=SITE, entries=entries)
    parsed = feedparser.parse(data)
    assert parsed.bozo == 0, parsed.get("bozo_exception")
    return data, parsed


# ---------------------------------------------------------------- entries


def test_entry_fields() -> None:
    e = event(categories=["software-dev", "ai-ml"])
    _, parsed = feed([entry(e)])
    (item,) = parsed.entries
    assert item.id == f"tag:netechconnect.com,2026:event/{e.id}"
    assert item.title == "Talk 1"
    assert item.link == "https://organizer.example.org/events/1"  # rel=alternate comes first
    links = {(link.rel, link.href) for link in item.links}
    assert ("related", f"{SITE}/events/talk-1-2026-11-10/") in links
    assert item.author == "Prairie Python"
    assert [(t.term, t.label) for t in item.tags] == [
        ("software-dev", "Software Development"),
        ("ai-ml", "AI & Machine Learning"),
    ]
    assert item.summary == (
        "Tue, Nov 10, 2026, 5:30 PM CT · AIM Institute, Omaha\n"
        "Organizer: Prairie Python\n\n"
        "Lightning talks and pizza."
    )


def test_entry_without_organizer_has_no_author_or_organizer_line() -> None:
    data, parsed = feed([entry(event(), organizer=None)])
    (item,) = parsed.entries
    assert "Organizer:" not in item.summary
    assert data.count(b"<author>") == 1  # the feed-level NETechConnect author only


def test_cancelled_events_say_so_in_the_title() -> None:
    _, parsed = feed([entry(event(status="cancelled"))])
    assert parsed.entries[0].title == "Cancelled: Talk 1"


def test_published_falls_back_to_first_seen() -> None:
    e = event(first_seen=utc(2026, 10, 10, 8))
    _, parsed = feed([entry(e)])
    assert parsed.entries[0].published == "2026-10-10T08:00:00Z"
    assert parsed.entries[0].updated == "2026-10-10T08:00:00Z"


def test_published_and_updated_from_the_timestamps() -> None:
    e = event(published_at=utc(2026, 10, 12), changed_at=utc(2026, 10, 15, 6))
    _, parsed = feed([entry(e)])
    assert parsed.entries[0].published == "2026-10-12T00:00:00Z"
    assert parsed.entries[0].updated == "2026-10-15T06:00:00Z"


def test_updated_never_before_published() -> None:
    """A change recorded before published_at existed (legacy event) can't predate first_seen."""
    e = event(first_seen=utc(2026, 10, 10), changed_at=utc(2026, 10, 9))
    assert entry(e).updated == utc(2026, 10, 10)


# ---------------------------------------------------------------- feed documents


def published(n: int, when: datetime) -> FeedEntry:
    return entry(event(n, published_at=when))


def test_newest_listed_first_then_by_id() -> None:
    a = published(1, utc(2026, 10, 12))
    b = published(2, utc(2026, 10, 14))
    c = published(3, utc(2026, 10, 14))
    _, parsed = feed([a, b, c])
    ids = [x.id.rsplit("/", 1)[1] for x in parsed.entries]
    assert ids[2] == a.event_id
    assert ids[:2] == sorted([b.event_id, c.event_id])


def test_at_most_feed_limit_entries_keeping_the_newest() -> None:
    start = utc(2026, 10, 11)
    entries = [published(n, start + timedelta(minutes=n)) for n in range(FEED_LIMIT + 5)]
    _, parsed = feed(entries)
    assert len(parsed.entries) == FEED_LIMIT
    kept = {x.id.rsplit("/", 1)[1] for x in parsed.entries}
    assert entries[0].event_id not in kept  # the oldest five drop
    assert entries[-1].event_id in kept


def test_feed_head() -> None:
    _, parsed = feed([published(1, utc(2026, 10, 12))])
    f = parsed.feed
    assert f.id == "tag:netechconnect.com,2026:feed/all"
    assert f.title == "NETechConnect: all events"
    assert f.author == "NETechConnect"
    links = {(link.rel, link.href) for link in f.links}
    assert ("self", f"{SITE}/feeds/all.xml") in links
    assert ("alternate", f"{SITE}/") in links
    assert f.updated == "2026-10-12T00:00:00Z"


def test_feed_updated_is_the_newest_entry_updated() -> None:
    a = entry(event(1, published_at=utc(2026, 10, 12), changed_at=utc(2026, 10, 20)))
    b = published(2, utc(2026, 10, 14))
    _, parsed = feed([a, b])
    assert parsed.feed.updated == "2026-10-20T00:00:00Z"


def test_empty_feed_is_valid_and_stable() -> None:
    data, parsed = feed([], key="security", title="NETechConnect: Security")
    assert parsed.entries == []
    assert parsed.feed.updated == EMPTY_FEED_UPDATED.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert parsed.feed.id == "tag:netechconnect.com,2026:feed/security"
    assert data == atom_feed(
        key="security", title="NETechConnect: Security", site_url=SITE, entries=[]
    )


def test_same_input_same_bytes() -> None:
    entries = [published(1, utc(2026, 10, 12)), published(2, utc(2026, 10, 13))]
    first = atom_feed(key="all", title="t", site_url=SITE, entries=entries)
    assert first == atom_feed(key="all", title="t", site_url=SITE, entries=list(reversed(entries)))


def test_text_constructs_are_plain_text_and_there_is_no_content() -> None:
    data, _ = feed([published(1, utc(2026, 10, 12))])
    assert b"<content" not in data
    assert b'type="html"' not in data and b'type="xhtml"' not in data
    for tag in (b"<title", b"<summary", b"<subtitle"):
        for chunk in data.split(tag)[1:]:
            assert chunk.startswith(b' type="text"'), chunk[:40]


# ---------------------------------------------------------------- category feeds (US2)


def test_category_feed_head() -> None:
    _, parsed = feed([], key="ai-ml", title="NETechConnect: AI & Machine Learning")
    assert parsed.feed.id == "tag:netechconnect.com,2026:feed/ai-ml"
    assert parsed.feed.title == "NETechConnect: AI & Machine Learning"
    assert any(link.href == f"{SITE}/feeds/ai-ml.xml" for link in parsed.feed.links)
