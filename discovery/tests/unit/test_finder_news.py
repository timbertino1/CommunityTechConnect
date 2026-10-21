"""The news finder: local tech news and blog feeds become event mentions (T088; research R6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from netc.fetch import FixtureHttp
from netc.finders.base import FinderContext
from netc.finders.news import MAX_ARTICLE_AGE_DAYS, NewsFinder
from netc.models import AreaConfig
from netc.storage import DataStore
from tests.ai_support import NOW, ScriptedClient, ai

pytestmark = pytest.mark.unit

REPO = DataStore(Path(__file__).resolve().parents[3] / "data")
AREAS: AreaConfig = REPO.read_areas()  # type: ignore[assignment]
RSS = Path(__file__).resolve().parents[1] / "fixtures" / "finders" / "rss" / "local_news.xml"
FEED = "https://news.example.com/feed/"


def ctx(tmp_path: Path, client: ScriptedClient | None) -> FinderContext:
    index = {FEED: {"file": str(RSS), "content_type": "application/rss+xml"}}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    service = ai(tmp_path, client) if client is not None else None
    return FinderContext(
        now=NOW, areas=AREAS, http=FixtureHttp(tmp_path), ai=service, news_feeds=[FEED]
    )


CYBER = {
    "mentions": [
        {
            "title": "Cyber Night",
            "date_hint": "Nov 12",
            "place_hint": "The Mill",
            "organizer_hint": "Lincoln Security Collective",
            "links": ["https://lincolnsec.example.org/events"],
        }
    ]
}


def test_articles_are_read_for_event_mentions(tmp_path: Path) -> None:
    client = ScriptedClient(CYBER, {"mentions": []})
    result = NewsFinder().run(ctx(tmp_path, client))
    assert len(client.calls) == 2  # the two recent articles
    titles = {m.title for m in result.mentions}
    assert "Cyber Night" in titles
    cyber = next(m for m in result.mentions if m.title == "Cyber Night")
    assert cyber.channel == "news" and cyber.links == ["https://lincolnsec.example.org/events"]
    assert result.stats["articles"] == 2


def test_event_items_in_a_feed_become_mentions_without_ai(tmp_path: Path) -> None:
    result = NewsFinder().run(ctx(tmp_path, None))
    [streaming] = result.mentions
    assert streaming.title == "Omaha Data Engineers: Streaming Night"
    assert streaming.date_hint == "Nov 10, 2026"
    assert streaming.links == ["https://news.example.com/events/streaming-night"]
    assert result.stats["skipped_no_ai"] == 2


def test_old_articles_are_left_alone(tmp_path: Path) -> None:
    client = ScriptedClient()
    later = ctx(tmp_path, client)
    later.now = NOW.replace(month=12)  # every article is now months old
    NewsFinder().run(later)
    assert client.calls == []
    assert MAX_ARTICLE_AGE_DAYS == 21


def test_an_unreadable_feed_is_counted(tmp_path: Path) -> None:
    context = ctx(tmp_path, None)
    context.news_feeds = ["https://gone.example.org/feed/"]
    result = NewsFinder().run(context)
    assert result.stats["errors"] == 1 and result.mentions == []


def test_ai_answers_without_usable_mentions_are_counted(tmp_path: Path) -> None:
    client = ScriptedClient({"mentions": [{"title": "x", "trust": "trusted"}]}, None)
    result = NewsFinder().run(ctx(tmp_path, client))
    assert result.stats["ai_unusable"] == 2
