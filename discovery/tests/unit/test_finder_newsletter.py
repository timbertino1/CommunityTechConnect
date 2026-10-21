"""The newsletter finder: emails from the inbox become event mentions, and each message is
deleted from the inbox only after its mentions are safely written (T098-T099; research R8)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from netc.connectors import default_connectors
from netc.fetch import FixtureHttp
from netc.finders.base import FinderContext
from netc.finders.newsletter import MAX_MESSAGES_PER_RUN, NewsletterFinder
from netc.inbox.kv import InboxError
from netc.models import AreaConfig
from netc.pipeline.discover_sources import discover_sources
from netc.storage import DataStore
from tests.ai_support import EMAILS, NOW, ScriptedClient, ai

pytestmark = pytest.mark.unit

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
AREAS: AreaConfig = DataStore(REPO_DATA).read_areas()  # type: ignore[assignment]
BASIC = (EMAILS / "newsletter_basic.eml").read_bytes()
KEY = hashlib.sha256(BASIC).hexdigest()
RUST = {
    "mentions": [
        {
            "title": "Rust Night",
            "date_hint": "Wed Nov 18",
            "place_hint": "Kiewit Luminarium, Omaha",
            "organizer_hint": "Heartland Rust Users",
            "links": ["https://heartlandrust.example.org/events/rust-night-nov"],
        }
    ]
}


class MemoryInbox:
    def __init__(self, items: dict[str, bytes], *, fail: str | None = None) -> None:
        self.items = dict(items)
        self.fail = fail
        self.reads: list[str] = []
        self.deleted: list[str] = []

    def keys(self) -> list[str]:
        if self.fail == "keys":
            raise InboxError("listing failed")
        return list(self.items)

    def read(self, key: str) -> bytes | None:
        if self.fail == "read":
            raise InboxError("read failed")
        self.reads.append(key)
        return self.items.get(key)

    def delete(self, key: str) -> None:
        if self.fail == "delete":
            raise InboxError("delete failed")
        self.deleted.append(key)
        self.items.pop(key, None)


def ctx(tmp_path: Path, client: ScriptedClient | None) -> FinderContext:
    service = ai(tmp_path, client) if client is not None else None
    return FinderContext(now=NOW, areas=AREAS, ai=service)


def test_an_email_becomes_mentions_and_is_marked_processed(tmp_path: Path) -> None:
    client = ScriptedClient(RUST)
    result = NewsletterFinder(MemoryInbox({KEY: BASIC})).run(ctx(tmp_path, client))
    [mention] = result.mentions
    assert mention.channel == "newsletter" and mention.title == "Rust Night"
    assert mention.links == ["https://heartlandrust.example.org/events/rust-night-nov"]
    assert result.processed_messages == [KEY]
    assert result.stats["processed"] == 1
    assert "Rust Night" in client.calls[0]["data"]


def test_the_finder_itself_never_deletes(tmp_path: Path) -> None:
    box = MemoryInbox({KEY: BASIC})
    NewsletterFinder(box).run(ctx(tmp_path, ScriptedClient(RUST)))
    assert box.deleted == []


def test_without_an_inbox_or_the_ai_nothing_is_read(tmp_path: Path) -> None:
    assert NewsletterFinder(None).run(ctx(tmp_path, None)).stats["skipped_no_inbox"] == 1
    box = MemoryInbox({KEY: BASIC})
    result = NewsletterFinder(box).run(ctx(tmp_path, None))
    assert result.stats["skipped_no_ai"] == 1
    assert box.reads == [] and result.processed_messages == []


def test_an_unusable_ai_answer_leaves_the_email_for_next_time(tmp_path: Path) -> None:
    result = NewsletterFinder(MemoryInbox({KEY: BASIC})).run(ctx(tmp_path, ScriptedClient(None)))
    assert result.processed_messages == [] and result.stats["ai_unusable"] == 1


def test_inbox_errors_are_counted_and_leave_the_email(tmp_path: Path) -> None:
    for fail in ("keys", "read"):
        box = MemoryInbox({KEY: BASIC}, fail=fail)
        result = NewsletterFinder(box).run(ctx(tmp_path, ScriptedClient(RUST)))
        assert result.stats["errors"] == 1 and result.processed_messages == [], fail


def test_an_item_whose_key_is_not_its_hash_is_discarded_unread(tmp_path: Path) -> None:
    client = ScriptedClient(RUST)
    result = NewsletterFinder(MemoryInbox({"a" * 64: BASIC})).run(ctx(tmp_path, client))
    assert client.calls == [] and result.mentions == []
    assert result.processed_messages == ["a" * 64] and result.stats["bad_hash"] == 1


def test_an_email_sent_twice_costs_one_ai_call(tmp_path: Path) -> None:
    client = ScriptedClient(RUST)
    service = ctx(tmp_path, client)
    NewsletterFinder(MemoryInbox({KEY: BASIC})).run(service)
    again = NewsletterFinder(MemoryInbox({KEY: BASIC})).run(service)
    assert len(client.calls) == 1 and again.processed_messages == [KEY]


def test_a_run_reads_a_limited_number_of_emails(tmp_path: Path) -> None:
    items = {}
    for i in range(MAX_MESSAGES_PER_RUN + 3):
        raw = BASIC + f"\n{i}\n".encode()
        items[hashlib.sha256(raw).hexdigest()] = raw
    client = ScriptedClient(*[{"mentions": []}] * len(items))
    result = NewsletterFinder(MemoryInbox(items)).run(ctx(tmp_path, client))
    assert len(result.processed_messages) == MAX_MESSAGES_PER_RUN
    assert result.stats["left_for_later"] == 3


# --- In discover-sources


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    for name in ("categories.yaml", "areas.yaml"):
        shutil.copy(REPO_DATA / name, root / name)
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.json").write_text("{}", encoding="utf-8")
    return root


def run(data: Path, box: MemoryInbox, *, dry_run: bool = False):  # type: ignore[no-untyped-def]
    return discover_sources(
        DataStore(data),
        FixtureHttp(data.parent / "pages"),
        default_connectors(lambda: NOW),
        now=NOW,
        ai=ai(data, ScriptedClient(RUST)),
        finders=[NewsletterFinder(box)],
        inbox=box,
        dry_run=dry_run,
    )


def test_processed_emails_are_deleted_after_the_data_is_written(data: Path) -> None:
    box = MemoryInbox({KEY: BASIC})
    report = run(data, box)
    assert box.deleted == [KEY] and report.inbox_deleted == 1
    assert [m.title for m in DataStore(data).read_mentions()] == ["Rust Night"]


def test_a_dry_run_deletes_nothing(data: Path) -> None:
    box = MemoryInbox({KEY: BASIC})
    report = run(data, box, dry_run=True)
    assert box.deleted == [] and report.inbox_deleted == 0


def test_a_failed_delete_is_counted_and_does_not_stop_the_run(data: Path) -> None:
    box = MemoryInbox({KEY: BASIC}, fail="delete")
    report = run(data, box)
    assert report.written and report.inbox_delete_errors == 1
