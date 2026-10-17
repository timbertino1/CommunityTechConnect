"""`netc discover-events`: one discovery run (T061; FR-002, FR-006, FR-007, FR-008, FR-016).

1. Read every due source through its connector (the runner isolates failures).
2. Normalize and classify each listing; rejected ones are dropped, undecided ones are held for
   review.
3. Merge duplicates found within the run, then apply the lifecycle rules to the stored events.
4. Write events, source health, and the review queue (unless ``dry_run``).

A broken source is recorded in its health and never fails the run.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from netc.connectors.base import Connector
from netc.fetch import HttpClient
from netc.models import Area, Event
from netc.pipeline.classify import ClassifyInput, classify
from netc.pipeline.dedupe import deduplicate
from netc.pipeline.lifecycle import Incoming, apply_run
from netc.pipeline.normalize import Dropped, Normalized, normalize, to_event
from netc.pipeline.runner import LogSink, run_sources, stderr_sink
from netc.storage import DataStore

UNDECIDED_CATEGORY = "general-tech"


@dataclass
class DiscoverReport:
    sources: dict[str, int] = field(default_factory=dict)
    """ok / failed / skipped counts."""
    listings: Counter[str] = field(default_factory=Counter)
    """What happened to each listing: kept, held, rejected, dropped."""
    events_total: int = 0
    new_reviews: int = 0
    written: bool = False


def discover_events(
    store: DataStore,
    http: HttpClient,
    connectors: Mapping[str, Connector],
    *,
    now: datetime,
    dry_run: bool = False,
    force: bool = False,
    log: LogSink = stderr_sink,
    source_timeout_seconds: float = 120.0,
    clock: Callable[[], float] | None = None,
) -> DiscoverReport:
    sources = store.read_sources()
    by_id = {s.id: s for s in sources}
    categories = store.read_categories()
    areas = store.read_areas()
    if areas is None:
        raise RuntimeError("data/areas.yaml is required for discovery")

    extra = {} if clock is None else {"clock": clock}
    run = run_sources(
        sources,
        connectors,
        http,
        store.read_source_status(),
        now=now,
        log=log,
        force=force,
        source_timeout_seconds=source_timeout_seconds,
        **extra,  # type: ignore[arg-type]
    )
    report = DiscoverReport(sources=run.metrics)
    refreshed = {o.source_id for o in run.outcomes if o.status == "ok"}

    built: list[Event] = []
    holds: dict[tuple[str, str], str] = {}
    for outcome in run.outcomes:
        source = by_id[outcome.source_id]
        for raw in outcome.listings:
            item = normalize(raw, source, areas, now=now)
            if isinstance(item, Dropped):
                report.listings["dropped"] += 1
                continue
            verdict = classify(_classify_input(item, source.default_area), categories, areas)
            if verdict.relevant is False:
                report.listings["rejected"] += 1
                continue
            area = item.area or verdict.area
            if area is None:
                report.listings["dropped"] += 1
                continue
            event = to_event(
                item,
                categories=verdict.categories or [UNDECIDED_CATEGORY],
                review_state="pending_review",
                now=now,
                area=area,
            )
            if verdict.relevant is None:
                holds[(item.listing.source_id, item.listing.url)] = (
                    f"needs review: {verdict.reason}"
                )
                report.listings["held"] += 1
            else:
                report.listings["kept"] += 1
            built.append(event)

    incoming = [Incoming(event, _hold_for(event, holds)) for event in deduplicate(built)]
    result = apply_run(
        store.read_events(),
        incoming,
        sources=by_id,
        refreshed_sources=refreshed,
        queue=store.read_review_queue(),
        now=now,
    )
    events = unique_slugs(result.events)
    report.events_total = len(events)
    report.new_reviews = len(result.new_reviews)

    if not dry_run:
        store.write_events(events)
        store.write_source_status(run.statuses)
        if result.new_reviews:
            store.write_review_queue([*store.read_review_queue(), *result.new_reviews])
        report.written = True
    return report


def unique_slugs(events: list[Event]) -> list[Event]:
    """Give every event a distinct slug: the earliest-seen keeps it, later ones get -2, -3..."""
    taken: set[str] = set()
    renamed: dict[str, Event] = {}
    for event in sorted(events, key=lambda e: (e.first_seen, e.id)):
        slug, n = event.slug, 2
        while slug in taken:
            suffix = f"-{n}"
            slug = event.slug[: 120 - len(suffix)] + suffix
            n += 1
        taken.add(slug)
        renamed[event.id] = event if slug == event.slug else event.model_copy(update={"slug": slug})
    return [renamed[e.id] for e in events]


def _classify_input(item: Normalized, source_area: Area | None) -> ClassifyInput:
    return ClassifyInput(
        title=item.title,
        summary=item.summary,
        organizer=item.organizer,
        area=item.area,
        online=item.location.online,
        source_area=source_area,
    )


def _hold_for(event: Event, holds: dict[tuple[str, str], str]) -> str | None:
    """Held only when every listing merged into the event was held."""
    reasons = [holds.get((listing.source_id, listing.url)) for listing in event.listings]
    return reasons[0] if reasons and all(reasons) else None
