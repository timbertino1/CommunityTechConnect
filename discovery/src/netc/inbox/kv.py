"""Workers KV, read through the Cloudflare KV REST API: the newsletter inbox (raw emails the
inbox Worker stored; T099, research R8, contracts/workers.md section 2) and visitors'
suggestions (the suggest Worker's records; T133, contracts/workers.md section 1).

Only the keys each Worker writes are ever listed, read or deleted: sha256(raw) for newsletters,
suggestion:<uuid> for suggestions (never the suggest Worker's rate: counters). An item is
deleted only once what came of it is written (discover_sources does that). The token is sent
only in the Authorization header and never appears in an error.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Final, Protocol
from urllib.parse import quote

from netc.fetch import FetchError
from netc.fetch.api import SafeApi

KV_API: Final = "https://api.cloudflare.com/client/v4"
MAX_MESSAGE_BYTES: Final = 1024 * 1024  # the Worker drops anything larger
MAX_KEYS: Final = 1000  # one page; far more than a month of newsletters
_CLOUDFLARE_ID: Final = re.compile(r"[0-9a-f]{32}")
_MESSAGE_KEY: Final = re.compile(r"[0-9a-f]{64}")
SUGGESTION_PREFIX: Final = "suggestion:"
_SUGGESTION_KEY: Final = re.compile(
    r"suggestion:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
MAX_SUGGESTION_BYTES: Final = 8 * 1024  # the Worker takes at most 4 KB


class InboxError(Exception):
    """The inbox couldn't be read or changed; the message stays for the next run."""


class Inbox(Protocol):
    def keys(self) -> list[str]: ...

    def read(self, key: str) -> bytes | None: ...

    def delete(self, key: str) -> None: ...


class KvInbox:
    def __init__(
        self,
        api: SafeApi,
        *,
        account_id: str,
        namespace_id: str,
        token: str,
        key_pattern: re.Pattern[str] = _MESSAGE_KEY,
        prefix: str = "",
        max_bytes: int = MAX_MESSAGE_BYTES,
    ) -> None:
        self._api = api
        self._base = f"{KV_API}/accounts/{account_id}/storage/kv/namespaces/{namespace_id}"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._key = key_pattern
        self._prefix = prefix
        self._max_bytes = max_bytes

    @classmethod
    def from_env(cls, api: SafeApi, env: Mapping[str, str] = os.environ) -> KvInbox:
        """The newsletter inbox (NEWSLETTERS_KV_ID)."""
        account, namespace, token = _settings(env, "NEWSLETTERS_KV_ID")
        return cls(api, account_id=account, namespace_id=namespace, token=token)

    @classmethod
    def suggestions_from_env(cls, api: SafeApi, env: Mapping[str, str] = os.environ) -> KvInbox:
        """Visitors' suggestions (SUGGESTIONS_KV_ID): only suggestion:<uuid> keys."""
        account, namespace, token = _settings(env, "SUGGESTIONS_KV_ID")
        return cls(
            api,
            account_id=account,
            namespace_id=namespace,
            token=token,
            key_pattern=_SUGGESTION_KEY,
            prefix=SUGGESTION_PREFIX,
            max_bytes=MAX_SUGGESTION_BYTES,
        )

    def keys(self) -> list[str]:
        found: list[str] = []
        cursor = ""
        while len(found) < MAX_KEYS:
            url = f"{self._base}/keys?limit={MAX_KEYS}" + (f"&cursor={cursor}" if cursor else "")
            if self._prefix:
                url += f"&prefix={quote(self._prefix, safe='')}"
            data = self._json(self._call("GET", url, "list the inbox"), "list the inbox")
            result, info = data.get("result"), data.get("result_info")
            if not isinstance(result, list):
                raise InboxError("the inbox listing was not understood")
            for item in result:
                name = item.get("name") if isinstance(item, dict) else None
                if isinstance(name, str) and self._key.fullmatch(name):
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
        if not self._key.fullmatch(key):
            raise InboxError("not a key this inbox reads")
        return f"{self._base}/values/{quote(key, safe='')}"

    def _call(self, method: str, url: str, doing: str) -> tuple[int, bytes]:
        try:
            if method == "DELETE":
                response = self._api.delete(url, headers=self._headers)
            else:
                response = self._api.get(url, headers=self._headers, max_bytes=self._max_bytes)
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


def _settings(env: Mapping[str, str], namespace_var: str) -> tuple[str, str, str]:
    """The account id, the namespace id and the token, checked."""
    values: dict[str, str] = {}
    for name in ("CLOUDFLARE_ACCOUNT_ID", namespace_var, "CLOUDFLARE_KV_TOKEN"):
        value = env.get(name, "").strip()
        if not value:
            raise InboxError(f"{name} is not set")
        if name != "CLOUDFLARE_KV_TOKEN" and not _CLOUDFLARE_ID.fullmatch(value):
            raise InboxError(f"{name} is not a Cloudflare id")
        values[name] = value
    return values["CLOUDFLARE_ACCOUNT_ID"], values[namespace_var], values["CLOUDFLARE_KV_TOKEN"]
