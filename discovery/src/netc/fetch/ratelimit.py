"""Per-host politeness: a minimum delay between requests and a request budget per run."""

from __future__ import annotations

from collections.abc import Callable

from netc.fetch.errors import BudgetExceededError


class HostRateLimiter:
    def __init__(
        self,
        *,
        budget_per_host: int,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._budget = budget_per_host
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._used: dict[str, int] = {}

    def spend(self, host: str) -> None:
        """Count one request against the host's budget, or raise BudgetExceededError."""
        used = self._used.get(host, 0)
        if used >= self._budget:
            raise BudgetExceededError(f"Request budget of {self._budget} for {host} is used up")
        self._used[host] = used + 1

    def wait(self, host: str, delay_seconds: float) -> None:
        """Sleep until ``delay_seconds`` have passed since the last request to ``host``."""
        last = self._last_request.get(host)
        if last is not None:
            remaining = last + delay_seconds - self._clock()
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()
