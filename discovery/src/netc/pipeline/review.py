"""Apply the decisions from a merged review PR (T121, T122; FR-017, FR-018).

Two steps, both strict:

1. ``check_review_merge`` decides whether the pushed commit is the merge of the bot's review
   PR, using the GitHub API responses the workflow fetched: the head branch is ``review/open``,
   the author is the bot, the PR was merged into main as exactly this commit, whoever merged
   it has the admin role, and the description was not edited after the merge (the ticks read
   are the ones the admin merged).
2. ``apply_decisions`` applies only ticks for ids that are in the PR's snapshot
   (``data/review/open.json`` at the merge commit) and still pending in the queue. Editing the
   description to add other ids, or re-running an old PR, changes nothing.

Approved events are published and rejected ones are kept off the site for good. Each decision
counts toward the event's sources: a probationary source with 3 approvals and no rejections
becomes trusted, and one with more rejections than approvals is paused (FR-018).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from netc.github.review_pr import REVIEW_BRANCH, Decision
from netc.models import Event, ReviewItem, Source
from netc.pipeline.overrides import apply_overrides
from netc.storage import DataStore

PROMOTE_AFTER_APPROVALS: Final = 3
BASE_BRANCH: Final = "main"


@dataclass(frozen=True)
class MergeCheck:
    ok: bool
    reason: str
    number: int | None = None


@dataclass
class ApplyResult:
    pr_number: int
    approved: list[ReviewItem] = field(default_factory=list)
    rejected: list[ReviewItem] = field(default_factory=list)
    still_pending: int = 0
    ignored: list[str] = field(default_factory=list)
    """Ticked ids that were not in the snapshot or were no longer pending."""
    promoted: list[Source] = field(default_factory=list)
    paused: list[Source] = field(default_factory=list)
    titles: dict[str, str] = field(default_factory=dict)
    """Event title for each decided review id (for the report)."""


def check_review_merge(
    pr: Mapping[str, Any],
    permission: Mapping[str, Any],
    edits: Mapping[str, Any],
    *,
    commit: str,
    bot_login: str,
) -> MergeCheck:
    """Whether ``commit`` is an admin's merge of the bot's review PR. Never raises."""
    try:
        number = pr.get("number")
        if not isinstance(number, int):
            return MergeCheck(False, "the PR response has no number")
        if _get(pr, "head", "ref") != REVIEW_BRANCH:
            return MergeCheck(False, f"head branch is not {REVIEW_BRANCH}", number)
        if _get(pr, "base", "ref") != BASE_BRANCH:
            return MergeCheck(False, f"the PR was not merged into {BASE_BRANCH}", number)
        if _get(pr, "user", "login") != bot_login:
            return MergeCheck(False, f"the PR was not opened by {bot_login}", number)
        if pr.get("merged") is not True or not isinstance(pr.get("merged_at"), str):
            return MergeCheck(False, "the PR is not merged", number)
        if pr.get("merge_commit_sha") != commit:
            return MergeCheck(False, "this commit is not the PR's merge commit", number)
        merger = _get(pr, "merged_by", "login")
        if not isinstance(merger, str) or not merger:
            return MergeCheck(False, "the PR response does not say who merged it", number)
        if _get(permission, "user", "login") != merger:
            return MergeCheck(False, "the permission response is for someone else", number)
        if permission.get("permission") != "admin":
            return MergeCheck(False, f"{merger} does not have the admin role", number)
        merged_at = _time(pr["merged_at"])
        edited = _get(edits, "data", "repository", "pullRequest", "lastEditedAt")
        if not _has_path(edits, "data", "repository", "pullRequest"):
            return MergeCheck(False, "the edit history response is missing", number)
        if edited is not None and _time(edited) > merged_at:
            return MergeCheck(False, "the PR description was edited after it was merged", number)
    except (TypeError, ValueError, KeyError) as exc:
        return MergeCheck(False, f"unreadable GitHub response ({type(exc).__name__})")
    return MergeCheck(True, f"review PR #{number} merged by {merger}", number)


def apply_decisions(
    store: DataStore,
    *,
    pr_number: int,
    decisions: Mapping[str, Decision],
    open_ids: Iterable[str],
    now: datetime,
) -> ApplyResult:
    """Record the decisions and update events and sources. Writes only what changed."""
    result = ApplyResult(pr_number)
    snapshot = set(open_ids)
    queue = store.read_review_queue()
    pending = {r.id for r in queue if r.decision == "pending"}
    eligible = snapshot & pending
    result.ignored = sorted(set(decisions) - eligible)
    result.still_pending = len(eligible - set(decisions))

    events = {e.id: e for e in store.read_events()}
    sources = {s.id: s for s in store.read_sources()}
    counted: dict[str, Source] = {}
    events_changed = False
    new_queue: list[ReviewItem] = []

    for item in queue:
        decision = decisions.get(item.id) if item.id in eligible else None
        if decision is None:
            new_queue.append(item)
            continue
        new_queue.append(item.model_copy(update={"decision": decision, "decided_in_pr": pr_number}))
        (result.approved if decision == "approved" else result.rejected).append(item)
        event = events.get(item.ref) if item.kind == "event" else None
        if event is None:
            continue
        result.titles[item.id] = event.title
        state = "published" if decision == "approved" else "rejected"
        events[event.id] = event.model_copy(update={"review_state": state})
        events_changed = True
        for source_id in _source_ids(event):
            source = counted.get(source_id) or sources.get(source_id)
            if source is None:
                continue
            field_name = "approved_count" if decision == "approved" else "rejected_count"
            counted[source_id] = source.model_copy(
                update={field_name: getattr(source, field_name) + 1}
            )

    changed_sources: list[Source] = []
    for source_id, source in counted.items():
        updated = _apply_trust_rules(source)
        if updated.trust == "trusted" and sources[source_id].trust == "probationary":
            result.promoted.append(updated)
        if updated.status == "paused" and sources[source_id].status != "paused":
            result.paused.append(updated)
        changed_sources.append(updated.model_copy(update={"updated_at": now.date()}))

    if result.approved or result.rejected:
        store.write_review_queue(new_queue)
    if events_changed:
        ordered = sorted(events.values(), key=lambda e: (e.start, e.id))
        store.write_events(apply_overrides(ordered, store.read_overrides()))
    for source in changed_sources:
        store.write_source(source)
    return result


def _apply_trust_rules(source: Source) -> Source:
    """FR-018, for probationary sources (a trusted source is demoted only by the owner)."""
    if source.trust != "probationary":
        return source
    if source.rejected_count > source.approved_count:
        return (
            source.model_copy(update={"status": "paused"}) if source.status == "active" else source
        )
    if source.approved_count >= PROMOTE_AFTER_APPROVALS and source.rejected_count == 0:
        return source.model_copy(update={"trust": "trusted"})
    return source


def _source_ids(event: Event) -> list[str]:
    return list(dict.fromkeys(listing.source_id for listing in event.listings))


def _get(data: Mapping[str, Any], *path: str) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _has_path(data: Mapping[str, Any], *path: str) -> bool:
    value: Any = data
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            return False
        value = value[key]
    return isinstance(value, Mapping)


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError("not a timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp without a time zone")
    return parsed
