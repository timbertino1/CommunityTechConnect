"""`netc health-issue`: the files the health issue script posts (T124)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from netc.cli import main
from netc.storage import DataStore
from tests.data_samples import make_status, utc
from tests.review_support import campus_source, held_event, make_review_data, queue_item

pytestmark = pytest.mark.integration

NOW = "2026-10-19T11:00:00Z"


def run(data: Path, out: Path, *extra: str) -> int:
    return main(
        ["health-issue", "--data-dir", str(data), "--out", str(out), "--owner", "timbertino1",
         "--now", NOW, *extra]
    )  # fmt: skip


def failing_store(root: Path) -> DataStore:
    store = make_review_data(root, [], [])
    status = make_status(last_attempt=utc(2026, 10, 19, 11), consecutive_failures=3,
                         last_error="TimeoutError: timed out")  # fmt: skip
    store.write_source_status({"src_campus": status})
    return store


def test_a_healthy_run_writes_the_body_and_no_comment(tmp_path: Path) -> None:
    store = make_review_data(tmp_path / "data", [], [])
    out = tmp_path / "out"
    assert run(store.root, out) == 0
    body = (out / "body.md").read_text(encoding="utf-8")
    assert "| Campus computing | active | probationary | added by the owner |" in body
    assert "Nothing needs attention." in body
    assert not (out / "comment.md").exists()


def test_a_problem_writes_an_alert_comment(tmp_path: Path) -> None:
    store = failing_store(tmp_path / "data")
    out = tmp_path / "out"
    assert run(store.root, out) == 0
    comment = (out / "comment.md").read_text(encoding="utf-8")
    assert comment.startswith("@timbertino1 the discovery bot needs your attention:")
    assert "<!-- netc-health-alert: failing:src_campus -->" in comment


def test_a_recent_alert_suppresses_the_comment(tmp_path: Path) -> None:
    store = failing_store(tmp_path / "data")
    out = tmp_path / "out"
    out.mkdir()
    (out / "comment.md").write_text("stale from an earlier run", encoding="utf-8")
    last = tmp_path / "last.json"
    last.write_text(
        json.dumps({"created_at": "2026-10-19T01:00:00Z",
                    "body": "<!-- netc-health-alert: failing:src_campus -->"}),
        encoding="utf-8",
    )  # fmt: skip
    assert run(store.root, out, "--last-alert", str(last)) == 0
    assert not (out / "comment.md").exists()


def test_an_empty_last_alert_file_means_none(tmp_path: Path) -> None:
    store = failing_store(tmp_path / "data")
    last = tmp_path / "last.json"
    last.write_text("", encoding="utf-8")
    out = tmp_path / "out"
    assert run(store.root, out, "--last-alert", str(last)) == 0
    assert (out / "comment.md").exists()


def test_pending_review_items_are_counted(tmp_path: Path) -> None:
    events = [held_event(3)]
    store = make_review_data(tmp_path / "data", events, [queue_item(events[0])])
    out = tmp_path / "out"
    assert run(store.root, out) == 0
    assert "1 item is waiting in the review PR" in (out / "body.md").read_text(encoding="utf-8")


def test_previous_status_shows_how_old_mains_data_was(tmp_path: Path) -> None:
    store = make_review_data(tmp_path / "data", [], [], sources=[campus_source()])
    previous = tmp_path / "previous.json"
    previous.write_text(
        json.dumps({"src_campus": {"last_attempt": "2026-10-17T11:00:00Z",
                                   "consecutive_failures": 0}}),
        encoding="utf-8",
    )  # fmt: skip
    out = tmp_path / "out"
    assert run(store.root, out, "--previous-status", str(previous)) == 0
    assert "48 hours" in (out / "body.md").read_text(encoding="utf-8")
    assert (out / "comment.md").exists()


def test_an_unreadable_previous_status_is_ignored(tmp_path: Path) -> None:
    store = make_review_data(tmp_path / "data", [], [])
    previous = tmp_path / "previous.json"
    previous.write_text("not json", encoding="utf-8")
    out = tmp_path / "out"
    assert run(store.root, out, "--previous-status", str(previous)) == 0
    assert "No earlier run is recorded." in (out / "body.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    ['["not", "an", "object"]', '{"created_at": "2026-10-19T01:00:00", "body": "x"}', "{oops"],
)
def test_a_malformed_last_alert_fails(tmp_path: Path, content: str) -> None:
    store = failing_store(tmp_path / "data")
    last = tmp_path / "last.json"
    last.write_text(content, encoding="utf-8")
    assert run(store.root, tmp_path / "out", "--last-alert", str(last)) == 1


def test_a_bad_owner_fails(tmp_path: Path) -> None:
    store = failing_store(tmp_path / "data")
    out = tmp_path / "out"
    code = main(["health-issue", "--data-dir", str(store.root), "--out", str(out),
                 "--owner", "not a login", "--now", NOW])  # fmt: skip
    assert code == 1
