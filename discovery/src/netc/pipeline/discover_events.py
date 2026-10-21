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
from netc.models import Event, Source
from netc.pipeline.ai import Ai
from netc.pipeline.classify import ClassifyInput, classify
from netc.pipeline.dedupe import deduplicate
from netc.pipeline.lifecycle import Incoming, apply_run
from netc.pipeline.normalize import Dropped, normalize, to_event
from netc.pipeline.overrides import apply_overrides
from netc.pipeline.runner import LogSink, SourceOutcome, run_sources, stderr_sink
from netc.pipeline.sanitize import to_plain_text
from netc.storage import DataStore

UNDECIDED_CATEGORY = "general-tech"


@dataclass
class SourceRow:
    """How one source did in this run (for the run report)."""

    source: Source
    outcome: SourceOutcome
    previous_failures: int = 0
    listings: Counter[str] = field(default_factory=Counter)


@dataclass
class EventChange:
    """An event this run added, held for review, or changed (for the run report)."""

    kind: str
    """"added" (published), "held" (waiting for review), or "updated"."""
    event: Event
    detail: str = ""
    """Why it is held, or which fields changed."""


@dataclass
class SetAside:
    """A listing that did not become an event: rejected as off-topic or dropped as unusable."""

    source_id: str
    title: str
    kind: str
    reason: str


@dataclass
class DiscoverReport:
    sources: dict[str, int] = field(default_factory=dict)
    """ok / failed / skipped counts."""
    listings: Counter[str] = field(default_factory=Counter)
    """What happened to each listing: kept, held, rejected, dropped."""
    events_total: int = 0
    new_reviews: int = 0
    written: bool = False
    now: datetime | None = None
    rows: list[SourceRow] = field(default_factory=list)
    changes: list[EventChange] = field(default_factory=list)
    set_aside: list[SetAside] = field(default_factory=list)
    ai_calls: int | None = None
    """AI calls made this run; None when the AI was off (no key, or an offline run)."""
    ai_spent_usd: float = 0.0
    """AI spend so far this month, this run included."""
    ai_unusable: int = 0
    ai_last_problem: str | None = None


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
    ai: Ai | None = None,
) -> DiscoverReport:
    sources = store.read_sources()
    by_id = {s.id: s for s in sources}
    categories = store.read_categories()
    areas = store.read_areas()
    if areas is None:
        raise RuntimeError("data/areas.yaml is required for discovery")

    extra = {} if clock is None else {"clock": clock}
    previous = store.read_source_status()
    run = run_sources(
        sources,
        connectors,
        http,
        previous,
        now=now,
        log=log,
        force=force,
        source_timeout_seconds=source_timeout_seconds,
        **extra,  # type: ignore[arg-type]
    )
    report = DiscoverReport(sources=run.metrics, now=now)
    refreshed = {o.source_id for o in run.outcomes if o.status == "ok"}

    built: list[Event] = []
    holds: dict[tuple[str, str], str] = {}
    for outcome in run.outcomes:
        source = by_id[outcome.source_id]
        before = previous.get(source.id)
        row = SourceRow(source, outcome, before.consecutive_failures if before else 0)
        report.rows.append(row)

        def tally(kind: str, title: str = "", reason: str = "", r: SourceRow = row) -> None:
            report.listings[kind] += 1
            r.listings[kind] += 1
            if kind in ("rejected", "dropped"):
                aside = SetAside(r.source.id, to_plain_text(title, 200), kind, reason)
                report.set_aside.append(aside)

        for raw in outcome.listings:
            item = normalize(raw, source, areas, now=now)
            if isinstance(item, Dropped):
                tally("dropped", raw.title, item.reason)
                continue
            verdict = classify(
                ClassifyInput.of(item, source.default_area), categories, areas, ai=ai
            )
            if verdict.relevant is False:
                tally("rejected", item.title, verdict.reason)
                continue
            area = item.area or verdict.area
            if area is None:
                tally("dropped", item.title, "no Nebraska area")
                continue
            event = to_event(
                item,
                categories=verdict.categories or [UNDECIDED_CATEGORY],
                review_state="pending_review",
                now=now,
                area=area,
                organizer_id=source.organizer_id,
            )
            if verdict.relevant is None:
                holds[(item.listing.source_id, item.listing.url)] = (
                    f"needs review: {verdict.reason}"
                )
                tally("held")
            else:
                tally("kept")
            built.append(event)

    incoming = [Incoming(event, _hold_for(event, holds)) for event in deduplicate(built)]
    stored = store.read_events()
    result = apply_run(
        stored,
        incoming,
        sources=by_id,
        refreshed_sources=refreshed,
        queue=store.read_review_queue(),
        now=now,
    )
    # Overrides last, so this run's fresh details don't undo the owner's corrections.
    events = apply_overrides(unique_slugs(result.events), store.read_overrides())
    report.events_total = len(events)
    report.new_reviews = len(result.new_reviews)
    report.changes = _changes(stored, events, {r.ref: r.reason for r in result.new_reviews})

    if not dry_run:
        store.write_events(events)
        store.write_source_status(run.statuses)
        if result.new_reviews:
            store.write_review_queue([*store.read_review_queue(), *result.new_reviews])
        if ai is not None:
            ai.cache.save()
        report.written = True
    if ai is not None and ai.client is not None:
        report.ai_calls = ai.calls
        report.ai_spent_usd = ai.cache.spent_usd()
        report.ai_unusable = ai.unusable
        report.ai_last_problem = ai.last_problem
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


def _changes(before: list[Event], after: list[Event], reasons: dict[str, str]) -> list[EventChange]:
    """What a reader of the run report wants to know: new events and real edits (not the
    routine last-verified refresh)."""
    old = {e.id: e for e in before}
    changes: list[EventChange] = []
    for event in after:
        was = old.get(event.id)
        if was is None:
            if event.review_state == "published":
                changes.append(EventChange("added", event))
            elif event.review_state == "pending_review":
                changes.append(EventChange("held", event, reasons.get(event.id, "")))
            continue
        changed = [
            label
            for label, a, b in (
                ("title", was.title, event.title),
                (
                    "time",
                    (was.start, was.end, was.all_day),
                    (event.start, event.end, event.all_day),
                ),
                ("place", was.location, event.location),
                ("status", was.status, event.status),
            )
            if a != b
        ]
        if changed:
            detail = ", ".join(changed)
            if "status" in changed:
                detail = detail.replace("status", f"status: {was.status} to {event.status}")
            changes.append(EventChange("updated", event, detail))
    return changes


def _hold_for(event: Event, holds: dict[tuple[str, str], str]) -> str | None:
    """Held only when every listing merged into the event was held."""
    reasons = [holds.get((listing.source_id, listing.url)) for listing in event.listings]
    return reasons[0] if reasons and all(reasons) else None
