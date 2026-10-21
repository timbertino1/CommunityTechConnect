"""The weekly web-search sweep: {topic} x {place} queries (T085; research R6).

The full set is larger than one week's share, so each week runs the WEEKLY_QUERIES that ran
least recently (never-run first, then oldest), and every query comes round about every two
weeks. That's about 175 searches a month.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Final

WEEKLY_QUERIES: Final = 40

PLACES: Final = ("Omaha", "Lincoln", "Nebraska")
TOPICS: Final = (
    "tech", "AI", "cybersecurity", "programming", "cloud", "data", "networking", "DevOps",
    "web development", "IT",
)  # fmt: skip
GROUP_WORDS: Final = ("meetup", "user group")
EVENT_WORDS: Final = ("conference", "workshop", "hackathon")


def all_queries() -> list[str]:
    groups = [
        f"{place} {topic} {word}" for place in PLACES for topic in TOPICS for word in GROUP_WORDS
    ]
    events = [f"{place} tech {word}" for place in PLACES for word in EVENT_WORDS]
    return groups + events


def weekly_queries(last_run: Mapping[str, date], *, n: int = WEEKLY_QUERIES) -> list[str]:
    """This week's queries: least recently run first, ties in a fixed order."""
    queries = all_queries()
    ranked = sorted(range(len(queries)), key=lambda i: (last_run.get(queries[i], date.min), i))
    return [queries[i] for i in ranked[:n]]
