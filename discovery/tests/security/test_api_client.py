"""The API client for fixed third-party APIs (search): an allow-list of hosts, https only, no
redirects, size and time limits, and no secrets in errors (T085; research R12)."""

from __future__ import annotations

import json

import httpx
import pytest

from netc.fetch import FetchError, UnsafeURLError
from netc.fetch.api import MAX_API_BYTES, SafeApi

pytestmark = pytest.mark.security

URL = "https://api.tavily.com/search"
SECRET = "test-api-key-not-real"


def client(handler: httpx.MockTransport) -> SafeApi:
    return SafeApi(transport=handler)


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"echo": json.loads(request.content), "auth": "seen"})


def test_posts_json_to_an_allowed_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(request)

    response = client(httpx.MockTransport(handler)).post_json(
        URL, {"query": "Omaha"}, headers={"Authorization": f"Bearer {SECRET}"}
    )
    assert response.status == 200
    assert response.data["echo"] == {"query": "Omaha"}
    [request] = seen
    assert request.method == "POST"
    assert request.headers["authorization"] == f"Bearer {SECRET}"
    assert "NETechConnect" in request.headers["user-agent"]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/search",
        "http://api.tavily.com/search",
        "https://api.tavily.com:8443/search",
        "https://user:pass@api.tavily.com/search",
        "https://api.tavily.com.evil.example/search",
        "https://169.254.169.254/latest/meta-data/",
    ],
)
def test_other_hosts_schemes_and_ports_are_refused(url: str) -> None:
    calls: list[httpx.Request] = []
    api = client(httpx.MockTransport(lambda r: calls.append(r) or ok(r)))  # type: ignore[func-returns-value]
    with pytest.raises(UnsafeURLError):
        api.post_json(url, {}, headers={})
    assert calls == []


def test_redirects_are_not_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://169.254.169.254/"})

    with pytest.raises(FetchError, match="redirect"):
        client(httpx.MockTransport(handler)).post_json(URL, {}, headers={})


def test_oversized_responses_are_cut_off() -> None:
    big = b'{"x": "' + b"a" * (MAX_API_BYTES + 10) + b'"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big, headers={"content-type": "application/json"})

    with pytest.raises(FetchError, match="too large"):
        client(httpx.MockTransport(handler)).post_json(URL, {}, headers={})


def test_non_json_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>oops</html>")

    with pytest.raises(FetchError, match="JSON"):
        client(httpx.MockTransport(handler)).post_json(URL, {}, headers={})


def test_error_statuses_are_returned_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "slow down"})

    response = client(httpx.MockTransport(handler)).post_json(URL, {}, headers={})
    assert response.status == 429


def test_network_errors_never_include_headers_or_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed with Authorization: Bearer {SECRET}", request=request)

    with pytest.raises(FetchError) as caught:
        client(httpx.MockTransport(handler)).post_json(
            URL, {}, headers={"Authorization": f"Bearer {SECRET}"}
        )
    assert SECRET not in str(caught.value)


def test_timeouts_are_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(FetchError, match="timed out"):
        client(httpx.MockTransport(handler)).post_json(URL, {}, headers={})
