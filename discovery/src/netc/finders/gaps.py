"""The gap finder (T089; research R7; FR-013).

Targeted searches for what the site expects but doesn't have: groups whose usual meetings
stopped (they may have moved to another site), annual events whose next edition isn't listed
about ten months after the last one, and known Nebraska groups with no working source
(searched at most monthly). Results become candidates (found via "gap") or mentions, like any
search result. At most MAX_GAP_QUERIES a run, so the weekly sweep keeps most of the budget.
"""

from __future__ import annotations

from datetime import timedelta
from typing import ClassVar, Final

from netc.finders.base import FinderContext, FinderResult, lead_from_result, merge_leads
from netc.pipeline.coverage import annual_series_due, quiet_sources
from netc.search.base import SearchBudgetExhaustedError, SearchError

MAX_GAP_QUERIES: Final = 15
RESEARCH_AFTER: Final = timedelta(days=30)
AREA_WORDS: Final = {"omaha": "Omaha", "lincoln": "Lincoln"}


class GapFinder:
    name: ClassVar[str] = "gap"

    def run(self, ctx: FinderContext) -> FinderResult:
        result = FinderResult()
        if ctx.search is None:
            result.stats["skipped_no_search"] += 1
            return result

        planned: list[tuple[str, str, str | None]] = []  # (why, query, known group name)
        for quiet in quiet_sources(ctx.sources, ctx.events, ctx.now):
            planned.append(("quiet group", f'"{quiet.source.name}" Nebraska events', None))
        for series in annual_series_due(ctx.events, ctx.now):
            planned.append(("annual event", f'"{series.title}" {series.last_event.year + 1}', None))
        working = {s.id for s in ctx.sources if s.status == "active"}
        for group in ctx.known_groups:
            if group.status != "active" or any(sid in working for sid in group.source_ids):
                continue
            if group.last_searched is not None and ctx.now - group.last_searched < RESEARCH_AFTER:
                continue
            place = AREA_WORDS.get(group.area or "", "Nebraska")
            planned.append(("known group with no source", f'"{group.name}" {place}', group.name))

        seen = ctx.known_keys()
        for why, query, group_name in planned[:MAX_GAP_QUERIES]:
            try:
                hits = ctx.search.search(query, count=5)
            except SearchBudgetExhaustedError:
                result.stats["budget_exhausted"] += 1
                break
            except SearchError:
                result.stats["errors"] += 1
                continue
            result.stats["queries"] += 1
            if group_name is not None:
                result.searched_groups[group_name] = ctx.now
            for hit in hits:
                lead = lead_from_result(
                    hit,
                    found_via="gap",
                    now=ctx.now,
                    areas=ctx.areas,
                    evidence=f"gap check: {why}: {query}",
                )
                merge_leads(result, lead, seen)
        return result
