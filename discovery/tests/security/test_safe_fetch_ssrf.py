"""SSRF protection in SafeHttp (research R12, Constitution I)."""

from __future__ import annotations

import ipaddress
from typing import Any

import httpcore
import pytest

from netc.fetch import TooManyRedirectsError, UnsafeURLError, is_public_ip
from netc.fetch.safe_fetch import VettedBackend
from tests.fetch_support import PUBLIC_IP, FakeResolver, make_http, mocked_web

pytestmark = pytest.mark.security

NON_PUBLIC_IPS = [
    "10.0.0.5",  # private 10/8
    "172.16.3.4",  # private 172.16/12
    "172.31.255.255",
    "192.168.1.1",  # private 192.168/16
    "127.0.0.1",  # loopback
    "127.8.8.8",
    "169.254.169.254",  # link-local / cloud metadata
    "100.64.0.1",  # CGNAT 100.64/10
    "100.127.255.254",
    "224.0.0.1",  # multicast
    "239.255.255.250",
    "0.0.0.0",  # unspecified  # noqa: S104
    "255.255.255.255",  # broadcast
    "::1",  # IPv6 loopback
    "::",  # IPv6 unspecified
    "fc00::1",  # unique local fc00::/7
    "fd12:3456::1",
    "fe80::1",  # link-local fe80::/10
    "ff02::1",  # IPv6 multicast
    "::ffff:127.0.0.1",  # IPv4-mapped loopback
    "::ffff:10.0.0.1",  # IPv4-mapped private
    "::ffff:169.254.169.254",
    "::7f00:1",  # IPv4-compatible loopback
    "64:ff9b::a00:1",  # NAT64 of 10.0.0.1
    "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
]


@pytest.mark.parametrize("address", NON_PUBLIC_IPS)
def test_non_public_ips_are_not_public(address: str) -> None:
    assert not is_public_ip(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", [PUBLIC_IP, "8.8.8.8", "2606:4700:4700::1111"])
def test_public_ips_are_public(address: str) -> None:
    assert is_public_ip(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", NON_PUBLIC_IPS)
def test_dns_answer_in_non_public_range_is_rejected_before_any_request(address: str) -> None:
    resolver = FakeResolver({"intranet.example.com": [address]})
    with mocked_web() as web, make_http(resolver=resolver) as http:
        page = web.get("https://intranet.example.com/").respond(200, text="secret")
        with pytest.raises(UnsafeURLError):
            http.get("https://intranet.example.com/")
        assert not page.called
        assert len(web.calls) == 0


def test_mixed_dns_answer_with_any_private_ip_is_rejected() -> None:
    resolver = FakeResolver({"mixed.example.com": [PUBLIC_IP, "10.1.2.3"]})
    with mocked_web(), make_http(resolver=resolver) as http, pytest.raises(UnsafeURLError):
        http.get("https://mixed.example.com/")


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://10.0.0.1/",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://2130706433/",  # decimal 127.0.0.1
        "https://0x7f.0.0.1/",  # hex
        "https://0177.0.0.1/",  # octal
        "https://127.1/",
        "https://localhost/",
        "https://LOCALHOST./",
        "https://api.localhost/",
        "https://intranet/",  # single-label host
        "https://example.com:8443/",
        "https://example.com:80/",
        "http://example.com:8080/",
        "https://user:pw@example.com/",
        "https://user@example.com/",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "gopher://example.com/",
        "//example.com/",
        "https:///path-only",
        "not a url",
    ],
)
def test_unsafe_urls_are_rejected_without_dns_or_requests(url: str) -> None:
    resolver = FakeResolver()
    with mocked_web() as web, make_http(resolver=resolver) as http:
        with pytest.raises(UnsafeURLError):
            http.get(url)
        assert len(web.calls) == 0


def test_http_is_upgraded_to_https() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        page = web.get("https://example.com/events?x=1").respond(
            200, text="<p>ok</p>", headers={"content-type": "text/html"}
        )
        response = http.get("http://example.com/events?x=1")
        assert page.called
        assert response.url == "https://example.com/events?x=1"
        assert not any(c.request.url.scheme == "http" for c in web.calls)


def test_explicit_port_443_is_allowed() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(
            200, text="ok", headers={"content-type": "text/html"}
        )
        assert http.get("https://example.com:443/").status == 200


