"""Test doubles for netc.fetch: a fake clock, a fake DNS resolver, and a SafeHttp factory."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import respx

from netc.fetch import IPAddress, SafeHttp

PUBLIC_IP = "93.184.216.34"
SITE_DOMAIN = "netechconnect.example"


@dataclass
class FakeClock:
    """Monotonic clock whose sleep() advances time instantly and records each wait."""

    now: float = 1000.0
    sleeps: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeResolver:
    """Resolves every host to a public IP unless the test maps it to other answers."""

    answers: dict[str, list[str]] = field(default_factory=dict)
    lookups: list[str] = field(default_factory=list)

    def __call__(self, host: str) -> list[IPAddress]:
        self.lookups.append(host)
        return [ipaddress.ip_address(a) for a in self.answers.get(host, [PUBLIC_IP])]


def make_http(
    clock: FakeClock | None = None,
    resolver: FakeResolver | None = None,
    **kwargs: object,
) -> SafeHttp:
    clock = clock or FakeClock()
    return SafeHttp(
        site_domain=SITE_DOMAIN,
        resolver=resolver or FakeResolver(),
        clock=clock,
        sleep=clock.sleep,
        **kwargs,  # type: ignore[arg-type]
    )


@contextmanager
def mocked_web(*robots_hosts: str) -> Iterator[respx.MockRouter]:
    """respx router where each listed host has no robots.txt (404, i.e. allow all)."""
    with respx.mock(assert_all_called=False) as router:
        for host in robots_hosts:
            router.get(f"https://{host}/robots.txt").respond(404)
        yield router
