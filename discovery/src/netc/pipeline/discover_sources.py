"""`netc discover-sources`: the weekly hunt for groups and events nobody told us about (T094;
research R6, R7; FR-010-FR-015).

0. Visitors' suggestions are read from KV (T133) and join the candidates first, so they are
   evaluated before anything a finder turns up.
1. Each finder runs in turn (web search, links on known pages, event platforms, news feeds,
   newsletters, coverage gaps). A
   finder that crashes is recorded and skipped; the others still run. Each one sees what the
   ones before it found, so nothing is found twice.
2. Mentions, new and old, are resolved to organizers' pages where possible (FR-014).
3. Candidates due a look are evaluated; relevant ones become probationary sources, whose events
   the next discover-events run collects and holds for review. No evaluation starts once the run
   has used its time budget (the job is stopped at 60 minutes, and a stopped job saves
   nothing); the rest wait for the next run.
4. Known groups record when they were last searched and gain the new sources.

Writes candidates.json, mentions.json, new source files, known_groups.yaml, the search usage,
the AI cache, and review items for suggestions it couldn't decide; nothing else. A suggestion's
note stays in memory. Newsletters and suggestions the run is done with are then deleted from KV,
so nothing is lost to a crash. In a dry run nothing is written or deleted. Each finder
and stage logs its time, and each evaluation its result, as JSON lines.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from netc.connectors.base import Connector
from netc.fetch import HttpClient
from netc.finders.base import Finder, FinderContext, site_key
from netc.finders.gaps import GapFinder
from netc.finders.link_graph import LinkGraphFinder
from netc.finders.news import NewsFinder
from netc.finders.newsletter import NewsletterFinder
from netc.finders.platform import PlatformFinder
from netc.finders.web_search import WebSearchFinder
from netc.inbox.kv import Inbox, InboxError
from netc.inbox.suggestions import read_suggestions
from netc.models import CandidateSource, KnownGroup, ReviewItem, Source
from netc.pipeline.ai import Ai
from netc.pipeline.evaluate import evaluate_candidates
from netc.pipeline.resolve import resolve_mentions
from netc.pipeline.runner import LogSink, stderr_sink
from netc.search.base import BudgetedSearch
from netc.storage import DataStore

RUN_TIME_BUDGET_SECONDS: Final = 40 * 60
"""Evaluations start only within this; the workflow's job timeout is 60 minutes."""
MENTIONS_BUDGET_SECONDS: Final = 10 * 60
"""Resolving mentions starts no new one after this, so evaluation always gets its turn."""


