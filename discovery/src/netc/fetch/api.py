"""A client for the few third-party APIs the pipeline calls with a key (T085; research R12).

SafeHttp is for untrusted pages: GET only, robots.txt, per-host pacing. A search API is the
opposite: one fixed, trusted host that we POST a query to with a secret. This client allows
only the hosts in API_HOSTS, over https on port 443, never follows a redirect (a redirect could
carry the key elsewhere), caps the response size and time, and keeps request headers out of
every error message so the key can't end up in a log.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

import httpx

from netc.fetch.errors import FetchError, FetchTimeoutError, ResponseTooLargeError, UnsafeURLError
from netc.fetch.robots import ROBOTS_USER_AGENT
from netc.fetch.safe_fetch import _ssl_context

API_HOSTS: Final = frozenset({"api.tavily.com"})
MAX_API_BYTES: Final = 1_000_000
API_TIMEOUT: Final = httpx.Timeout(20.0, connect=10.0)


@dataclass(frozen=True)
class ApiResponse:
    status: int
    data: Any
    """Parsed JSON (error statuses included, so callers can say what went wrong)."""


class ApiClient(Protocol):
    def post_json(
        self, url: str, payload: Mapping[str, Any], *, headers: Mapping[str, str]
    ) -> ApiResponse: ...


class SafeApi:
    def __init__(
        self,
        *,
        hosts: frozenset[str] = API_HOSTS,
        transport: httpx.BaseTransport | None = None,
        site_domain: str = "netechconnect.pages.dev",
    ) -> None:
        self._hosts = hosts
        self._user_agent = f"{ROBOTS_USER_AGENT}/1.0 (+https://{site_domain}/about)"
        self._client = httpx.Client(
            transport=transport,
            verify=_ssl_context() if transport is None else True,
            trust_env=False,
            follow_redirects=False,
            timeout=API_TIMEOUT,
        )

    def post_json(
        self, url: str, payload: Mapping[str, Any], *, headers: Mapping[str, str]
    ) -> ApiResponse:
        self._check(url)
        sent = {**headers, "user-agent": self._user_agent, "accept": "application/json"}
        try:
            with self._client.stream("POST", url, json=dict(payload), headers=sent) as response:
                if response.is_redirect:
                    raise FetchError(f"{_host(url)} answered with a redirect; refused")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_API_BYTES:
                        raise ResponseTooLargeError(f"{_host(url)} response too large")
                status = response.status_code
        except httpx.TimeoutException as exc:
            raise FetchTimeoutError(f"{_host(url)} timed out ({type(exc).__name__})") from None
        except httpx.HTTPError as exc:
            # The exception text can quote the request, headers included: keep only its type.
            raise FetchError(f"{_host(url)} could not be reached ({type(exc).__name__})") from None
        try:
            data = json.loads(bytes(body))
        except ValueError:
            raise FetchError(f"{_host(url)} did not return JSON") from None
        return ApiResponse(status, data)

    def close(self) -> None:
        self._client.close()

    def _check(self, url: str) -> None:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.hostname not in self._hosts
            or parts.port not in (None, 443)
            or parts.username is not None
            or parts.password is not None
        ):
            raise UnsafeURLError(f"{_host(url)} is not an allowed API endpoint")


def _host(url: str) -> str:
    try:
        return urlsplit(url).hostname or "unknown host"
    except ValueError:
        return "unknown host"
