"""The news and blog finder (T088; research R6).

Reads local tech news feeds (the list is in finders/config.yaml). Feed items that carry event
dates become mentions directly. Other recent articles go to the AI extractor, which lists the
specific upcoming events they mention; without the AI they are counted and left for a later run.
The AI's cache means an article is never sent twice, so re-reading a feed each week costs
nothing. Every mention waits to be resolved to the organizer's page (FR-014).
"""

from __future__ import annotations

from datetime import timedelta
from typing import ClassVar, Final

from netc.connectors.base import RawPayload
from netc.connectors.rss import RSS_CONTENT_TYPES, read_feed
from netc.fetch import FetchError
from netc.finders.base import FinderContext, FinderResult, make_mention
from netc.pipeline.extract import extract_mentions

MAX_ARTICLE_AGE_DAYS: Final = 21
MAX_ARTICLES_PER_FEED: Final = 30


class NewsFinder:
    name: ClassVar[str] = "news"

    def run(self, ctx: FinderContext) -> FinderResult:
        result = FinderResult()
        if ctx.http is None:
            result.stats["skipped_no_http"] += 1
            return result
        seen: set[str] = set()
        oldest = ctx.now - timedelta(days=MAX_ARTICLE_AGE_DAYS)
        for feed_url in ctx.news_feeds:
            try:
                response = ctx.http.get(feed_url, kind="feed", allowed_types=RSS_CONTENT_TYPES)
            except FetchError:
                result.stats["errors"] += 1
                continue
            if response.status >= 400:
                result.stats["errors"] += 1
                continue
            feed = read_feed(RawPayload.from_response(response, fetched_at=ctx.now))
            result.stats["feeds"] += 1

            for listing in feed.listings:
                when = listing.start
                hint = f"{when:%b} {when.day}, {when.year}"
                mention = make_mention(
                    listing.title,
                    [listing.url or ""],
                    channel="news",
                    date_hint=hint,
                    place_hint=listing.location_text,
                )
                if mention is not None and mention.id not in seen:
                    seen.add(mention.id)
                    result.mentions.append(mention)

            recent = [a for a in feed.articles if a.published is None or a.published >= oldest]
            for article in recent[:MAX_ARTICLES_PER_FEED]:
                result.stats["articles"] += 1
                if ctx.ai is None:
                    result.stats["skipped_no_ai"] += 1
                    continue
                text = f"{article.title}\n\n{article.summary}"
                found = extract_mentions(
                    text, [article.url, *article.links], ai=ctx.ai, channel="news"
                )
                if found is None:
                    result.stats["ai_unusable"] += 1
                    continue
                for mention in found:
                    if mention.id not in seen:
                        seen.add(mention.id)
                        result.mentions.append(mention)
        return result
