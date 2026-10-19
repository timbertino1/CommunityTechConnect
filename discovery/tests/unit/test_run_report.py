"""The Markdown run report shown in the Actions summary and the data PR."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime

import pytest

from netc.pipeline.discover_events import DiscoverReport, EventChange, SetAside, SourceRow
from netc.pipeline.run_report import MAX_ITEMS, MAX_REPORT_CHARS, render_markdown
from netc.pipeline.runner import SourceOutcome
from tests.data_samples import make_event, make_source, utc

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 19, 11, 0, tzinfo=UTC)
JOIN = "\N{WORD JOINER}"


def row(source_id: str, name: str, outcome: SourceOutcome, **counts: int) -> SourceRow:
    trust = "probationary" if counts.pop("probationary", 0) else "trusted"
    failures = counts.pop("previous_failures", 0)
    return SourceRow(make_source(source_id, name=name, trust=trust), outcome, failures,
                     Counter(counts))  # fmt: skip


def report(**overrides: object) -> DiscoverReport:
    rows = [
        row(
            "src_prairie-python",
            "Prairie Python",
            SourceOutcome(
                "src_prairie-python", "ok", past=3, latest_past=utc(2026, 10, 13, 22, 30)
            ),
        ),
        row(
            "src_unl",
            "UNL School of Computing",
            SourceOutcome("src_unl", "failed", error="RobotsUnavailableError: timed out"),
            previous_failures=1,
        ),
        row(
            "src_nic",
            "Nebraska Innovation Campus",
            SourceOutcome("src_nic", "skipped", skipped_reason="paused"),
        ),
    ]
    data: dict[str, object] = {
        "sources": {"sources": 3, "ok": 1, "failed": 1, "skipped": 1, "listings": 0},
        "now": NOW,
        "written": True,
        "rows": rows,
    }
    data.update(overrides)
    return DiscoverReport(**data)  # type: ignore[arg-type]


def test_header_counts_sources_and_changes() -> None:
    text = render_markdown(report())
    assert text.startswith("## Discovery run · Mon, Oct 19, 2026, 6:00 AM CT\n")
    assert "**Sources:** 1 read, 1 failed, 1 skipped." in text
    assert "0 added to the site, 0 held for review, 0 updated." in text
    assert "Dry run" not in text


def test_dry_runs_say_so() -> None:
    assert "Dry run: nothing was saved." in render_markdown(report(written=False))


def test_each_source_gets_a_row_with_its_result() -> None:
    lines = render_markdown(report()).splitlines()
    rows = {line.split(" | ")[0].lstrip("| "): line for line in lines if line.startswith("| ")}
    assert "✅ ok" in rows["Prairie Python"]
    assert "Oct 13, 2026 (3 past shown)" in rows["Prairie Python"]
    assert "❌ failed (2 runs in a row)" in rows["UNL School of Computing"]
    assert "⏸️ paused" in rows["Nebraska Innovation Campus"]


def test_failures_are_listed_with_their_error() -> None:
    text = render_markdown(report())
    assert "### Failures" in text
    assert "- **UNL School of Computing** (2 runs in a row): " in text
    assert "`RobotsUnavailableError: timed out`" in text


def test_no_failures_section_when_everything_worked() -> None:
    ok = report(rows=report().rows[:1])
    assert "### Failures" not in render_markdown(ok)


def test_probationary_sources_are_marked() -> None:
    rows = [row("src_x", "Campus", SourceOutcome("src_x", "ok"), probationary=1, held=2)]
    assert "✅ ok, probationary" in render_markdown(report(rows=rows))


def test_added_held_and_updated_events_are_listed() -> None:
    added = make_event(title="Drupal Nebraska", url="https://groups.drupal.org/node/1",
                       source_id="src_prairie-python")  # fmt: skip
    held = make_event(slug="talk-2026-10-30", title="Guest talk", url="https://events.unl.edu/1")
    moved = make_event(slug="moved-2026-11-03", title="Moved meetup", url="https://x.org/2")
    changes = [
        EventChange("added", added),
        EventChange("held", held, "source is probationary"),
        EventChange("updated", moved, "time, place"),
    ]
    text = render_markdown(report(changes=changes))
    assert "1 added to the site, 1 held for review, 1 updated." in text
    assert "### Added to the site (1)\n\n- `Drupal Nebraska` · Tue, Oct 20, 2026" in text
    assert "`groups.drupal.org` · from Prairie Python" in text
    assert "### Held for review (1)" in text
    assert "· why: `source is probationary`" in text
    assert "### Updated (1)" in text
    assert "· changed: `time, place`" in text


def test_rejected_and_dropped_listings_are_folded_away() -> None:
    aside = [
        SetAside("src_prairie-python", "Fall Semester Break", "rejected", "not about technology"),
        SetAside("src_prairie-python", "Untitled", "dropped", ""),
    ]
    text = render_markdown(report(set_aside=aside))
    assert "<details><summary>Rejected or dropped listings (2)</summary>" in text
    assert "- Prairie Python, rejected: `Fall Semester Break` (`not about technology`)" in text
    assert "- Prairie Python, dropped: `Untitled`\n" in text
    assert text.rstrip().endswith("</details>")


def test_repeated_listings_are_shown_once_with_a_count() -> None:
    exams = SetAside("src_unl", "Final Exams", "rejected", "excluded: final exam")
    text = render_markdown(report(set_aside=[exams] * 5))
    assert "(5)</summary>" in text  # the summary still counts every listing
    assert text.count("`Final Exams`") == 1
    assert "(`excluded: final exam`), 5 times" in text


def test_long_lists_are_capped() -> None:
    aside = [SetAside("src_prairie-python", f"Item {i}", "rejected", "") for i in range(80)]
    text = render_markdown(report(set_aside=aside))
    assert f"`Item {MAX_ITEMS - 1}`" in text
    assert f"`Item {MAX_ITEMS}`" not in text
    assert "- …and 30 more" in text


def test_the_report_fits_in_a_pr_description() -> None:
    rows = [
        row(f"src_{i}", "Source " + "x" * 120, SourceOutcome(f"src_{i}", "ok")) for i in range(2000)
    ]
    text = render_markdown(report(rows=rows))
    assert len(text) <= MAX_REPORT_CHARS
    assert text.endswith("*(Report shortened.)*\n")


# --- Text from other sites can't do anything on GitHub


HOSTILE = [
    "@timbertino1 please look",
    "Fixes #12",
    "![x](https://evil.example/pixel.png)",
    "[click](https://evil.example/)",
    "<img src=x onerror=alert(1)>",
    "Break `out` of | the table",
    "line one\n## Heading\n- item",
]


@pytest.mark.parametrize("title", HOSTILE)
def test_listing_text_stays_inside_a_code_span(title: str) -> None:
    text = render_markdown(report(set_aside=[SetAside("src_prairie-python", title, "rejected",
                                                      title)]))  # fmt: skip
    line = next(x for x in text.splitlines() if x.startswith("- Prairie Python, rejected: "))
    spans = re.findall(r"`[^`]*`", line)
    assert len(spans) == 2  # title and reason, each one whole span
    outside = re.sub(r"`[^`]*`", "", line)
    for marker in ("@", "#", "](", "<img", "|", "\n"):
        assert marker not in outside
    assert "\n## Heading" not in text


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("@octocat fans", f"@{JOIN}octocat fans"),
        ("C# Omaha #12", f"C\\#{JOIN} Omaha \\#{JOIN}12"),
        ("See https://evil.example", f"See https:{JOIN}//evil.example"),
        ("**Bold** [x](y) | z", "\\*\\*Bold\\*\\* \\[x\\]\\(y\\) \\| z"),
        ("(NE)NUG", "\\(NE\\)NUG"),
    ],
)
def test_source_names_are_escaped(name: str, expected: str) -> None:
    rows = [row("src_x", name, SourceOutcome("src_x", "ok"))]
    text = render_markdown(report(rows=rows))
    assert f"| {expected} | ✅ ok |" in text