def test_redirect_to_host_resolving_to_private_ip_is_rejected() -> None:
    resolver = FakeResolver({"evil.example.net": ["169.254.169.254"]})
    with mocked_web("example.com", "evil.example.net") as web, make_http(resolver=resolver) as http:
        web.get("https://example.com/").respond(
            302, headers={"location": "https://evil.example.net/latest/meta-data/"}
        )
        metadata = web.get("https://evil.example.net/latest/meta-data/").respond(200, text="creds")
        with pytest.raises(UnsafeURLError):
            http.get("https://example.com/")
        assert not metadata.called


@pytest.mark.parametrize(
    "location",
    ["https://127.0.0.1/admin", "https://localhost/", "https://example.com:8080/", "file:///etc"],
)
def test_redirect_to_unsafe_url_is_rejected(location: str) -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(301, headers={"location": location})
        with pytest.raises(UnsafeURLError):
            http.get("https://example.com/")
        assert len([c for c in web.calls if c.request.url.path != "/robots.txt"]) == 1


def test_redirect_to_http_is_upgraded() -> None:
    with mocked_web("example.com", "www.example.com") as web, make_http() as http:
        web.get("https://example.com/").respond(
            301, headers={"location": "http://www.example.com/"}
        )
        web.get("https://www.example.com/").respond(
            200, text="ok", headers={"content-type": "text/html"}
        )
        assert http.get("https://example.com/").url == "https://www.example.com/"


def test_relative_redirect_is_resolved_against_current_url() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/a/b").respond(302, headers={"location": "../c"})
        web.get("https://example.com/c").respond(
            200, text="ok", headers={"content-type": "text/html"}
        )
        assert http.get("https://example.com/a/b").url == "https://example.com/c"


def _redirect_chain(web: Any, hops: int) -> None:
    for i in range(hops):
        web.get(f"https://example.com/r{i}").respond(
            302, headers={"location": f"https://example.com/r{i + 1}"}
        )
    web.get(f"https://example.com/r{hops}").respond(
        200, text="end", headers={"content-type": "text/html"}
    )


def test_five_redirects_are_followed() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        _redirect_chain(web, 5)
        assert http.get("https://example.com/r0").url == "https://example.com/r5"


def test_sixth_redirect_is_refused() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        _redirect_chain(web, 6)
        with pytest.raises(TooManyRedirectsError):
            http.get("https://example.com/r0")


# --- The connection layer re-vets DNS at connect time and pins the vetted IP (anti-rebinding).


def test_backend_refuses_to_connect_when_dns_now_answers_private() -> None:
    backend = VettedBackend(FakeResolver({"rebind.example.com": ["127.0.0.1"]}))
    with pytest.raises(UnsafeURLError):
        backend.connect_tcp("rebind.example.com", 443)


def test_backend_refuses_non_443_ports() -> None:
    backend = VettedBackend(FakeResolver())
    with pytest.raises(UnsafeURLError):
        backend.connect_tcp("example.com", 8443)


def test_backend_connects_to_the_vetted_ip_not_the_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[tuple[str, int]] = []

    def fake_connect(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> str:
        attempts.append((host, port))
        return "stream"

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", fake_connect)
    backend = VettedBackend(FakeResolver({"example.com": [PUBLIC_IP]}))
    assert backend.connect_tcp("example.com", 443) == "stream"  # type: ignore[comparison-overlap]
    assert attempts == [(PUBLIC_IP, 443)]


def test_backend_tries_next_vetted_ip_when_one_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def fake_connect(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> str:
        attempts.append(host)
        if host == "2606:4700:4700::1111":
            raise httpcore.ConnectError("unreachable")
        return "stream"

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", fake_connect)
    backend = VettedBackend(FakeResolver({"example.com": ["2606:4700:4700::1111", PUBLIC_IP]}))
    assert backend.connect_tcp("example.com", 443) == "stream"  # type: ignore[comparison-overlap]
    assert attempts == ["2606:4700:4700::1111", PUBLIC_IP]


def test_environment_proxies_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # A proxy would make the connection on our behalf and bypass VettedBackend.
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:3128")
    monkeypatch.setenv("ALL_PROXY", "http://10.0.0.1:3128")
    with make_http() as http:
        pool = http._client._transport._pool  # type: ignore[attr-defined]
        assert type(pool) is httpcore.ConnectionPool
        assert isinstance(pool._network_backend, VettedBackend)
        assert http._client._mounts == {}
