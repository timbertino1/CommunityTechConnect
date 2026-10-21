"""`netc discover-sources`: the weekly hunt for groups and events nobody told us about (T094;
research R6, R7; FR-010-FR-015).

1. Each finder runs in turn (web search, links on known pages, news feeds, coverage gaps). A
   finder that crashes is recorded and skipped; the others still run. Each one sees what the
   ones before it found, so nothing is found twice.
2. Mentions, new and old, are resolved to organizers' pages where possible (FR-014).
3. Candidates due a look are evaluated; relevant ones become probationary sources, whose events
   the next discover-events run collects and holds for review.
4. Known groups record when they were last searched and gain the new sources.

Writes candidates.json, mentions.json, new source files, known_groups.yaml, the search usage and
the AI cache; nothing else. In a dry run nothing is written.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from netc.connectors.base import Connector
from netc.fetch import HttpClient
from netc.finders.base import Finder, FinderContext, site_key
from netc.finders.gaps import GapFinder
from netc.finders.link_graph import LinkGraphFinder
from netc.finders.news import NewsFinder
from netc.finders.web_search import WebSearchFinder
from netc.models import CandidateSource, KnownGroup, Source
from netc.pipeline.ai import Ai
from netc.pipeline.evaluate import evaluate_candidates
from netc.pipeline.resolve import resolve_mentions
from netc.pipeline.runner import LogSink, stderr_sink
from netc.search.base import BudgetedSearch
from netc.storage import DataStore


def default_finders() -> list[Finder]:
    return [WebSearchFinder(), LinkGraphFinder(), NewsFinder(), GapFinder()]


@dataclass
class DiscoverSourcesReport:
    now: datetime
    finders: dict[str, Counter[str]] = field(default_factory=dict)
    finder_errors: dict[str, str] = field(default_factory=dict)
    found: dict[str, int] = field(default_factory=dict)
    """New candidates by channel."""
    new_mentions: int = 0
    mentions: Counter[str] = field(default_factory=Counter)
    evaluated: Counter[str] = field(default_factory=Counter)
    added: list[Source] = field(default_factory=list)
    set_aside: list[CandidateSource] = field(default_factory=list)
    """Candidates evaluated this run and not added (rejected, needs review, blocked)."""
    searches_used: int | None = None
    searches_left: int | None = None
    ai_calls: int | None = None
    ai_spent_usd: float = 0.0
    written: bool = False


def discover_sources(
    store: DataStore,
    http: HttpClient,
    connectors: Mapping[str, Connector],
    *,
    now: datetime,
    search: BudgetedSearch | None = None,
    ai: Ai | None = None,
    news_feeds: Sequence[str] = (),
    finders: Sequence[Finder] | None = None,
    dry_run: bool = False,
    log: LogSink = stderr_sink,
) -> DiscoverSourcesReport:
    areas = store.read_areas()
    if areas is None:
        raise RuntimeError("data/areas.yaml is required for discovery")
    sources = store.read_sources()
    candidates = store.read_candidates()
    mentions = {m.id: m for m in store.read_mentions()}
    groups = store.read_known_groups()
    events = store.read_events()
    report = DiscoverSourcesReport(now=now)
    used_before = search.usage.used if search else 0

    ctx = FinderContext(
        now=now,
        areas=areas,
        http=http,
        search=search,
        ai=ai,
        sources=sources,
        candidates=list(candidates),
        known_groups=groups,
        organizers=store.read_organizers(),
        events=events,
        news_feeds=list(news_feeds),
    )
    searched: dict[str, datetime] = {}
    found: Counter[str] = Counter()
    for finder in finders if finders is not None else default_finders():
        try:
            result = finder.run(ctx)
        except Exception as exc:  # one broken finder must not stop the hunt
            report.finder_errors[finder.name] = type(exc).__name__
            log(
                json.dumps(
                    {"event": "finder_failed", "finder": finder.name, "error": type(exc).__name__}
                )
            )
            continue
        report.finders[finder.name] = result.stats
        _add_candidates(ctx, result.candidates, found)
        for mention in result.mentions:
            if mention.id not in mentions:
                mentions[mention.id] = mention
                report.new_mentions += 1
        searched.update(result.searched_groups)

    resolved = resolve_mentions(
        list(mentions.values()), http=http, now=now, search=search, events=events
    )
    report.mentions = resolved.counts
    _add_candidates(ctx, resolved.candidates, found)
    report.found = dict(found)

    evaluation = evaluate_candidates(
        ctx.candidates,
        http=http,
        connectors=connectors,
        sources=sources,
        categories=store.read_categories(),
        areas=areas,
        now=now,
        ai=ai,
    )
    report.evaluated = evaluation.counts
    report.added = evaluation.added
    # The evaluator returns a new object for each candidate it looked at.
    report.set_aside = [
        after
        for before, after in zip(ctx.candidates, evaluation.candidates, strict=True)
        if after is not before and after.result in ("rejected", "needs_review", "blocked_by_terms")
    ]
    groups = _update_groups(groups, searched, evaluation.added)

    if search is not None:
        report.searches_used = search.usage.used - used_before
        report.searches_left = search.remaining
    if ai is not None and ai.client is not None:
        report.ai_calls = ai.calls

    if not dry_run:
        store.write_candidates(evaluation.candidates)
        store.write_mentions(resolved.mentions)
        for source in evaluation.added:
            store.write_source(source)
        store.write_known_groups(groups)
        if search is not None:
            store.write_search_usage(search.usage)
        if ai is not None:
            ai.cache.save()
        report.written = True
    if ai is not None and ai.client is not None:
        report.ai_spent_usd = ai.cache.spent_usd()
    return report


def _add_candidates(
    ctx: FinderContext, new: Sequence[CandidateSource], found: Counter[str]
) -> None:
    known = ctx.known_keys()
    for candidate in new:
        key = site_key(candidate.url)
        if key is None or key in known:
            continue
        known.add(key)
        ctx.candidates.append(candidate)
        found[candidate.found_via] += 1


def _update_groups(
    groups: list[KnownGroup], searched: Mapping[str, datetime], added: Sequence[Source]
) -> list[KnownGroup]:
    updated = [
        g.model_copy(update={"last_searched": searched[g.name]}) if g.name in searched else g
        for g in groups
    ]
    for source in added:
        names = {source.name.casefold()}
        match = next(
            (
                i
                for i, g in enumerate(updated)
                if names & {g.name.casefold(), *(a.casefold() for a in g.aliases)}
            ),
            None,
        )
        if match is None:
            updated.append(
                KnownGroup(
                    name=source.name,
                    area=source.default_area,
                    links=[source.url],
                    source_ids=[source.id],
                )
            )
            continue
        group = updated[match]
        updated[match] = group.model_copy(
            update={
                "source_ids": list(dict.fromkeys([*group.source_ids, source.id])),
                "links": list(dict.fromkeys([*group.links, source.url])),
            }
        )
    return updated
