"""`netc review-pr`: the files the review PR script commits and posts (T120, T122)."""

from __future__ import annotations

from pathlib import Path

import pytest

from netc.cli import main
from netc.storage import DataStore
from tests.review_support import held_event, make_review_data, queue_item, tick

pytestmark = pytest.mark.integration

NOW = "2026-10-19T11:00:00Z"


def run(data: Path, out: Path, *extra: str) -> int:
    return main(["review-pr", "--data-dir", str(data), "--out", str(out), "--now", NOW, *extra])


def test_pending_items_produce_a_title_body_and_snapshot(tmp_path: Path) -> None:
    events = [held_event(3), held_event(4)]
    queue = [queue_item(e) for e in events]
    store = make_review_data(tmp_path / "data", events, queue, open_ids=[])
    out = tmp_path / "out"
    assert run(store.root, out) == 0
    assert (out / "status").read_text(encoding="utf-8") == "ready\n"
    assert (out / "title.txt").read_text(encoding="utf-8") == "Review: 2 items (events)\n"
    assert "`Campus talk 3`" in (out / "body.md").read_text(encoding="utf-8")
    assert DataStore(store.root).read_review_open() == sorted(q.id for q in queue)
    assert main(["validate-data", "--data-dir", str(store.root)]) == 0


def test_nothing_pending_writes_no_pr_files(tmp_path: Path) -> None:
    store = make_review_data(tmp_path / "data", [], [], open_ids=[])
    out = tmp_path / "out"
    assert run(store.root, out) == 0
    assert (out / "status").read_text(encoding="utf-8") == "none\n"
    assert not (out / "body.md").exists()


def test_an_open_pr_with_ticks_is_left_alone(tmp_path: Path) -> None:
    events = [held_event(3)]
    queue = [queue_item(e) for e in events]
    store = make_review_data(tmp_path / "data", events, queue, open_ids=[])
    first = tmp_path / "first"
    run(store.root, first)
    current = tmp_path / "current.md"
    body = (first / "body.md").read_text(encoding="utf-8")
    current.write_text(tick(body, queue[0].id, "approve"), encoding="utf-8")
    out = tmp_path / "out"
    assert run(store.root, out, "--current-body", str(current)) == 0
    assert (out / "status").read_text(encoding="utf-8") == "kept\n"
    assert not (out / "body.md").exists()


def test_an_open_pr_without_ticks_is_rebuilt(tmp_path: Path) -> None:
    events = [held_event(3)]
    store = make_review_data(tmp_path / "data", events, [queue_item(events[0])], open_ids=[])
    current = tmp_path / "current.md"
    current.write_text("## 1 item waiting for review\n", encoding="utf-8")
    out = tmp_path / "out"
    assert run(store.root, out, "--current-body", str(current)) == 0
    assert (out / "status").read_text(encoding="utf-8") == "ready\n"
