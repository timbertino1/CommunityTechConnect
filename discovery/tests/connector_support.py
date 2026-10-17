"""Helpers for connector contract tests: fixture payloads and sources."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netc.connectors.base import RawPayload
from netc.models import RawListing, Source
from tests.data_samples import make_source

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
FETCHED_AT = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def fixture_text(relative: str, **replace: str) -> str:
    text = (FIXTURES / relative).read_text(encoding="utf-8")
    for marker, value in replace.items():
        text = text.replace(f"__{marker}__", value)
    return text


def payload(
    text: str,
    url: str = "https://example.org/feed",
    content_type: str = "text/calendar",
    **kwargs: Any,
) -> RawPayload:
    return RawPayload(
        url=url,
        content=text.encode("utf-8"),
        content_type=content_type,
        fetched_at=FETCHED_AT,
        text=text,
        **kwargs,
    )


def ical_source(**overrides: Any) -> Source:
    data: dict[str, Any] = {"connector": "ical", "url": "https://example.org/feed.ics"}
    data.update(overrides)
    return make_source("src_test-ical", **data)


def jsonld_source(**overrides: Any) -> Source:
    data: dict[str, Any] = {"connector": "jsonld", "url": "https://www.example.org/events"}
    data.update(overrides)
    return make_source("src_test-jsonld", **data)


def by_title(listings: list[RawListing]) -> dict[str, RawListing]:
    return {listing.title: listing for listing in listings}
