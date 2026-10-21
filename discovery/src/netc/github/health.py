"""The Discovery health issue (T124; contracts/workflows-and-review.md, "Health issue").

One pinned issue whose description the bot rewrites after every run: a table of every source
(FR-042), then failing sources, items waiting for review, quiet groups, unresolved mentions,
new sources, AI and search spend, and whether the schedule is keeping main up to date.

Issue edits don't notify anyone, so when something needs the owner the bot also posts a
comment mentioning them (FR-044): at most one a day, and the same unresolved problem is
repeated only once a week. Each comment ends with a hidden marker listing what it was about,
which is how the next run knows what has already been reported.

Like the run report, this is posted on a public repository: source names are shown as plain
text with mentions and links broken, and errors (which can quote other sites) as code spans.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from netc.github.markdown import code_span, plain_name
from netc.github.review_pr import pending_items
from netc.models import CandidateSource, Event, EventMention, ReviewItem, Source, SourceStatus
from netc.pipeline.ai import MONTHLY_BUDGET_USD
from netc.pipeline.coverage import quiet_sources
from netc.pipeline.timeutil import format_central

HEALTH_TITLE: Final = "Discovery health"
ALERT_AFTER_FAILURES: Final = 2
"""Runs are twice daily, so this is about a day of failing; one failure is often a blip."""
STALE_AFTER: Final = timedelta(hours=36)
"""Main's data older than this means the data PRs aren't merging (or runs aren't happening)."""
MIN_ALERT_GAP: Final = timedelta(hours=20)
REMIND_AFTER: Final = timedelta(days=7)
MAX_LISTED: Final = 25
MAX_BODY_CHARS: Final = 60_000
"""GitHub caps an issue description at 65,536 characters."""

CENTRAL: Final = ZoneInfo("America/Chicago")
_LOGIN: Final = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_MARKER: Final = re.compile(r"<!-- netc-health-alert: ([a-z0-9:_ -]*) -->")
_KEY: Final = re.compile(r"^(?:review|schedule|ai-budget|failing:src_[a-z0-9-]+)$")

ORIGIN_LABELS: Final = {
    "preconfigured": "pre-configured",
    "admin": "added by the owner",
    "suggested": "suggested by a visitor",
}
FOUND_VIA_LABELS: Final = {
    "web_search": "web search",
    "link_graph": "linked from a source",
    "newsletter": "newsletter",
    "news": "news",
    "platform": "event platform",
    "gap": "gap check",
    "suggestion": "visitor suggestion",
}
STATUS_LABELS: Final = {
    "active": "active",
    "paused": "paused",
    "blocked_by_terms": "blocked by terms",
}


@dataclass(frozen=True)
class Attention:
    key: str
    """Stable id of the problem, e.g. ``failing:src_unl-computing``; kept in the alert marker."""
    text: str


@dataclass(frozen=True)
class Health:
    body: str
    attention: list[Attention]


@dataclass(frozen=True)
class LastAlert:
    posted: datetime
    body: str


def build_health(
    sources: Iterable[Source],
    statuses: Mapping[str, SourceStatus],
    events: Iterable[Event],
    queue: Iterable[ReviewItem],
    mentions: Iterable[EventMention],
    *,
    now: datetime,
    previous_status: Mapping[str, SourceStatus] | None = None,
    ai_spent_usd: float | None = None,
    candidates: Iterable[CandidateSource] = (),
) -> Health:
    """The issue description after a run. ``previous_status`` is main's source status from
    before the run, used to tell whether earlier runs' data reached main. ``ai_spent_usd`` is
    this month's AI spend, or None when the AI hasn't been used yet."""
    ordered = sorted(sources, key=lambda s: (s.name.casefold(), s.id))
    events = list(events)
    attention: list[Attention] = []

    failing_lines = []
    for source in ordered:
        status = statuses.get(source.id)
        if source.status != "active" or status is None or status.consecutive_failures == 0:
            continue
        n = status.consecutive_failures
        error = code_span(status.last_error or "unknown error")
        failing_lines.append(
            f"- **{plain_name(source.name)}** ({_failures(n)}, {_last_worked(status)}): {error}"
        )
        if n >= ALERT_AFTER_FAILURES:
            attention.append(
                Attention(
                    f"failing:{source.id}",
                    f"**{plain_name(source.name)}** has failed {n} runs in a row: {error}",
                )
            )

    waiting = pending_items(queue, events, now=now)
    if waiting:
        noun = "1 item is" if len(waiting) == 1 else f"{len(waiting)} items are"
        review_text = f"{noun} waiting in the review PR (branch `review/open`)."
        attention.append(Attention("review", review_text))
    else:
        review_text = "Nothing is waiting."

    schedule_lines, stale = _schedule(statuses, previous_status, now)
    if stale is not None:
        attention.append(Attention("schedule", stale))
    if ai_spent_usd is not None and ai_spent_usd >= MONTHLY_BUDGET_USD:
        attention.append(
            Attention(
                "ai-budget",
                f"This month's AI budget (${MONTHLY_BUDGET_USD:.2f}) is spent, so undecided "
                "events go to review until next month.",
            )
        )

    lines = [f"## {HEALTH_TITLE} · {_when(now)}", ""]
    if attention:
        lines += ["**Needs attention:**", ""] + [f"- {a.text}" for a in attention]
    else:
        lines.append("✅ **Nothing needs attention.**")
    lines += [
        "",
        "The discovery bot rewrites this description after every run, so edits here are lost. "
        "When something needs you, it adds a comment.",
        "",
        "### Sources",
        "",
        "| Source | Status | Trust | How found | Last successful check | Events found last run "
        "| Failures in a row |",
        "|---|---|---|---|---|--:|--:|",
    ]
    lines += [_source_row(s, statuses.get(s.id)) for s in ordered]
    lines += ["", "### Failing sources", "", *(_capped(failing_lines) or ["None."])]
    lines += ["", "### Waiting for review", "", review_text]
    lines += ["", "### Quiet groups", "", *(_capped(_quiet(ordered, events, now)) or ["None."])]
    lines += ["", "### Unresolved mentions", "", _mentions(mentions)]
    lines += ["", "### New sources this week", "", _new_sources(ordered, now)]
    lines += ["", "### Candidates needing a look", "", _needs_look(candidates)]
    lines += ["", "### AI and search spend", "", *_spend(ai_spent_usd)]
    lines += ["", "### Schedule", "", *schedule_lines]

    body = "\n".join(lines) + "\n"
    if len(body) > MAX_BODY_CHARS:
        body = body[: MAX_BODY_CHARS - 40].rsplit("\n", 1)[0] + "\n\n*(Shortened.)*\n"
    return Health(body, attention)


def alert_comment(
    health: Health, *, owner: str, last: LastAlert | None, now: datetime
) -> str | None:
    """The comment to post now, or None. At most one a day; a problem already reported is
    repeated only after REMIND_AFTER."""
    if not _LOGIN.match(owner):
        raise ValueError(f"owner must be a GitHub login, got {owner!r}")
    keys = {a.key for a in health.attention}
    if not keys:
        return None
    if last is not None:
        age = now - last.posted
        if age < MIN_ALERT_GAP:
            return None
        if keys <= _reported(last.body) and age < REMIND_AFTER:
            return None
    lines = [f"@{owner} the discovery bot needs your attention:", ""]
    lines += [f"- {a.text}" for a in health.attention]
    lines += [
        "",
        "Details are in the description above.",
        "",
        f"<!-- netc-health-alert: {' '.join(sorted(keys))} -->",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- helpers


def _reported(body: str) -> set[str]:
    match = _MARKER.search(body)
    if match is None:
        return set()
    return {k for k in match.group(1).split() if _KEY.match(k)}


def _source_row(source: Source, status: SourceStatus | None) -> str:
    success = _when(status.last_success) if status and status.last_success else "never"
    found = status.events_found_last_run if status else None
    failures = status.consecutive_failures if status else 0
    return (
        f"| {plain_name(source.name)} | {STATUS_LABELS[source.status]} | {source.trust} "
        f"| {_how_found(source)} | {success} | {'-' if found is None else found} | {failures} |"
    )


def _how_found(source: Source) -> str:
    if source.origin == "discovered":
        via = FOUND_VIA_LABELS.get(source.found_via or "", "")
        return f"discovered ({via})" if via else "discovered"
    return ORIGIN_LABELS[source.origin]


def _failures(n: int) -> str:
    return "first failure" if n == 1 else f"{n} runs in a row"


def _last_worked(status: SourceStatus) -> str:
    if status.last_success is None:
        return "never succeeded"
    return f"last worked {_day(status.last_success)}"


def _quiet(sources: list[Source], events: list[Event], now: datetime) -> list[str]:
    """Groups that went quiet (pipeline.coverage); the gap finder searches for them weekly."""
    return [
        f"- **{plain_name(q.source.name)}**: last event {_day(q.last_event)}; "
        f"usually every {_days(q.usual_gap)}."
        for q in quiet_sources(sources, events, now)
    ]


def _mentions(mentions: Iterable[EventMention]) -> str:
    unresolved = [m for m in mentions if m.resolution == "unresolved"]
    if not unresolved:
        return "None."
    noun = "1 mention" if len(unresolved) == 1 else f"{len(unresolved)} mentions"
    items = [f"- {code_span(m.title)} ({m.channel.replace('_', ' ')})" for m in unresolved]
    return f"{noun} not yet matched to an event:\n\n" + "\n".join(_capped(items))


def _new_sources(sources: list[Source], now: datetime) -> str:
    since = now.astimezone(CENTRAL).date() - timedelta(days=7)
    counts = Counter(_how_found(s) for s in sources if s.added_at > since)
    if not counts:
        return "None."
    return "\n".join(f"- {label}: {counts[label]}" for label in sorted(counts))


def _schedule(
    statuses: Mapping[str, SourceStatus],
    previous: Mapping[str, SourceStatus] | None,
    now: datetime,
) -> tuple[list[str], str | None]:
    lines = [
        f"This run: {_when(now)}. Runs are scheduled at 11:00 and 23:00 UTC, and each one's "
        "data reaches main through the bot's data PR."
    ]
    attempts = [s.last_attempt for s in (previous or {}).values() if s.last_attempt is not None]
    if not attempts:
        return [*lines, "", "No earlier run is recorded."], None
    latest = max(attempts)
    hours = int((now - latest).total_seconds() // 3600)
    lines += ["", f"Before this run, main's data came from a run at {_when(latest)} "
                  f"({hours} hours earlier)."]  # fmt: skip
    if now - latest <= STALE_AFTER:
        return lines, None
    return lines, (
        f"Main's data was {hours} hours old before this run: check that the bot's data PRs "
        "are merging."
    )


def _needs_look(candidates: Iterable[CandidateSource]) -> str:
    """Sites discovery found but couldn't read or judge automatically (no feed or event data,
    no upcoming events, or events only a person can judge). Add one by hand if it's worth it."""
    waiting = [c for c in candidates if c.result == "needs_review"]
    if not waiting:
        return "None."
    items = [f"- {code_span(c.url)}: {code_span(c.reason)}" for c in waiting]
    noun = "1 site" if len(waiting) == 1 else f"{len(waiting)} sites"
    listed = "\n".join(_capped(items))
    return f"{noun} discovery couldn't add automatically:\n\n{listed}"


def _spend(ai_spent_usd: float | None) -> list[str]:
    search = "Web search: not in use yet (the weekly discovery run comes later in Phase 4)."
    if ai_spent_usd is None:
        return ["AI second opinion: not used yet.", "", search]
    return [
        f"AI second opinion: ${ai_spent_usd:.2f} of ${MONTHLY_BUDGET_USD:.2f} this month "
        "(the OpenAI account also has its own $5 cap).",
        "",
        search,
    ]


def _capped(items: list[str]) -> list[str]:
    if len(items) <= MAX_LISTED:
        return items
    return [*items[:MAX_LISTED], f"- …and {len(items) - MAX_LISTED} more"]


def _when(value: datetime) -> str:
    return format_central(value, None, all_day=False)


def _day(value: datetime) -> str:
    local = value.astimezone(CENTRAL)
    return f"{local:%b} {local.day}, {local.year}"


def _days(gap: timedelta) -> str:
    days = round(gap.total_seconds() / 86400)
    return "day" if days <= 1 else f"{days} days"
