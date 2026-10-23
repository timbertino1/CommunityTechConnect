"""SafeHttp: the only way discovery code may reach the network (research R12, Constitution I).

Every request, including each redirect hop:

1. is vetted as an https URL on port 443 with a public, non-IP hostname (http is upgraded);
2. has its hostname resolved and every answer checked to be a public address;
3. obeys the host's robots.txt, crawl delay, and per-run request budget;
4. connects only to an address that was vetted at connect time (VettedBackend), so a DNS
   answer that changes between the check and the connection cannot reach an internal host;
5. is bounded by a 10 s connect timeout, a 30 s total time limit, a size cap, and a
   content-type allow-list.

Proxies from the environment are ignored, cookies are never stored, and redirects are followed
manually (at most 5) so that each hop goes through the same checks.
"""

from __future__ import annotations

import codecs
import contextlib
import functools
import socket
import ssl
import time
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from http.cookiejar import CookieJar, DefaultCookiePolicy
from ipaddress import ip_address
from types import MappingProxyType, TracebackType
from typing import Final, Literal, Self
from urllib.parse import urlsplit

import httpcore
import httpx

from netc.fetch.errors import (
    ContentTypeNotAllowedError,
    FetchError,
    FetchTimeoutError,
    ResponseTooLargeError,
    RobotsDisallowedError,
    TooManyRedirectsError,
    UnsafeURLError,
)
from netc.fetch.ratelimit import HostRateLimiter
from netc.fetch.robots import ROBOTS_USER_AGENT, RobotsCache
from netc.fetch.urls import IPAddress, is_public_ip, join_url, vet_url

type FetchKind = Literal["page", "feed"]
type _Kind = Literal["page", "feed", "robots"]
type Resolver = Callable[[str], list[IPAddress]]

_MB: Final = 1024 * 1024
MAX_BYTES: Final[Mapping[_Kind, int]] = MappingProxyType(
    {"page": 5 * _MB, "feed": 2 * _MB, "robots": 512 * 1024}
)
DEFAULT_CONTENT_TYPES: Final[Mapping[FetchKind, frozenset[str]]] = MappingProxyType(
    {
        "page": frozenset({"text/html", "application/xhtml+xml"}),
        "feed": frozenset(
            {
                "application/rss+xml",
                "application/atom+xml",
                "application/xml",
                "text/xml",
                "text/calendar",
                "application/json",
                "application/feed+json",
                "application/ld+json",
            }
        ),
    }
)
_ACCEPT: Final[Mapping[_Kind, str]] = MappingProxyType(
    {
        "page": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        "feed": "text/calendar,application/rss+xml,application/atom+xml,"
        "application/xml;q=0.9,application/json;q=0.9,*/*;q=0.1",
        "robots": "text/plain,*/*;q=0.1",
    }
)

CONNECT_TIMEOUT_SECONDS: Final = 10.0
TOTAL_TIMEOUT_SECONDS: Final = 30.0
MAX_REDIRECTS: Final = 5
DEFAULT_DELAY_SECONDS: Final = 5.0
DEFAULT_BUDGET_PER_HOST: Final = 50
HTTPS_PORT: Final = 443


def system_resolver(host: str) -> list[IPAddress]:
    """Resolve ``host`` with the OS resolver; returns unique addresses in answer order."""
    infos = socket.getaddrinfo(host, HTTPS_PORT, type=socket.SOCK_STREAM)
    addresses: list[IPAddress] = []
    for *_, sockaddr in infos:
        address = ip_address(str(sockaddr[0]).split("%", 1)[0])
        if address not in addresses:
            addresses.append(address)
    return addresses


def resolve_public(host: str, resolver: Resolver) -> list[IPAddress]:
    """Resolve ``host``; raise UnsafeURLError if any answer is not a public address."""
    try:
        addresses = resolver(host)
    except OSError as exc:
        raise FetchError(f"DNS lookup failed for {host}: {exc}") from exc
    if not addresses:
        raise FetchError(f"DNS lookup returned no addresses for {host}")
    for address in addresses:
        if not is_public_ip(address):
            raise UnsafeURLError(f"{host} resolves to non-public address {address}")
    return addresses


