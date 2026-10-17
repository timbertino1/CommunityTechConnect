"""Timeouts, size caps, content types, and identification in SafeHttp (research R12)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from netc.fetch import (
    MAX_BYTES,
    ContentTypeNotAllowedError,
    FetchError,
    FetchTimeoutError,
    ResponseTooLargeError,
)
from tests.fetch_support import SITE_DOMAIN, FakeClock, make_http, mocked_web

pytestmark = pytest.mark.security

MB = 1024 * 1024
HTML = {"content-type": "text/html; charset=utf-8"}
RSS = {"content-type": "application/rss+xml"}


def test_size_caps_are_5mb_for_pages_and_2mb_for_feeds() -> None:
    assert MAX_BYTES["page"] == 5 * MB
    assert MAX_BYTES["feed"] == 2 * MB


# --- Timeouts


def test_connect_timeout_is_10s_and_total_is_30s() -> None:
    seen: list[dict[str, float]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, text="ok", headers=HTML)

    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").mock(side_effect=capture)
        http.get("https://example.com/")
    assert seen[0]["connect"] == 10.0
    assert all(0 < v <= 30.0 for v in seen[0].values())


def test_connect_timeout_raises_fetch_timeout() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").mock(side_effect=httpx.ConnectTimeout("slow"))
        with pytest.raises(FetchTimeoutError):
            http.get("https://example.com/")


def test_slow_drip_response_is_aborted_after_30s_total() -> None:
    clock = FakeClock()

    def drip() -> Iterator[bytes]:
        while True:  # never ends on its own
            clock.advance(8.0)
            yield b"<p>x</p>"

    with mocked_web("example.com") as web, make_http(clock=clock) as http:
        web.get("https://example.com/").respond(200, headers=HTML, content=drip())
        with pytest.raises(FetchTimeoutError):
            http.get("https://example.com/")


def test_transport_error_becomes_fetch_error() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(FetchError):
            http.get("https://example.com/")


# --- Size caps


def test_page_at_the_cap_is_accepted() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(200, headers=HTML, content=b"x" * (5 * MB))
        assert len(http.get("https://example.com/").content) == 5 * MB


def test_page_over_5mb_is_rejected() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(200, headers=HTML, content=b"x" * (5 * MB + 1))
        with pytest.raises(ResponseTooLargeError):
            http.get("https://example.com/")


def test_feed_over_2mb_is_rejected() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/feed").respond(200, headers=RSS, content=b"x" * (2 * MB + 1))
        with pytest.raises(ResponseTooLargeError):
            http.get("https://example.com/feed", kind="feed")


def test_endless_body_without_content_length_is_aborted_mid_stream() -> None:
    produced: list[int] = []

    def endless() -> Iterator[bytes]:
        while True:
            produced.append(1)
            yield b"x" * (256 * 1024)

    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/feed").respond(200, headers=RSS, content=endless())
        with pytest.raises(ResponseTooLargeError):
            http.get("https://example.com/feed", kind="feed")
    # Stopped just past 2 MB rather than reading forever.
    assert len(produced) <= 2 * MB // (256 * 1024) + 1


def test_declared_content_length_over_cap_is_rejected_before_reading() -> None:
    def body() -> Iterator[bytes]:
        raise AssertionError("body must not be read")
        yield b""  # pragma: no cover

    headers = {**HTML, "content-length": str(50 * MB)}
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(200, headers=headers, content=body())
        with pytest.raises(ResponseTooLargeError):
            http.get("https://example.com/")


# --- Content types


@pytest.mark.parametrize(
    "content_type", ["application/pdf", "image/png", "application/octet-stream", "text/javascript"]
)
def test_disallowed_content_types_are_rejected(content_type: str) -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(200, headers={"content-type": content_type})
        with pytest.raises(ContentTypeNotAllowedError):
            http.get("https://example.com/")


def test_missing_content_type_is_rejected() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").mock(return_value=httpx.Response(200, content=b"<p>"))
        with pytest.raises(ContentTypeNotAllowedError):
            http.get("https://example.com/")


@pytest.mark.parametrize(
    "content_type", ["text/html", "TEXT/HTML; charset=UTF-8", "application/xhtml+xml"]
)
def test_page_content_types_are_accepted(content_type: str) -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(200, headers={"content-type": content_type})
        assert http.get("https://example.com/").content_type == content_type.split(";")[0].lower()


@pytest.mark.parametrize(
    "content_type",
    ["application/rss+xml", "application/atom+xml", "application/xml", "text/xml", "text/calendar"],
)
def test_feed_content_types_are_accepted(content_type: str) -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/feed").respond(200, headers={"content-type": content_type})
        http.get("https://example.com/feed", kind="feed")


def test_caller_can_narrow_allowed_types() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/cal").respond(200, headers=RSS)
        with pytest.raises(ContentTypeNotAllowedError):
            http.get("https://example.com/cal", kind="feed", allowed_types={"text/calendar"})


def test_error_statuses_are_returned_without_content_type_check() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/gone").respond(404, headers={"content-type": "image/png"})
        assert http.get("https://example.com/gone").status == 404


# --- Identification and statelessness


def test_user_agent_identifies_the_bot() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(200, headers=HTML)
        http.get("https://example.com/")
        agents = {c.request.headers["user-agent"] for c in web.calls}
    assert agents == {f"NETechConnectBot/1.0 (+https://{SITE_DOMAIN}/about)"}


def test_cookies_are_not_sent_back() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/a").respond(
            200, headers={**HTML, "set-cookie": "session=abc; Path=/"}
        )
        b = web.get("https://example.com/b").respond(200, headers=HTML)
        http.get("https://example.com/a")
        http.get("https://example.com/b")
        assert "cookie" not in b.calls.last.request.headers


def test_text_decodes_with_declared_charset_and_tolerates_bad_bytes() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(
            200,
            headers={"content-type": "text/html; charset=latin-1"},
            content="café".encode("latin-1"),
        )
        web.get("https://example.com/bad").respond(200, headers=HTML, content=b"ok \xff\xfe")
        assert http.get("https://example.com/").text == "café"
        assert http.get("https://example.com/bad").text.startswith("ok ")
