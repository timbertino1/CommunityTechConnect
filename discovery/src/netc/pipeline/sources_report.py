"""The discover-sources run report: the job summary and the weekly data PR's description.

Like the discovery run report, everything from other sites (names, URLs, reasons) goes in code
spans or is shown as plain text with mentions and links broken (netc.github.markdown).
"""

from __future__ import annotations

from typing import Final

from netc.github.markdown import code_span, plain_name
from netc.pipeline.ai import MONTHLY_BUDGET_USD
from netc.pipeline.discover_sources import DiscoverSourcesReport
from netc.pipeline.timeutil import format_central

MAX_LISTED: Final = 40
CHANNELS: Final = {
    "web_search": "web search",
    "link_graph": "links on known pages",
    "news": "news feeds",
    "newsletter": "newsletters",
    "gap": "gap checks",
    "platform": "event platforms",
    "suggestion": "visitor suggestions",
}
RESULTS: Final = {
    "rejected": "rejected",
    "needs_review": "needs a look",
    "blocked_by_terms": "blocked by terms",
}


def render_sources_markdown(report: DiscoverSourcesReport) -> str:
    found = sum(report.found.values())
    lines = [
        f"## Finding new groups · {format_central(report.now, None, all_day=False)}",
        "",
        f"**{found} new candidate{'s' if found != 1 else ''}**, "
        f"**{len(report.added)} added on probation**, "
        f"{report.new_mentions} new mention{'s' if report.new_mentions != 1 else ''}."
        + ("" if report.written else " *(Dry run: nothing was saved.)*"),
        "",
        "New sources start on probation: their events wait in the review PR until 3 are approved.",
        "",
        "### Finders",
        "",
        "| Finder | Result |",
        "|---|---|",
    ]
    for name, stats in report.finders.items():
        detail = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sorted(stats.items()))
        lines.append(f"| {CHANNELS.get(name, name)} | {detail or 'nothing to do'} |")
    for name, error in report.finder_errors.items():
        lines.append(f"| {CHANNELS.get(name, name)} | failed: {code_span(error)} |")

    if report.found:
        by = ", ".join(f"{CHANNELS.get(k, k)} {v}" for k, v in sorted(report.found.items()))
        lines += ["", f"**New candidates by channel:** {by}."]

    if report.added:
        lines += ["", "### Added on probation", ""]
        lines += [
            f"- **{plain_name(s.name)}** · {code_span(s.url)} · read as {s.connector}"
            f" · found via {CHANNELS.get(s.found_via or '', s.found_via or 'unknown')}"
            for s in report.added[:MAX_LISTED]
        ]
    if report.stopped_for_time:
        waiting = report.evaluated["deferred"]
        lines += [
            "",
            f"**Stopped at the time limit:** {waiting} candidate{'s' if waiting != 1 else ''} "
            "wait for the next run.",
        ]
    if report.set_aside:
        lines += ["", "### Looked at and not added", ""]
        lines += [
            f"- {code_span(c.url)} · {RESULTS.get(c.result, c.result)}: {code_span(c.reason)}"
            for c in report.set_aside[:MAX_LISTED]
        ]
        if len(report.set_aside) > MAX_LISTED:
            lines.append(f"- …and {len(report.set_aside) - MAX_LISTED} more")

    m = report.mentions
    lines += [
        "",
        "### Mentions",
        "",
        f"{m['resolved']} resolved to an organizer's page, {m['unresolved']} still looking, "
        f"{m['discarded']} retired (past, or not found after 4 tries)."
        + (f" {m['deferred']} wait for the next run." if m["deferred"] else ""),
    ]
    budgets = []
    if report.searches_used is not None:
        budgets.append(
            f"web search: {report.searches_used} used, {report.searches_left} left this month"
        )
    if report.ai_calls is not None:
        spent = f"${report.ai_spent_usd:.2f} of ${MONTHLY_BUDGET_USD:.2f}"
        budgets.append(f"AI: {report.ai_calls} calls, {spent} this month")
    if budgets:
        lines += ["", "**Budgets:** " + "; ".join(budgets) + "."]
    if report.inbox_deleted or report.inbox_delete_errors:
        lines += [
            "",
            f"**Newsletter inbox:** {report.inbox_deleted} read and cleared"
            + (
                f", {report.inbox_delete_errors} could not be cleared (read again next run)"
                if report.inbox_delete_errors
                else ""
            )
            + ".",
        ]
    if report.suggestions_read or report.suggestions_error:
        line = (
            f"**Visitor suggestions:** could not be read ({code_span(report.suggestions_error)})"
            if report.suggestions_error
            else f"**Visitor suggestions:** {report.suggestions_read} read, "
            f"{report.suggestions_for_review} sent to review, "
            + (f"{report.suggestions_known} already listed, " if report.suggestions_known else "")
            + f"{report.suggestions_deleted} cleared from KV"
        )
        lines += ["", line + "."]
    return "\n".join(lines) + "\n"
