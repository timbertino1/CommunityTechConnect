"""The newsletter inbox: raw emails the inbox Worker stored in Workers KV (T099; research R8,
contracts/workers.md section 2).

Read through the Cloudflare KV REST API with a token scoped to the NEWSLETTERS namespace. The
Worker keys each message by sha256(raw), so only 64-hex-digit keys are ever listed, read or
deleted. A message is deleted only once its mentions are written (discover_sources does that).
The token is sent only in the Authorization header and never appears in an error.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Final, Protocol

from netc.fetch import FetchError
from netc.fetch.api import SafeApi

KV_API: Final = "https://api.cloudflare.com/client/v4"
MAX_MESSAGE_BYTES: Final = 1024 * 1024  # the Worker drops anything larger
MAX_KEYS: Final = 1000  # one page; far more than a month of newsletters
_CLOUDFLARE_ID: Final = re.compile(r"[0-9a-f]{32}")
_MESSAGE_KEY: Final = re.compile(r"[0-9a-f]{64}")


class InboxError(Exception):
    """The inbox couldn't be read or changed; the message stays for the next run."""


class Inbox(Protocol):
    def keys(self) -> list[str]: ...

    def read(self, key: str) -> bytes | None: ...

    def delete(self, key: str) -> None: ...


class KvInbox:
    def __init__(self, api: SafeApi, *, account_id: str, namespace_id: str, token: str) -> None:
        self._api = api
        self._base = f"{KV_API}/accounts/{account_id}/storage/kv/namespaces/{namespace_id}"
        self._headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def from_env(cls, api: SafeApi, env: Mapping[str, str] = os.environ) -> KvInbox:
        settings: dict[str, str] = {}
        for name in ("CLOUDFLARE_ACCOUNT_ID", "NEWSLETTERS_KV_ID", "CLOUDFLARE_KV_TOKEN"):
            value = env.get(name, "").strip()
            if not value:
                raise InboxError(f"{name} is not set")
            if name != "CLOUDFLARE_KV_TOKEN" and not _CLOUDFLARE_ID.fullmatch(value):
                raise InboxError(f"{name} is not a Cloudflare id")
            settings[name] = value
        return cls(
            api,
            account_id=settings["CLOUDFLARE_ACCOUNT_ID"],
            namespace_id=settings["NEWSLETTERS_KV_ID"],
            token=settings["CLOUDFLARE_KV_TOKEN"],
        )

    def keys(self) -> list[str]:
        found: list[str] = []
        cursor = ""
        while len(found) < MAX_KEYS:
            url = f"{self._base}/keys?limit={MAX_KEYS}" + (f"&cursor={cursor}" if cursor else "")
            data = self._json(self._call("GET", url, "list the inbox"), "list the inbox")
            result, info = data.get("result"), data.get("result_info")
            if not isinstance(result, list):
                raise InboxError("the inbox listing was not understood")
            for item in result:
                name = item.get("name") if isinstance(item, dict) else None
                if isinstance(name, str) and _MESSAGE_KEY.fullmatch(name):
                    found.append(name)
            next_cursor = info.get("cursor") if isinstance(info, dict) else None
            if not isinstance(next_cursor, str) or not next_cursor or not result:
                break
            if not re.fullmatch(r"[A-Za-z0-9_\-.~]+", next_cursor):
                raise InboxError("the inbox listing returned an unusable cursor")
            cursor = next_cursor
        return found[:MAX_KEYS]

    def read(self, key: str) -> bytes | None:
        status, content = self._call("GET", self._value_url(key), "read a message")
        if status == 404:
            return None
        if status >= 400:
            raise InboxError(f"reading a message failed (HTTP {status})")
        return content

    def delete(self, key: str) -> None:
        status, content = self._call("DELETE", self._value_url(key), "delete a message")
        if status == 404:
            return
        self._json((status, content), "delete a message")

    def _value_url(self, key: str) -> str:
        if not _MESSAGE_KEY.fullmatch(key):
            raise InboxError("not a message key")
        return f"{self._base}/values/{key}"

    def _call(self, method: str, url: str, doing: str) -> tuple[int, bytes]:
        try:
            if method == "DELETE":
                response = self._api.delete(url, headers=self._headers)
            else:
                response = self._api.get(url, headers=self._headers, max_bytes=MAX_MESSAGE_BYTES)
        except FetchError as exc:
            raise InboxError(f"could not {doing}: {exc}") from None
        return response.status, response.content

    @staticmethod
    def _json(response: tuple[int, bytes], doing: str) -> dict[str, object]:
        status, content = response
        if status >= 400:
            raise InboxError(f"could not {doing} (HTTP {status})")
        try:
            data = json.loads(content)
        except ValueError:
            raise InboxError(f"could not {doing}: not JSON") from None
        if not isinstance(data, dict) or data.get("success") is not True:
            raise InboxError(f"could not {doing}: Cloudflare reported a failure")
        return data
