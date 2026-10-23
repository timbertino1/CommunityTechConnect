"""The run report: a short Markdown summary of one discovery run.

It is written to the Actions job summary and used as the data PR's description, so the owner
can see at a glance which sources were read, what each one found, and which events changed.

Everything from outside sites (titles, errors, reasons) goes inside code spans. The report is
posted on a public repository, and a code span is where GitHub does not turn text into
@mentions, issue links, autolinks, images or HTML, so a hostile title stays plain text.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Final
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from netc.github.markdown import code_span, plain_name
from netc.pipeline.ai import MONTHLY_BUDGET_USD
from netc.pipeline.discover_events import DiscoverReport, EventChange, SourceRow
from netc.pipeline.timeutil import format_central

CENTRAL: Final = ZoneInfo("America/Chicago")
MAX_ITEMS: Final = 50
"""Longest list shown per section; the rest are counted."""
MAX_REPORT_CHARS: Final = 60_000
"""GitHub caps a PR description at 65,536 characters."""

SKIP_LABELS: Final = {
    "not_due": "⏭️ not due yet",
    "paused": "⏸️ paused",
    "blocked_by_terms": "⛔ blocked by terms",
}


def render_markdown(report: DiscoverReport) -> str:
    names = {row.source.id: row.source.name for row in report.rows}
    when = format_central(report.now, None, all_day=False) if report.now else "unknown time"
    kinds = Counter(c.kind for c in report.changes)
    m = report.sources
    read, failed = m.get("ok", 0), m.get("failed", 0)
    skipped = m.get("skipped", 0)
    lines = [
        f"## Discovery run · {when}",
        "",
        f"**Sources:** {read} read, {failed} failed, {skipped} skipped."
        f" **Events:** {kinds['added']} added to the site, {kinds['held']} held for review,"
        f" {kinds['updated']} updated."
        + ("" if report.written else " *(Dry run: nothing was saved.)*"),
        "",
        *_ai_line(report),
        *_link_line(report),
        "### Sources",
        "",
        "| Source | Result | Upcoming | Added or kept | Held | Rejected | Dropped "
        "| Latest past event |",
        "|---|---|--:|--:|--:|--:|--:|---|",
    ]
    lines += [_source_row(row) for row in report.rows]
    lines.append("")
    lines.append(
        "*Upcoming* counts events found in the next 180 days. *Latest past event* is the most "
        "recent event the source still shows that has already happened; it tells a quiet group "
        "from a broken reader."
    )

    failures = [row for row in report.rows if row.outcome.status == "failed"]
    if failures:
        lines += ["", "### Failures", ""]
        lines += [
            f"- **{plain_name(row.source.name)}** ({_failure_count(row)}): "
            f"{code_span(row.outcome.error or 'unknown error')}"
            for row in failures
        ]

    for kind, heading in (
        ("added", "Added to the site"),
        ("held", "Held for review"),
        ("updated", "Updated"),
    ):
        items = [c for c in report.changes if c.kind == kind]
        if items:
            lines += ["", f"### {heading} ({len(items)})", ""]
            lines += _capped([_change(c, names) for c in items])

    if report.set_aside:
        lines += [
            "",
            f"<details><summary>Rejected or dropped listings ({len(report.set_aside)})</summary>",
            "",
        ]
        # A multi-day entry (exam week, a closedown) arrives once per day: show it once.
        repeats = Counter((s.source_id, s.kind, s.title, s.reason) for s in report.set_aside)
        lines += _capped(
            [
                f"- {plain_name(names.get(sid, sid))}, {kind}: {code_span(title)}"
                + (f" ({code_span(reason)})" if reason else "")
                + (f", {n} times" if n > 1 else "")
                for (sid, kind, title, reason), n in repeats.items()
            ]
        )
        lines += ["", "</details>"]

    text = "\n".join(lines) + "\n"
    if len(text) > MAX_REPORT_CHARS:
        text = text[: MAX_REPORT_CHARS - 40].rsplit("\n", 1)[0] + "\n\n*(Report shortened.)*\n"
    return text


def _ai_line(report: DiscoverReport) -> list[str]:
    if report.ai_calls is None:
        return []
    calls = "1 call" if report.ai_calls == 1 else f"{report.ai_calls} calls"
    problems = ""
    if report.ai_unusable:
        why = code_span(report.ai_last_problem or "unknown")
        problems = (
            f" {report.ai_unusable} gave no usable answer (last: {why}); those wait for review."
        )
    return [
        f"**AI second opinion:** {calls} this run; ${report.ai_spent_usd:.2f} of "
        f"${MONTHLY_BUDGET_USD:.2f} spent this month.{problems}",
        "",
    ]


def _link_line(report: DiscoverReport) -> list[str]:
    """The monthly check of past events' original pages (T118)."""
    check = report.link_check
    if check is None:
        return []
    pages = "1 page" if check.checked == 1 else f"{check.checked} pages"
    gone = "1 may be gone" if check.unavailable == 1 else f"{check.unavailable} may be gone"
    return [f"**Past events' original pages:** {pages} checked; {gone}.", ""]


def _source_row(row: SourceRow) -> str:
    outcome = row.outcome
    if outcome.status == "skipped":
        reason = outcome.skipped_reason or ""
        result = SKIP_LABELS.get(reason, f"⏭️ skipped ({plain_name(reason)})")
        return f"| {plain_name(row.source.name)} | {result} | | | | | | |"
    if outcome.status == "failed":
        result = f"❌ failed ({_failure_count(row)})"
        return f"| {plain_name(row.source.name)} | {result} | | | | | | |"
    c = row.listings
    result = "✅ ok" + (f", {len(outcome.warnings)} warnings" if outcome.warnings else "")
    if row.source.trust == "probationary":
        result += ", probationary"
    latest = _day(outcome.latest_past) if outcome.latest_past else ""
    if latest and outcome.past > 1:
        latest += f" ({outcome.past} past shown)"
    return (
        f"| {plain_name(row.source.name)} | {result} | {len(outcome.listings)} | {c['kept']} "
        f"| {c['held']} | {c['rejected']} | {c['dropped']} | {latest} |"
    )


def _change(change: EventChange, names: dict[str, str]) -> str:
    event = change.event
    when = format_central(event.start, event.end, all_day=event.all_day)
    host = urlsplit(event.original_url).hostname or ""
    sources = ", ".join(dict.fromkeys(plain_name(names.get(x.source_id, x.source_id))
                                      for x in event.listings))  # fmt: skip
    line = f"- {code_span(event.title)} · {when} · {code_span(host)} · from {sources}"
    if change.detail:
        label = "why" if change.kind == "held" else "changed"
        line += f" · {label}: {code_span(change.detail)}"
    return line


def _failure_count(row: SourceRow) -> str:
    n = row.previous_failures + 1
    return "first failure" if n == 1 else f"{n} runs in a row"


def _capped(items: list[str]) -> list[str]:
    if len(items) <= MAX_ITEMS:
        return items
    return [*items[:MAX_ITEMS], f"- …and {len(items) - MAX_ITEMS} more"]


def _day(value: datetime) -> str:
    local = value.astimezone(CENTRAL)
    return f"{local:%b} {local.day}, {local.year}"