class VettedBackend(httpcore.SyncBackend):
    """Resolves and vets the host at connect time, then connects to the vetted IP.

    TLS still uses the original hostname for SNI and certificate checks (httpcore passes the
    origin host to start_tls), so pinning the IP does not weaken HTTPS.
    """

    def __init__(self, resolver: Resolver) -> None:
        self._resolver = resolver

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        if port != HTTPS_PORT:
            raise UnsafeURLError(f"Only port {HTTPS_PORT} is allowed, not {port}")
        last_error: httpcore.ConnectError | None = None
        for address in resolve_public(host, self._resolver):
            try:
                return super().connect_tcp(
                    str(address),
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.ConnectError as exc:
                last_error = exc
        raise last_error or FetchError(f"Could not connect to {host}")


@functools.cache
def _ssl_context() -> ssl.SSLContext:
    """Certificate-verifying TLS context, built once: loading the CA bundle is slow."""
    return httpx.create_ssl_context(trust_env=False)


class _VettedTransport(httpx.HTTPTransport):
    def __init__(self, resolver: Resolver) -> None:
        super().__init__(verify=_ssl_context(), trust_env=False)
        # httpx does not expose the network backend, so swap in a pool that uses ours.
        self._pool = httpcore.ConnectionPool(
            ssl_context=_ssl_context(),
            network_backend=VettedBackend(resolver),
        )


@dataclass(frozen=True)
class FetchResponse:
    url: str
    """Final URL after redirects."""
    status: int
    content_type: str
    """Lower-case media type without parameters; empty when the server sent none."""
    charset: str | None
    headers: Mapping[str, str]
    content: bytes

    @property
    def text(self) -> str:
        encoding = "utf-8"
        if self.charset:
            with contextlib.suppress(LookupError):
                encoding = codecs.lookup(self.charset).name
        return self.content.decode(encoding, errors="replace")


def _parse_content_type(value: str | None) -> tuple[str, str | None]:
    if not value:
        return "", None
    media_type, *params = (part.strip() for part in value.split(";"))
    charset = None
    for param in params:
        name, _, param_value = param.partition("=")
        if name.strip().lower() == "charset":
            charset = param_value.strip().strip('"') or None
    return media_type.lower(), charset


class SafeHttp:
    """HTTP client for untrusted URLs. Create one per run; use as a context manager."""

    def __init__(
        self,
        *,
        site_domain: str,
        resolver: Resolver = system_resolver,
        default_delay_seconds: float = DEFAULT_DELAY_SECONDS,
        budget_per_host: int = DEFAULT_BUDGET_PER_HOST,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._resolver = resolver
        self._default_delay = default_delay_seconds
        self._clock = clock
        self._limiter = HostRateLimiter(budget_per_host=budget_per_host, clock=clock, sleep=sleep)
        self._robots = RobotsCache(self._fetch_robots)
        self.user_agent = f"{ROBOTS_USER_AGENT}/1.0 (+https://{site_domain}/about)"
        self._client = httpx.Client(
            transport=_VettedTransport(resolver),
            trust_env=False,
            follow_redirects=False,
            cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])),
            headers={"user-agent": self.user_agent, "accept-encoding": "gzip, deflate"},
            timeout=httpx.Timeout(CONNECT_TIMEOUT_SECONDS),
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(
        self,
        url: str,
        *,
        kind: FetchKind = "page",
        allowed_types: Collection[str] | None = None,
        delay_seconds: float | None = None,
    ) -> FetchResponse:
        """Fetch ``url`` safely and politely.

        ``kind`` selects the size cap and default content types; ``allowed_types`` narrows or
        replaces them; ``delay_seconds`` is the source's rate limit (default 5 s). Error
        statuses (4xx/5xx) are returned, not raised. Raises a FetchError subclass otherwise.
        """
        types = (
            frozenset(t.lower() for t in allowed_types)
            if allowed_types is not None
            else DEFAULT_CONTENT_TYPES[kind]
        )
        delay = self._default_delay if delay_seconds is None else delay_seconds
        return self._get(url, kind=kind, allowed_types=types, delay=delay, polite=True)

    def _fetch_robots(self, host: str) -> tuple[int, str]:
        response = self._get(
            f"https://{host}/robots.txt",
            kind="robots",
            allowed_types=None,
            delay=self._default_delay,
            polite=False,
        )
        return response.status, response.text

    def _get(
        self,
        url: str,
        *,
        kind: _Kind,
        allowed_types: frozenset[str] | None,
        delay: float,
        polite: bool,
    ) -> FetchResponse:
        current = vet_url(url)
        for _hop in range(MAX_REDIRECTS + 1):
            host = urlsplit(current).hostname or ""
            resolve_public(host, self._resolver)
            wait = delay
            if polite:
                rules = self._robots.rules_for(host)
                if not rules.allows(current):
                    raise RobotsDisallowedError(f"robots.txt disallows {current}")
                wait = max(wait, rules.crawl_delay or 0.0)
                self._limiter.spend(host)
            self._limiter.wait(host, wait)

            result = self._exchange(current, kind, allowed_types)
            if isinstance(result, FetchResponse):
                return result
            current = vet_url(join_url(current, result))
        raise TooManyRedirectsError(f"More than {MAX_REDIRECTS} redirects starting at {url}")

    def _exchange(
        self, url: str, kind: _Kind, allowed_types: frozenset[str] | None
    ) -> FetchResponse | str:
        """One HTTP GET. Returns the response, or the Location of a redirect."""
        deadline = self._clock() + TOTAL_TIMEOUT_SECONDS
        try:
            with self._client.stream("GET", url, headers={"accept": _ACCEPT[kind]}) as resp:
                location = resp.headers.get("location")
                if resp.is_redirect and location:
                    return str(location)

                content_type, charset = _parse_content_type(resp.headers.get("content-type"))
                if (
                    resp.is_success
                    and allowed_types is not None
                    and content_type not in allowed_types
                ):
                    raise ContentTypeNotAllowedError(
                        f"{url} returned content type {content_type or '(none)'!r}"
                    )

                limit = MAX_BYTES[kind]
                declared = resp.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > limit:
                    raise ResponseTooLargeError(
                        f"{url} declares {declared} bytes; limit is {limit}"
                    )

                body = bytearray()
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > limit:
                        raise ResponseTooLargeError(f"{url} exceeded the {limit}-byte limit")
                    if self._clock() > deadline:
                        raise FetchTimeoutError(
                            f"{url} took longer than {TOTAL_TIMEOUT_SECONDS:.0f} s"
                        )

                return FetchResponse(
                    url=url,
                    status=resp.status_code,
                    content_type=content_type,
                    charset=charset,
                    headers=MappingProxyType(dict(resp.headers)),
                    content=bytes(body),
                )
        except httpx.TimeoutException as exc:
            raise FetchTimeoutError(f"{url} timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"{url} could not be fetched: {exc}") from exc
