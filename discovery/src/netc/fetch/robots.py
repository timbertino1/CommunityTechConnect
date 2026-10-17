"""robots.txt rules, fetched and cached once per host per run (research R12)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

from protego import Protego

from netc.fetch.errors import FetchError, RobotsUnavailableError

ROBOTS_USER_AGENT = "NETechConnectBot"

# Fetches https://<host>/robots.txt and returns (status, body text); raises FetchError.
type RobotsFetcher = Callable[[str], tuple[int, str]]


@dataclass(frozen=True)
class RobotsRules:
    """Parsed rules for one host. ``parser`` is None when everything is allowed."""

    parser: Protego | None = None

    def allows(self, url: str) -> bool:
        return self.parser is None or bool(self.parser.can_fetch(url, ROBOTS_USER_AGENT))

    @property
    def crawl_delay(self) -> float | None:
        if self.parser is None:
            return None
        delay = self.parser.crawl_delay(ROBOTS_USER_AGENT)
        return None if delay is None else float(delay)


class RobotsCache:
    """robots.txt per host for one run.

    2xx: parse the rules. 4xx (except 429): no rules, everything allowed (RFC 9309).
    429, 5xx, or a network failure: the host is skipped for the rest of the run.
    """

    def __init__(self, fetch: RobotsFetcher) -> None:
        self._fetch = fetch
        self._rules: dict[str, RobotsRules] = {}
        self._failures: dict[str, str] = {}

    def rules_for(self, host: str) -> RobotsRules:
        if host in self._rules:
            return self._rules[host]
        if host in self._failures:
            raise RobotsUnavailableError(self._failures[host])
        try:
            status, body = self._fetch(host)
        except FetchError as exc:
            self._fail(host, f"robots.txt for {host} could not be fetched: {exc}")
        if 200 <= status < 300:
            rules = RobotsRules(Protego.parse(body))
        elif 400 <= status < 500 and status != 429:
            rules = RobotsRules()
        else:
            self._fail(host, f"robots.txt for {host} returned HTTP {status}")
        self._rules[host] = rules
        return rules

    def _fail(self, host: str, reason: str) -> NoReturn:
        self._failures[host] = reason
        raise RobotsUnavailableError(reason)
