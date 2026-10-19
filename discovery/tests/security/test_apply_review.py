"""Applying a merged review PR: only the bot's PR, merged by an admin, and only its own items
(T121; contracts/workflows-and-review.md "Review PR"; FR-017, FR-018)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from netc.cli import main
from netc.github.review_pr import build_review_pr, read_decisions
from netc.models import Event, ReviewItem, Source
from netc.pipeline.review import ApplyResult, MergeCheck, apply_decisions, check_review_merge
from netc.storage import DataStore
from tests.review_support import (
    AREAS,
    CATEGORIES,
    NOW,
    campus_source,
    held_event,
    make_review_data,
    queue_item,
    tick,
)

pytestmark = pytest.mark.security

BOT = "netechconnect-bot[bot]"
SHA = "a" * 40
PR: dict[str, Any] = {
    "number": 42,
    "head": {"ref": "review/open"},
    "base": {"ref": "main"},
    "user": {"login": BOT},
    "merged": True,
    "merged_at": "2026-10-19T14:00:00Z",
    "merge_commit_sha": SHA,
    "merged_by": {"login": "timbertino1"},
    "body": "",
}
PERMISSION: dict[str, Any] = {"permission": "admin", "user": {"login": "timbertino1"}}
EDITS: dict[str, Any] = {
    "data": {"repository": {"pullRequest": {"lastEditedAt": "2026-10-19T13:59:00Z"}}}
}


def changed(base: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    data = copy.deepcopy(base)
    *parents, last = path.split(".")
    target = data
    for key in parents:
        target = target[key]
    target[last] = value
    return data


def check(
    pr: dict[str, Any] = PR,
    permission: dict[str, Any] = PERMISSION,
    edits: dict[str, Any] = EDITS,
    commit: str = SHA,
) -> MergeCheck:
    return check_review_merge(pr, permission, edits, commit=commit, bot_login=BOT)


# --- Is this the bot's review PR, merged by an admin, as this commit?


def test_the_real_thing_passes() -> None:
    result = check()
    assert result.ok, result.reason
    assert result.number == 42


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        ("head.ref", "bot/data-2026-10-19", "head branch"),
        ("head.ref", "review/open-2", "head branch"),
        ("base.ref", "develop", "not merged into main"),
        ("user.login", "timbertino1", "not opened by"),
        ("user.login", "netechconnect-bot", "not opened by"),
        ("merged", False, "not merged"),
        ("merged_at", None, "not merged"),
        ("merge_commit_sha", "b" * 40, "not the PR's merge commit"),
        ("merged_by", None, "who merged"),
        ("number", "42", "no number"),
    ],
)
def test_anything_else_is_refused(path: str, value: Any, reason: str) -> None:
    result = check(pr=changed(PR, path, value))
    assert not result.ok
    assert reason in result.reason


def test_a_merger_without_the_admin_role_is_refused() -> None:
    result = check(permission=changed(PERMISSION, "permission", "write"))
    assert not result.ok
    assert "admin" in result.reason


def test_a_permission_answer_for_someone_else_is_refused() -> None:
    result = check(permission=changed(PERMISSION, "user.login", "someone-else"))
    assert not result.ok


def test_a_description_edited_after_the_merge_is_refused() -> None:
    late = changed(EDITS, "data.repository.pullRequest.lastEditedAt", "2026-10-19T14:05:00Z")
    result = check(edits=late)
    assert not result.ok
    assert "edited after" in result.reason


def test_a_never_edited_description_is_fine() -> None:
    assert check(edits=changed(EDITS, "data.repository.pullRequest.lastEditedAt", None)).ok


@pytest.mark.parametrize("edits", [{}, {"data": None}, {"errors": [{"message": "nope"}]}])
def test_a_missing_edit_history_is_refused(edits: dict[str, Any]) -> None:
    assert not check(edits=edits).ok


def test_unreadable_responses_are_refused_without_raising() -> None:
    assert not check(pr=changed(PR, "merged_at", "yesterday")).ok
    assert not check(pr={}).ok


# --- Applying the ticks


def setup(tmp_path: Path, n: int = 3, **source: Any) -> tuple[DataStore, list[Event], str]:
    events = [held_event(i + 1) for i in range(n)]
    queue = [queue_item(e) for e in events]
    store = make_review_data(tmp_path / "data", events, queue, [campus_source(**source)])
    pr = build_review_pr(queue, events, store.read_sources(), categories=CATEGORIES,
                         areas=AREAS, now=NOW)  # fmt: skip
    assert pr is not None
    return store, events, pr.body


def rid(event: Event) -> str:
    return queue_item(event).id


def apply(store: DataStore, body: str, open_ids: list[str] | None = None) -> ApplyResult:
    return apply_decisions(
        store,
        pr_number=42,
        decisions=read_decisions(body),
        open_ids=open_ids if open_ids is not None else store.read_review_open(),
        now=NOW,
    )


def states(store: DataStore) -> dict[str, str]:
    return {e.title: e.review_state for e in store.read_events()}


def queue_of(store: DataStore) -> dict[str, ReviewItem]:
    return {r.id: r for r in store.read_review_queue()}


def test_approve_publishes_and_reject_keeps_off_the_site(tmp_path: Path) -> None:
    store, (a, b, c), body = setup(tmp_path)
    body = tick(tick(body, rid(a), "approve"), rid(b), "reject")
    result = apply(store, body)
    assert states(store) == {
        "Campus talk 1": "published",
        "Campus talk 2": "rejected",
        "Campus talk 3": "pending_review",
    }
    q = queue_of(store)
    assert (q[rid(a)].decision, q[rid(a)].decided_in_pr) == ("approved", 42)
    assert (q[rid(b)].decision, q[rid(b)].decided_in_pr) == ("rejected", 42)
    assert q[rid(c)].decision == "pending"
    assert (len(result.approved), len(result.rejected), result.still_pending) == (1, 1, 1)


def test_both_or_neither_ticked_stays_pending(tmp_path: Path) -> None:
    store, (a, _, _), body = setup(tmp_path)
    apply(store, tick(body, rid(a), "approve", "reject"))
    assert all(r.decision == "pending" for r in store.read_review_queue())
    assert set(states(store).values()) == {"pending_review"}


def test_nothing_ticked_writes_nothing(tmp_path: Path) -> None:
    store, _, body = setup(tmp_path)
    before = {p: p.read_bytes() for p in sorted(store.root.rglob("*")) if p.is_file()}
    apply(store, body)
    after = {p: p.read_bytes() for p in sorted(store.root.rglob("*")) if p.is_file()}
    assert after == before


def test_ticks_for_ids_outside_the_snapshot_are_ignored(tmp_path: Path) -> None:
    # Someone edits the description to add a block for an item the PR didn't list.
    store, (a, b, _), body = setup(tmp_path)
    smuggled = f"\n**Event** · `Campus talk 2` — later · Omaha · x · `{rid(b)}`\n- [x] approve\n"
    result = apply(store, body + smuggled, open_ids=[rid(a)])
    assert result.ignored == [rid(b)]
    assert states(store)["Campus talk 2"] == "pending_review"


def test_already_decided_and_unknown_ids_are_ignored(tmp_path: Path) -> None:
    store, (a, _, _), body = setup(tmp_path)
    apply(store, tick(body, rid(a), "approve"))
    # The same merged PR applied again (or an old one re-run): nothing changes.
    second = apply(store, tick(body, rid(a), "reject"))
    assert second.ignored == [rid(a)]
    assert states(store)["Campus talk 1"] == "published"
    unknown = "\n**Event** · `x` — y · `rev_ffffffffffff`\n- [x] approve\n"
    assert apply(store, body + unknown, open_ids=["rev_ffffffffffff"]).ignored == [
        "rev_ffffffffffff"
    ]


# --- Source counts and trust (FR-018)


def source_after(store: DataStore) -> Source:
    (source,) = store.read_sources()
    return source


def approve_all(store: DataStore, events: list[Event], body: str, *rejects: int) -> None:
    for i, event in enumerate(events):
        body = tick(body, rid(event), "reject" if i in rejects else "approve")
    apply(store, body)


def test_three_approvals_and_no_rejections_promote_a_probationary_source(
    tmp_path: Path,
) -> None:
    store, events, body = setup(tmp_path)
    approve_all(store, events, body)
    source = source_after(store)
    assert (source.approved_count, source.rejected_count) == (3, 0)
    assert source.trust == "trusted"
    assert source.status == "active"
    assert source.updated_at == NOW.date()


def test_two_approvals_are_not_enough(tmp_path: Path) -> None:
    store, events, body = setup(tmp_path, n=2)
    approve_all(store, events, body)
    assert source_after(store).trust == "probationary"


def test_any_rejection_keeps_the_source_probationary(tmp_path: Path) -> None:
    store, events, body = setup(tmp_path, n=4)
    approve_all(store, events, body, 3)
    source = source_after(store)
    assert (source.approved_count, source.rejected_count) == (3, 1)
    assert (source.trust, source.status) == ("probationary", "active")


def test_more_rejections_than_approvals_pause_the_source(tmp_path: Path) -> None:
    store, events, body = setup(tmp_path)
    approve_all(store, events, body, 1, 2)
    source = source_after(store)
    assert (source.approved_count, source.rejected_count) == (1, 2)
    assert (source.trust, source.status) == ("probationary", "paused")


def test_a_trusted_source_is_counted_but_never_paused(tmp_path: Path) -> None:
    store, events, body = setup(tmp_path, trust="trusted")
    approve_all(store, events, body, 0, 1, 2)
    source = source_after(store)
    assert source.rejected_count == 3
    assert (source.trust, source.status) == ("trusted", "active")


def test_counts_build_on_earlier_reviews(tmp_path: Path) -> None:
    store, events, body = setup(tmp_path, n=1, approved_count=2)
    approve_all(store, events, body)
    assert source_after(store).trust == "trusted"


# --- The command, end to end


def write_inputs(tmp_path: Path, pr: dict[str, Any]) -> list[str]:
    paths = {"pr": pr, "permission": PERMISSION, "edits": EDITS}
    args: list[str] = []
    for name, data in paths.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        args += [f"--{name}", str(path)]
    return args


def test_the_command_applies_a_valid_merge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, (a, b, _), body = setup(tmp_path)
    pr = {**PR, "body": tick(tick(body, rid(a), "approve"), rid(b), "reject")}
    report = tmp_path / "report.md"
    code = main(["apply-review", "--data-dir", str(store.root), "--commit", SHA,
                 "--bot-login", BOT, "--report", str(report), "--now", "2026-10-19T14:01:00Z",
                 *write_inputs(tmp_path, pr)])  # fmt: skip
    assert code == 0, capsys.readouterr().err
    assert "1 approved, 1 rejected, 1 left waiting" in capsys.readouterr().out
    assert main(["validate-data", "--data-dir", str(store.root)]) == 0
    text = report.read_text(encoding="utf-8")
    assert text.startswith("## Decisions from review PR #42\n")
    assert "### Approved (published)\n\n- `Campus talk 1`" in text
    assert "### Rejected (kept off the site)\n\n- `Campus talk 2`" in text


def test_the_command_changes_nothing_when_the_check_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, (a, _, _), body = setup(tmp_path)
    pr = {**changed(PR, "user.login", "timbertino1"), "body": tick(body, rid(a), "approve")}
    before = {p: p.read_bytes() for p in sorted(store.root.rglob("*")) if p.is_file()}
    code = main(["apply-review", "--data-dir", str(store.root), "--commit", SHA,
                 "--bot-login", BOT, *write_inputs(tmp_path, pr)])  # fmt: skip
    assert code == 1
    assert "not applied: the PR was not opened by" in capsys.readouterr().err
    after = {p: p.read_bytes() for p in sorted(store.root.rglob("*")) if p.is_file()}
    assert after == before
