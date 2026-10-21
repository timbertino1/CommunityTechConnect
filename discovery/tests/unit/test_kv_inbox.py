"""The newsletter inbox in Cloudflare Workers KV, read through the KV REST API (T098; research
R8, contracts/workers.md section 2). The API is mocked; nothing leaves the machine."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import httpx
import pytest

from netc.fetch.api import SafeApi
from netc.inbox.kv import KV_API, MAX_MESSAGE_BYTES, InboxError, KvInbox

pytestmark = pytest.mark.unit

ACCOUNT = "0123456789abcdef0123456789abcdef"
NAMESPACE = "fedcba9876543210fedcba9876543210"
TOKEN = "test-kv-token-not-real"
ENV = {
    "CLOUDFLARE_ACCOUNT_ID": ACCOUNT,
    "NEWSLETTERS_KV_ID": NAMESPACE,
    "CLOUDFLARE_KV_TOKEN": TOKEN,
}
BASE = f"{KV_API}/accounts/{ACCOUNT}/storage/kv/namespaces/{NAMESPACE}"
RAW = b"Subject: hello\r\n\r\nRust Night, Nov 18\r\n"
KEY = hashlib.sha256(RAW).hexdigest()

Handler = Callable[[httpx.Request], httpx.Response]


def inbox(handler: Handler, seen: list[httpx.Request] | None = None) -> KvInbox:
    def record(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    return KvInbox.from_env(SafeApi(transport=httpx.MockTransport(record)), ENV)


def listing(names: list[str], cursor: str = "") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "success": True,
            "errors": [],
            "result": [{"name": n, "expiration": 1_795_000_000} for n in names],
            "result_info": {"count": len(names), "cursor": cursor},
        },
    )


# --- Configuration


def test_namespace_and_account_come_from_the_environment() -> None:
    seen: list[httpx.Request] = []
    inbox(lambda r: listing([]), seen).keys()
    [request] = seen
    assert str(request.url).startswith(f"{BASE}/keys")
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("missing", sorted(ENV))
def test_each_setting_is_required(missing: str) -> None:
    env = {k: v for k, v in ENV.items() if k != missing}
    with pytest.raises(InboxError, match=missing):
        KvInbox.from_env(SafeApi(), env)


@pytest.mark.parametrize("bad", ["REPLACE_WITH_NEWSLETTERS_KV_ID", "../../accounts", "abc"])
def test_ids_must_look_like_cloudflare_ids(bad: str) -> None:
    with pytest.raises(InboxError, match="NEWSLETTERS_KV_ID"):
        KvInbox.from_env(SafeApi(), {**ENV, "NEWSLETTERS_KV_ID": bad})


# --- List, read, delete


def test_keys_are_listed_across_pages() -> None:
    other = "a" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "page2":
            return listing([other])
        return listing([KEY], cursor="page2")

    assert inbox(handler).keys() == [KEY, other]


def test_keys_the_worker_could_not_have_written_are_ignored() -> None:
    names = [KEY, "not-a-hash", "../" + "a" * 61, KEY.upper()]
    assert inbox(lambda r: listing(names)).keys() == [KEY]


def test_a_message_is_read_as_raw_bytes() -> None:
    seen: list[httpx.Request] = []
    raw = inbox(lambda r: httpx.Response(200, content=RAW), seen).read(KEY)
    assert raw == RAW
    [request] = seen
    assert request.method == "GET" and str(request.url) == f"{BASE}/values/{KEY}"


def test_a_message_already_gone_reads_as_none() -> None:
    gone = httpx.Response(404, json={"success": False, "errors": [{"code": 10009}]})
    assert inbox(lambda r: gone).read(KEY) is None


def test_a_message_over_the_cap_is_refused() -> None:
    big = httpx.Response(200, content=b"x" * (MAX_MESSAGE_BYTES + 1))
    with pytest.raises(InboxError):
        inbox(lambda r: big).read(KEY)


def test_a_message_is_deleted_by_its_key() -> None:
    seen: list[httpx.Request] = []
    inbox(lambda r: httpx.Response(200, json={"success": True}), seen).delete(KEY)
    [request] = seen
    assert request.method == "DELETE" and str(request.url) == f"{BASE}/values/{KEY}"


@pytest.mark.parametrize("key", ["../keys", "x" * 64, ""])
def test_only_message_hashes_are_read_or_deleted(key: str) -> None:
    seen: list[httpx.Request] = []
    box = inbox(lambda r: httpx.Response(200, content=RAW), seen)
    with pytest.raises(InboxError):
        box.read(key)
    with pytest.raises(InboxError):
        box.delete(key)
    assert seen == []


@pytest.mark.parametrize(
    ("call", "response"),
    [
        ("keys", httpx.Response(403, json={"success": False, "errors": [{"message": TOKEN}]})),
        ("keys", httpx.Response(200, json={"success": False})),
        ("read", httpx.Response(500, content=b"oops")),
        ("delete", httpx.Response(403, json={"success": False})),
    ],
)
def test_errors_raise_without_the_token(call: str, response: httpx.Response) -> None:
    box = inbox(lambda r: response)
    with pytest.raises(InboxError) as caught:
        getattr(box, call)(*([] if call == "keys" else [KEY]))
    assert TOKEN not in str(caught.value)
