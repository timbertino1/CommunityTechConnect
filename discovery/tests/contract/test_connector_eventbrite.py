"""Eventbrite organizer connector: an organizer's public events through the Eventbrite API
(T104; gate V2). The API is faked; nothing leaves the machine."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from netc.connectors import default_connectors
from netc.connectors.base import RawPayload
from netc.connectors.eventbrite_org import (
    EVENTBRITE_API,
    MAX_CALLS_PER_RUN,
    EventbriteOrgConnector,
    organizer_id,
)
from netc.fetch import FetchError, FetchKind, FetchResponse
from netc.fetch.api import API_HOSTS, RawApiResponse
from netc.models import Source
from tests.connector_support import FETCHED_AT
from tests.data_samples import make_source

pytestmark = pytest.mark.contract

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "eventbrite"
TOKEN = "test-eventbrite-token-not-real"
ORG_URL = "https://www.eventbrite.com/o/nebraska-cloud-community-12345678901"
EVENTS_URL = f"{EVENTBRITE_API}/organizers/12345678901/events/"


def source(url: str = ORG_URL) -> Source:
    return make_source("src_ne-cloud", connector="eventbrite_org", url=url)


class FakeApi:
    def __init__(self, *pages: tuple[int, bytes]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(
        self, url: str, *, headers: Mapping[str, str], max_bytes: int = 1_000_000
    ) -> RawApiResponse:
        self.calls.append((url, dict(headers)))
        status, body = self.pages.pop(0) if self.pages else (200, b'{"events": []}')
        return RawApiResponse(status, body)


class NeverFetch:
    def get(
        self,
        url: str,
        *,
        kind: FetchKind = "page",
        allowed_types: Collection[str] | None = None,
        delay_seconds: float | None = None,
    ) -> FetchResponse:
        raise AssertionError(f"the page {url} was fetched; only the API may be used")


def recorded() -> bytes:
    return (FIXTURE / "organizer_events.json").read_bytes()


def connector(api: FakeApi, env: Mapping[str, str] | None = None) -> EventbriteOrgConnector:
    return EventbriteOrgConnector(
        lambda: FETCHED_AT, api=api, env={"EVENTBRITE_TOKEN": TOKEN} if env is None else env
    )


def parsed(body: bytes | None = None) -> tuple[EventbriteOrgConnector, RawPayload]:
    eb = connector(FakeApi((200, body if body is not None else recorded())))
    return eb, eb.fetch(source(), NeverFetch())


# --- Where the events come from


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (ORG_URL, "12345678901"),
        (ORG_URL + "/", "12345678901"),
        ("https://www.eventbrite.com/o/12345678901", "12345678901"),
        ("https://www.eventbrite.com/e/some-event-tickets-1000000000001", None),
        ("https://www.eventbrite.com/o/no-number-here", None),
        ("https://evil.example.com/o/x-12345678901", None),
    ],
)
def test_the_organizer_id_comes_from_the_public_organizer_page(
    url: str, expected: str | None
) -> None:
    assert organizer_id(url) == expected


def test_events_are_read_from_the_api_with_the_token_in_a_header() -> None:
    api = FakeApi((200, recorded()))
    payload = connector(api).fetch(source(), NeverFetch())
    [(url, headers)] = api.calls
    assert url.startswith(EVENTS_URL + "?")
    assert "status=live" in url and "expand=venue" in url
    assert headers == {"Authorization": f"Bearer {TOKEN}"}
    assert TOKEN not in payload.url and TOKEN.encode() not in payload.content
    assert "www.eventbriteapi.com" in API_HOSTS


def test_pages_are_followed_by_continuation() -> None:
    first = {"pagination": {"has_more_items": True, "continuation": "abc123"},
             "events": [{"id": "1"}]}  # fmt: skip
    second = {"pagination": {"has_more_items": False}, "events": [{"id": "2"}]}
    api = FakeApi((200, json.dumps(first).encode()), (200, json.dumps(second).encode()))
    payload = connector(api).fetch(source(), NeverFetch())
    assert len(api.calls) == 2 and "continuation=abc123" in api.calls[1][0]
    assert [e["id"] for e in json.loads(payload.content)["events"]] == ["1", "2"]


def test_without_a_token_nothing_is_called() -> None:
    api = FakeApi()
    with pytest.raises(FetchError, match="EVENTBRITE_TOKEN"):
        connector(api, env={}).fetch(source(), NeverFetch())
    assert api.calls == []


def test_a_source_that_is_not_an_organizer_page_fails() -> None:
    with pytest.raises(FetchError, match="organizer"):
        connector(FakeApi()).fetch(source("https://www.eventbrite.com/e/x-1"), NeverFetch())


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_api_errors_fail_without_the_token(status: int) -> None:
    api = FakeApi((status, json.dumps({"error_description": TOKEN}).encode()))
    with pytest.raises(FetchError) as caught:
        connector(api).fetch(source(), NeverFetch())
    assert TOKEN not in str(caught.value) and str(status) in str(caught.value)


def test_calls_stop_well_under_the_hourly_limit() -> None:
    api = FakeApi(*[(200, b'{"events": []}')] * (MAX_CALLS_PER_RUN + 5))
    eb = connector(api)
    for _ in range(MAX_CALLS_PER_RUN):
        eb.fetch(source(), NeverFetch())
    with pytest.raises(FetchError, match="limit"):
        eb.fetch(source(), NeverFetch())
    assert len(api.calls) == MAX_CALLS_PER_RUN <= 500  # Terms 3.5: 1,000 an hour per token


# --- Parsing


def test_upcoming_events_become_listings() -> None:
    eb, payload = parsed()
    result = eb.parse(source(), payload)
    cloud = next(x for x in result.listings if x.external_id == "1000000000001")
    assert cloud.title == "Nebraska Cloud Day 2026"
    assert cloud.start == datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
    assert cloud.end == datetime(2026, 11, 14, 23, 0, tzinfo=UTC)
    assert cloud.tz == "America/Chicago" and cloud.all_day is False
    assert cloud.location_text == "Scott Conference Center, 6450 Pine St, Omaha, NE 68106"
    assert cloud.url == "https://www.eventbrite.com/e/nebraska-cloud-day-2026-tickets-1000000000001"
    assert cloud.description_text == "A full day of cloud talks for developers and ops folks."
    assert cloud.online is False and cloud.cancelled is False


def test_online_and_cancelled_events() -> None:
    eb, payload = parsed()
    by_id = {x.external_id: x for x in eb.parse(source(), payload).listings}
    online = by_id["1000000000002"]
    assert online.online is True and online.location_text is None
    assert online.description_text == "Live online workshop."
    assert (
        online.url
        == "https://www.eventbrite.com/e/intro-to-kubernetes-online-tickets-1000000000002"
    )
    assert by_id["1000000000003"].cancelled is True


def test_past_events_are_counted_not_listed() -> None:
    eb, payload = parsed()
    result = eb.parse(source(), payload)
    assert "1000000000004" not in {x.external_id for x in result.listings}
    assert result.past == 1
    assert result.latest_past == datetime(2026, 4, 11, 14, 0, tzinfo=UTC)


def test_broken_entries_are_skipped_with_warnings() -> None:
    eb, payload = parsed()
    result = eb.parse(source(), payload)
    assert len(result.listings) == 3
    assert len(result.warnings) == 2


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"events": "x"}', b"{}"])
def test_garbage_never_raises(body: bytes) -> None:
    eb, payload = parsed(body)
    result = eb.parse(source(), payload)
    assert result.listings == [] and result.warnings


def test_the_connector_is_registered() -> None:
    assert default_connectors(lambda: FETCHED_AT)["eventbrite_org"].kind == "eventbrite_org"
