"""The web search finder (T086; research R6).

Runs this week's topic x place queries (about 40) through the budgeted search. Each result is a
candidate site, a mention (a news or blog post), or nothing (social networks, platform pages,
other states). Sites already on file as sources or candidates are skipped.
"""

from __future__ import annotations

from typing import ClassVar

from netc.finders.base import FinderContext, FinderResult, lead_from_result, merge_leads
from netc.search.base import SearchBudgetExhaustedError, SearchError
from netc.search.queries import weekly_queries


class WebSearchFinder:
    name: ClassVar[str] = "web_search"

    def run(self, ctx: FinderContext) -> FinderResult:
        result = FinderResult()
        if ctx.search is None:
            result.stats["skipped_no_search"] += 1
            return result
        seen = ctx.known_keys()
        for query in weekly_queries(ctx.search.usage.last_run):
            try:
                hits = ctx.search.search(query, count=10)
            except SearchBudgetExhaustedError:
                result.stats["budget_exhausted"] += 1
                break
            except SearchError:
                result.stats["errors"] += 1
                continue
            result.stats["queries"] += 1
            result.stats["results"] += len(hits)
            for hit in hits:
                lead = lead_from_result(
                    hit,
                    found_via="web_search",
                    now=ctx.now,
                    evidence=f"web search: {query}",
                    areas=ctx.areas,
                )
                merge_leads(result, lead, seen)
        return result
