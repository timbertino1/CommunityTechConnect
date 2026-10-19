"""The run report: a short Markdown summary of one discovery run.

It is written to the Actions job summary and used as the data PR's description, so the owner
can see at a glance which sources were read, what each one found, and which events changed.

Everything from outside sites (titles, errors, reasons) goes inside code spans. The report is
posted on a public repository, and a code span is where GitHub does not turn text into
@mentions, issue links, autolinks, images or HTML, so a hostile title stays plain text.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Final
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from netc.pipeline.discover_events import DiscoverReport, EventChange, SourceRow
from netc.pipeline.timeutil import format_central

CENTRAL: Final = ZoneInfo("America/Chicago")
MAX_TEXT: Final = 140
MAX_ITEMS: Final = 50
"""Longest list shown per section; the rest are counted."""
MAX_REPORT_CHARS: Final = 60_000
"""GitHub caps a PR description at 65,536 characters."""

SKIP_LABELS: Final = {
    "not_due": "⏭️ not due yet",
    "paused": "⏸️ paused",
    "blocked_by_terms": "⛔ blocked by terms",
}
_SPACE: Final = re.compile(r"\s+")
_MARKDOWN: Final = re.compile(r"([\\`*_{}\[\]<>()#+!|~])")
# GitHub finds @mentions, #123 links and bare URLs after rendering, so escaping doesn't stop
# them; an invisible word joiner after the trigger character does.
_JOIN: Final = "\N{WORD JOINER}"
_TRIGGERS: Final = re.compile(r"([@#]|:(?=//))")


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
            f"- **{_name(row.source.name)}** ({_failure_count(row)}): "
            f"{_code(row.outcome.error or 'unknown error')}"
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
                f"- {_name(names.get(sid, sid))}, {kind}: {_code(title)}"
                + (f" ({_code(reason)})" if reason else "")
                + (f", {n} times" if n > 1 else "")
                for (sid, kind, title, reason), n in repeats.items()
            ]
        )
        lines += ["", "</details>"]

    text = "\n".join(lines) + "\n"
    if len(text) > MAX_REPORT_CHARS:
        text = text[: MAX_REPORT_CHARS - 40].rsplit("\n", 1)[0] + "\n\n*(Report shortened.)*\n"
    return text


def _source_row(row: SourceRow) -> str:
    outcome = row.outcome
    if outcome.status == "skipped":
        reason = outcome.skipped_reason or ""
        result = SKIP_LABELS.get(reason, f"⏭️ skipped ({_name(reason)})")
        return f"| {_name(row.source.name)} | {result} | | | | | | |"
    if outcome.status == "failed":
        result = f"❌ failed ({_failure_count(row)})"
        return f"| {_name(row.source.name)} | {result} | | | | | | |"
    c = row.listings
    result = "✅ ok" + (f", {len(outcome.warnings)} warnings" if outcome.warnings else "")
    if row.source.trust == "probationary":
        result += ", probationary"
    latest = _day(outcome.latest_past) if outcome.latest_past else ""
    if latest and outcome.past > 1:
        latest += f" ({outcome.past} past shown)"
    return (
        f"| {_name(row.source.name)} | {result} | {len(outcome.listings)} | {c['kept']} "
        f"| {c['held']} | {c['rejected']} | {c['dropped']} | {latest} |"
    )


def _change(change: EventChange, names: dict[str, str]) -> str:
    event = change.event
    when = format_central(event.start, event.end, all_day=event.all_day)
    host = urlsplit(event.original_url).hostname or ""
    sources = ", ".join(dict.fromkeys(_name(names.get(x.source_id, x.source_id))
                                      for x in event.listings))  # fmt: skip
    line = f"- {_code(event.title)} · {when} · {_code(host)} · from {sources}"
    if change.detail:
        label = "why" if change.kind == "held" else "changed"
        line += f" · {label}: {_code(change.detail)}"
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


def _one_line(text: str) -> str:
    text = _SPACE.sub(" ", text).strip()
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1].rstrip() + "…"


def _code(text: str) -> str:
    """Untrusted text as an inline code span. Backticks can't be escaped inside one, so they
    become apostrophes; pipes would still split a table cell, so they become slashes."""
    body = _one_line(text).replace("`", "'").replace("|", "/")
    return f"`{body}`" if body else "`-`"


def _name(text: str) -> str:
    """A source name (reviewed data) as plain text: Markdown escaped, mentions and links broken."""
    escaped = _MARKDOWN.sub(r"\\\1", _one_line(text))
    return _TRIGGERS.sub(lambda m: m.group(1) + _JOIN, escaped) or "-"
