"""The review pull request (T120, T122; contracts/workflows-and-review.md, "Review PR").

The bot keeps one PR open on branch ``review/open`` while items wait for review. Its only file
change is ``data/review/open.json``, the snapshot of the ``rev_`` ids it lists, and its
description has one block per item with an approve and a reject checkbox. The owner ticks
boxes and merges; `netc apply-review` then reads the ticks (see netc.pipeline.review).

Only items already on main are listed, so every id in the snapshot exists in the queue. Event
text comes from other sites, so it is shown in code spans: it can't contain a backtick, which
means it can't fake an item header, an id, or a checkbox line that the parser would read.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from urllib.parse import urlsplit

from netc.github.markdown import code_span, plain_name
from netc.models import Event, ReviewItem, Source
from netc.pipeline.timeutil import format_central

REVIEW_BRANCH: Final = "review/open"
MAX_ITEMS: Final = 100
"""Most items in one PR (GitHub caps a description at 65,536 characters); the rest wait."""

KIND_LABELS: Final = {
    "event": ("Event", "events"),
    "source": ("Source", "sources"),
    "suggestion": ("Suggestion", "suggestions"),
    "mention": ("Mention", "mentions"),
}
INTRO: Final = """\
Tick **approve** or **reject** under each item, then **merge** this PR. That's all: the bot \
applies your decisions a minute later in a small data PR that merges itself.

- **Approve** publishes the event on the site. **Reject** keeps it off the site for good.
- An item with neither box ticked (or both) stays waiting and comes back in the next review PR.
- A probationary source becomes trusted after 3 approved events and no rejected ones; its \
later events then publish without review. A source with more rejected than approved events \
is paused.
- Closing this PR without merging changes nothing. The bot won't rewrite it once you've \
ticked a box.
- Only the ticks are read, so there's no need to edit anything else.
"""

Decision = Literal["approved", "rejected"]

_HEADER: Final = re.compile(
    r"^\*\*(?:Event|Source|Suggestion|Mention)\*\* · .*`(rev_[a-f0-9]{12})`\s*$"
)
_BOX: Final = re.compile(r"^\s*[-*] \[([ xX])\] (approve|reject)\s*$")


@dataclass(frozen=True)
class ReviewPr:
    title: str
    body: str
    review_ids: list[str]
    """The snapshot written to data/review/open.json."""
    waiting: int
    """Pending items that could not be listed (over MAX_ITEMS); they wait for the next PR."""


def build_review_pr(
    queue: Iterable[ReviewItem],
    events: Iterable[Event],
    sources: Iterable[Source],
    *,
    categories: Mapping[str, str],
    areas: Mapping[str, str],
    now: datetime,
) -> ReviewPr | None:
    """The review PR for every pending item, or None when nothing is waiting.

    Event items are listed soonest first; events that are over or no longer pending are left
    out (nothing to decide). Other kinds are listed after events, oldest first.
    """
    by_event = {e.id: e for e in events}
    names = {s.id: s.name for s in sources}
    listed = pending_items(queue, by_event.values(), now=now)
    if not listed:
        return None

    shown = listed[:MAX_ITEMS]
    waiting = len(listed) - len(shown)
    blocks = [
        _event_block(item, by_event[item.ref], names, categories, areas)
        if item.kind == "event"
        else _other_block(item)
        for item in shown
    ]
    count = len(shown)
    lines = [
        f"## {count} item{'s' if count != 1 else ''} waiting for review",
        "",
        INTRO,
        "---",
        "",
        "\n\n".join(blocks),
    ]
    if waiting:
        lines += ["", f"*{waiting} more will be listed in the next review PR.*"]

    kinds = [KIND_LABELS[k][1] for k in KIND_LABELS if any(i.kind == k for i in shown)]
    title = f"Review: {count} item{'s' if count != 1 else ''} ({', '.join(kinds)})"
    return ReviewPr(title, "\n".join(lines) + "\n", sorted(i.id for i in shown), waiting)


def pending_items(
    queue: Iterable[ReviewItem], events: Iterable[Event], *, now: datetime
) -> list[ReviewItem]:
    """The items still waiting for a decision, in review PR order (see build_review_pr)."""
    by_event = {e.id: e for e in events}
    listed: list[tuple[tuple[int, str, str], ReviewItem]] = []
    for item in queue:
        if item.decision != "pending":
            continue
        if item.kind == "event":
            event = by_event.get(item.ref)
            if event is None or event.review_state != "pending_review":
                continue
            if (event.end or event.start) <= now:
                continue
            key = (0, event.start.isoformat(), item.id)
        else:
            key = (1, item.created.isoformat(), item.id)
        listed.append((key, item))
    listed.sort(key=lambda pair: pair[0])
    return [item for _, item in listed]


def read_decisions(body: str) -> dict[str, Decision]:
    """The decision for each item that has exactly one box ticked.

    Neither or both ticked means no decision. Checkbox lines count only under an item header,
    and only for that header's id. Ids are not checked here; the caller keeps only ids that
    are in the snapshot and still pending.
    """
    ticks: dict[str, set[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        header = _HEADER.match(line)
        if header:
            current = header.group(1)
            ticks.setdefault(current, set())
            continue
        box = _BOX.match(line)
        if box and current is not None and box.group(1) in "xX":
            ticks[current].add(box.group(2))
    return {
        review_id: "approved" if marks == {"approve"} else "rejected"
        for review_id, marks in ticks.items()
        if len(marks) == 1
    }


def has_ticks(body: str) -> bool:
    """Whether the owner has started deciding (any box ticked under an item)."""
    current = False
    for line in body.splitlines():
        if _HEADER.match(line):
            current = True
            continue
        box = _BOX.match(line)
        if box and current and box.group(1) in "xX":
            return True
    return False


def _event_block(
    item: ReviewItem,
    event: Event,
    names: Mapping[str, str],
    categories: Mapping[str, str],
    areas: Mapping[str, str],
) -> str:
    when = format_central(event.start, event.end, all_day=event.all_day)
    where = plain_name(areas.get(event.area, event.area))
    topics = ", ".join(plain_name(categories.get(c, c)) for c in event.categories)
    sources = ", ".join(
        dict.fromkeys(plain_name(names.get(x.source_id, x.source_id)) for x in event.listings)
    )
    header = f"**Event** · {code_span(event.title)} — {when} · {where} · {topics} · `{item.id}`"
    held = f"Held: {code_span(item.reason)} · from {sources} · {_link(event.original_url)}"
    return "\n".join([header, held, "- [ ] approve", "- [ ] reject"])


def _other_block(item: ReviewItem) -> str:
    label = KIND_LABELS.get(item.kind, ("Item", ""))[0]
    header = f"**{label}** · {code_span(item.ref)} · `{item.id}`"
    return "\n".join([header, f"Held: {code_span(item.reason)}", "- [ ] approve", "- [ ] reject"])


def _link(url: str) -> str:
    """A link to the original page. Event URLs are validated https URLs; anything that could
    break out of the link's angle brackets is shown as text instead."""
    if any(c in url for c in "<>\\ \t\r\n") or urlsplit(url).scheme != "https":
        return code_span(urlsplit(url).hostname or "link")
    return f"[original page](<{url}>)"
