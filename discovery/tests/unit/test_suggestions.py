"""Visitor suggestions from the suggest Worker's KV namespace (T133; FR-020, FR-022,
contracts/workers.md section 1). The KV API is mocked; nothing leaves the machine."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from netc.fetch.api import SafeApi
from netc.inbox.kv import KV_API, InboxError, KvInbox
from netc.inbox.suggestions import MAX_SUGGESTIONS, read_suggestions

pytestmark = pytest.mark.unit

ACCOUNT = "0123456789abcdef0123456789abcdef"
NAMESPACE = "9df218ecf9ea43acbea671744abdfa67"
ENV = {
    "CLOUDFLARE_ACCOUNT_ID": ACCOUNT,
    "SUGGESTIONS_KV_ID": NAMESPACE,
    "CLOUDFLARE_KV_TOKEN": "test-kv-token-not-real",
}
BASE = f"{KV_API}/accounts/{ACCOUNT}/storage/kv/namespaces/{NAMESPACE}"
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
KEY = "suggestion:0f8fad5b-d9cb-469f-a165-70867728950e"
KEY2 = "suggestion:7c9e6679-7425-40de-944b-e07fc1f90ae7"

Handler = Callable[[httpx.Request], httpx.Response]


class FakeInbox:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = dict(values)
        self.deleted: list[str] = []

    def keys(self) -> list[str]:
        return list(self.values)

    def read(self, key: str) -> bytes | None:
        return self.values.get(key)

    def delete(self, key: str) -> None:
        self.deleted.append(key)


def record(url: str, note: str = "", **extra: object) -> bytes:
    return json.dumps(
        {"url": url, "note": note, "received_at": "2026-10-24T01:20:00Z", **extra}
    ).encode()


# --- Reading the namespace


def kv(handler: Handler, seen: list[httpx.Request] | None = None) -> KvInbox:
    def log(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    return KvInbox.suggestions_from_env(SafeApi(transport=httpx.MockTransport(log)), ENV)


def test_only_suggestion_keys_are_listed_never_the_rate_counters() -> None:
    seen: list[httpx.Request] = []
    names = [KEY, "rate:" + "a" * 64, "suggestion:not-a-uuid", KEY2]
    listing = {
        "success": True,
        "result": [{"name": n} for n in names],
        "result_info": {"cursor": ""},
    }
    keys = kv(lambda r: httpx.Response(200, json=listing), seen).keys()
    assert keys == [KEY, KEY2]
    assert str(seen[0].url).startswith(f"{BASE}/keys")
    assert seen[0].url.params["prefix"] == "suggestion:"


def test_a_suggestion_is_read_and_deleted_by_its_encoded_key() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={"success": True, "result": None})
        return httpx.Response(200, content=record("https://example.org/"))

    inbox = kv(answer, seen)
    assert inbox.read(KEY) == record("https://example.org/")
    inbox.delete(KEY)
    assert [r.method for r in seen] == ["GET", "DELETE"]
    assert all(str(r.url) == f"{BASE}/values/suggestion%3A{KEY.split(':')[1]}" for r in seen)


@pytest.mark.parametrize("key", ["rate:" + "a" * 64, "suggestion:../../x", "a" * 64])
def test_nothing_but_a_suggestion_key_is_ever_read_or_deleted(key: str) -> None:
    inbox = kv(lambda r: httpx.Response(500))
    with pytest.raises(InboxError):
        inbox.read(key)
    with pytest.raises(InboxError):
        inbox.delete(key)


def test_the_namespace_id_is_required() -> None:
    env = {k: v for k, v in ENV.items() if k != "SUGGESTIONS_KV_ID"}
    with pytest.raises(InboxError, match="SUGGESTIONS_KV_ID"):
        KvInbox.suggestions_from_env(SafeApi(), env)


# --- Turning suggestions into candidates


def test_a_suggestion_becomes_a_candidate_with_its_note_in_memory_only() -> None:
    inbox = FakeInbox({KEY: record("https://technologynebraska.com/events/", "They meet monthly.")})
    found = read_suggestions(inbox, now=NOW)
    [candidate] = found.candidates
    assert candidate.url == "https://technologynebraska.com/events/"
    assert candidate.found_via == "suggestion"
    assert candidate.result == "pending"
    assert candidate.note == "They meet monthly."
    assert "note" not in candidate.model_dump(mode="json")
    assert "monthly" not in json.dumps(candidate.model_dump(mode="json"))
    assert found.done == [KEY]


def test_the_note_is_scrubbed_again() -> None:
    note = "Ask jane@example.com or 402-555-0142. Monthly."
    inbox = FakeInbox({KEY: record("https://example.org/events", note)})
    [candidate] = read_suggestions(inbox, now=NOW).candidates
    assert candidate.note is not None
    assert "jane" not in candidate.note and "555" not in candidate.note
    assert "Monthly." in candidate.note


def test_a_platform_page_is_tidied_like_any_other_candidate() -> None:
    inbox = FakeInbox({KEY: record("https://meetup.com/Omaha-Rust/events/316700840/?utm=x")})
    [candidate] = read_suggestions(inbox, now=NOW).candidates
    assert candidate.url == "https://www.meetup.com/omaha-rust/"


def test_an_address_that_is_not_a_source_page_goes_to_review_not_to_evaluation() -> None:
    inbox = FakeInbox({KEY: record("https://www.facebook.com/somegroup")})
    found = read_suggestions(inbox, now=NOW)
    assert found.candidates == []
    assert [(s.url, s.reason) for s in found.for_review] == [
        ("https://www.facebook.com/somegroup", "suggested, but not a page we can read events from")
    ]
    assert found.done == [KEY]


@pytest.mark.parametrize(
    "value",
    [b"not json", b"[]", record("http://plain.example.org/"), record("javascript:alert(1)"),
     json.dumps({"note": "no url"}).encode()],
)  # fmt: skip
def test_broken_records_are_dropped_and_deleted(value: bytes) -> None:
    inbox = FakeInbox({KEY: value})
    found = read_suggestions(inbox, now=NOW)
    assert found.candidates == [] and found.for_review == []
    assert found.done == [KEY]


def test_a_record_that_cannot_be_read_now_is_kept_for_next_time() -> None:
    class Flaky(FakeInbox):
        def read(self, key: str) -> bytes | None:
            raise InboxError("HTTP 503")

    found = read_suggestions(Flaky({KEY: record("https://example.org/")}), now=NOW)
    assert found.candidates == [] and found.done == []


def test_the_same_site_suggested_twice_is_one_candidate() -> None:
    inbox = FakeInbox(
        {KEY: record("https://example.org/events"), KEY2: record("https://example.org/events")}
    )
    found = read_suggestions(inbox, now=NOW)
    assert len(found.candidates) == 1
    assert sorted(found.done) == sorted([KEY, KEY2])


def test_at_most_a_run_s_worth_are_read() -> None:
    values = {
        f"suggestion:{i:08d}-0000-4000-8000-000000000000": record(f"https://e{i}.example.org/")
        for i in range(80)
    }
    found = read_suggestions(FakeInbox(values), now=NOW)
    assert len(found.candidates) == MAX_SUGGESTIONS
    assert len(found.done) == MAX_SUGGESTIONS  # the rest wait in KV for the next run