def default_finders(inbox: Inbox | None = None) -> list[Finder]:
    return [
        WebSearchFinder(),
        LinkGraphFinder(),
        PlatformFinder(),
        NewsFinder(),
        NewsletterFinder(inbox),
        GapFinder(),
    ]


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
    stopped_for_time: bool = False
    """The time budget ran out during evaluation; deferred candidates wait for the next run."""
    inbox_deleted: int = 0
    inbox_delete_errors: int = 0
    suggestions_read: int = 0
    suggestions_for_review: int = 0
    """Suggestions sent to the review queue: not a source page, or not decidable automatically."""
    suggestions_deleted: int = 0
    suggestions_error: str | None = None
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
    inbox: Inbox | None = None,
    suggestions: Inbox | None = None,
    dry_run: bool = False,
    log: LogSink = stderr_sink,
    time_budget_seconds: float = RUN_TIME_BUDGET_SECONDS,
    mentions_budget_seconds: float = MENTIONS_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> DiscoverSourcesReport:
    started = mark = clock()

    def stage_done(stage: str) -> None:
        nonlocal mark
        now_s = clock()
        log(json.dumps({"event": "stage_done", "stage": stage, "seconds": round(now_s - mark, 1)}))
        mark = now_s

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
    processed: list[str] = []

    suggested_done: list[str] = []
    set_aside_suggestions: list[tuple[str, str]] = []
    if suggestions is not None:
        try:
            read = read_suggestions(suggestions, now=now)
        except InboxError as exc:
            report.suggestions_error = str(exc)
            log(json.dumps({"event": "suggestions_failed", "error": type(exc).__name__}))
        else:
            report.suggestions_read = len(read.done)
            suggested_done = read.done
            set_aside_suggestions = [(s.url, s.reason) for s in read.for_review]
            _add_candidates(ctx, read.candidates, found)
    for finder in finders if finders is not None else default_finders(inbox):
        finder_started = clock()
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
        log(
            json.dumps(
                {
                    "event": "finder_done",
                    "finder": finder.name,
                    "seconds": round(clock() - finder_started, 1),
                }
            )
        )
        _add_candidates(ctx, result.candidates, found)
        for mention in result.mentions:
            if mention.id not in mentions:
                mentions[mention.id] = mention
                report.new_mentions += 1
        searched.update(result.searched_groups)
        processed += result.processed_messages

    stage_done("finders")

    mentions_started = clock()
    resolved = resolve_mentions(
        list(mentions.values()),
        http=http,
        now=now,
        search=search,
        events=events,
        should_stop=lambda: (
            clock() - mentions_started >= mentions_budget_seconds
            or clock() - started >= time_budget_seconds
        ),
        log=log,
        clock=clock,
    )
    report.mentions = resolved.counts
    _add_candidates(ctx, resolved.candidates, found)
    report.found = dict(found)
    stage_done("mentions")

    evaluation = evaluate_candidates(
        ctx.candidates,
        http=http,
        connectors=connectors,
        sources=sources,
        categories=store.read_categories(),
        areas=areas,
        now=now,
        ai=ai,
        should_stop=lambda: clock() - started >= time_budget_seconds,
        log=log,
        clock=clock,
    )
    stage_done("evaluation")
    report.evaluated = evaluation.counts
    report.stopped_for_time = evaluation.stopped_for_time
    report.added = evaluation.added
    # The evaluator returns a new object for each candidate it looked at.
    report.set_aside = [
        after
        for before, after in zip(ctx.candidates, evaluation.candidates, strict=True)
        if after is not before and after.result in ("rejected", "needs_review", "blocked_by_terms")
    ]
    groups = _update_groups(groups, searched, evaluation.added)
    undecided = set_aside_suggestions + [
        (c.url, c.reason)
        for c in report.set_aside
        if c.found_via == "suggestion" and c.result == "needs_review"
    ]
    queue = store.read_review_queue()
    queued = {r.id for r in queue}
    reviews: list[ReviewItem] = []
    for url, reason in undecided:
        review = ReviewItem(
            id=_suggestion_review_id(url),
            kind="suggestion",
            ref=url,
            reason=f"visitor suggestion: {reason}"[:280],
            created=now,
        )
        if review.id not in queued:
            queued.add(review.id)
            reviews.append(review)
    report.suggestions_for_review = len(reviews)

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
        if reviews:
            store.write_review_queue([*queue, *reviews])
        if search is not None:
            store.write_search_usage(search.usage)
        if ai is not None:
            ai.cache.save()
        report.written = True
        if inbox is not None:
            for key in processed:
                try:
                    inbox.delete(key)
                    report.inbox_deleted += 1
                except InboxError:
                    report.inbox_delete_errors += 1  # read again next run; the AI cache answers
        if suggestions is not None:
            for key in suggested_done:
                try:
                    suggestions.delete(key)
                    report.suggestions_deleted += 1
                except InboxError:
                    pass  # read again next run: the site is then known, so nothing is redone
    if ai is not None and ai.client is not None:
        report.ai_spent_usd = ai.cache.spent_usd()
    return report


def _suggestion_review_id(url: str) -> str:
    return "rev_" + hashlib.sha256(f"suggestion:{url}".encode()).hexdigest()[:12]


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
