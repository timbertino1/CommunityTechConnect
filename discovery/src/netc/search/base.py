"""The search provider interface and the monthly budget (T085; research R6, gate V4).

Finders search through BudgetedSearch, never a provider directly. It counts every call
against MONTHLY_QUERY_BUDGET (well under Tavily's 1,000 free searches) and refuses once the
month's budget is spent, and it records only when each query last ran. Results are used in
memory by the finder that asked and are never stored: only candidate sites the evaluator
fetched and checked itself reach data/.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Final, Protocol

from netc.models import SearchUsage

MONTHLY_QUERY_BUDGET: Final = 400
"""About 175 weekly-sweep queries a month, plus room for targeted searches (gaps, mentions)."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    """A safe https URL."""
    snippet: str
    """Plain text."""


class SearchError(Exception):
    """A search could not be done. Messages never contain the API key."""


class SearchBudgetExhaustedError(SearchError):
    """This month's query budget is spent; no call was made."""


class SearchProvider(Protocol):
    name: ClassVar[str]

    def search(self, query: str, *, count: int = 10) -> list[SearchResult]: ...


class BudgetedSearch:
    def __init__(
        self,
        provider: SearchProvider,
        usage: SearchUsage,
        *,
        now: datetime,
        budget: int = MONTHLY_QUERY_BUDGET,
    ) -> None:
        self._provider = provider
        self._now = now
        self._budget = budget
        month = f"{now:%Y-%m}"
        self._usage = (
            usage if usage.month == month else usage.model_copy(update={"month": month, "used": 0})
        )

    @property
    def usage(self) -> SearchUsage:
        return self._usage

    @property
    def remaining(self) -> int:
        return max(0, self._budget - self._usage.used)

    def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
        if self.remaining == 0:
            raise SearchBudgetExhaustedError(
                f"this month's search budget ({self._budget} queries) is spent"
            )
        # Count before calling: the provider may charge even for a call that fails.
        last_run = {**self._usage.last_run, query[:200]: self._now.date()}
        self._usage = self._usage.model_copy(
            update={"used": self._usage.used + 1, "last_run": last_run}
        )
        return self._provider.search(query, count=count)
