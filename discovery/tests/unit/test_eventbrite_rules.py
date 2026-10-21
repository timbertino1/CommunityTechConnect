"""Eventbrite's API terms, built into the data and the site (T104; gate V2):

- 3.1: no Eventbrite content about past events is stored, so an event whose only listings come
  from Eventbrite is deleted once it has ended (not kept for the archive);
- 3.2: an event with an Eventbrite listing always shows a direct link to that Eventbrite page,
  and the link is never ``nofollow``.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest

from netc.models import Event, Source
from netc.pipeline.lifecycle import apply_run
from tests.data_samples import make_event, make_source, utc
from tests.site_support import build, html_files, make_data

pytestmark = pytest.mark.unit

NOW = utc(2026, 10, 18, 12)
EVENTBRITE = make_source(
    "src_ne-cloud",
    connector="eventbrite_org",
    url="https://www.eventbrite.com/o/nebraska-cloud-community-12345678901",
)
OWN_SITE = make_source("src_ne-cloud-site", url="https://necloud.example.org/")
SOURCES: dict[str, Source] = {s.id: s for s in (EVENTBRITE, OWN_SITE)}
EB_URL = "https://www.eventbrite.com/e/nebraska-cloud-day-2026-tickets-1000000000001"


def event(
    *, start_days: float, end_days: float | None, also_own_site: bool = False, url: str = EB_URL
) -> Event:
    start = NOW + timedelta(days=start_days)
    end = None if end_days is None else NOW + timedelta(days=end_days)
    made = make_event(url=url, source_id=EVENTBRITE.id, start=start, end=end)
    if not also_own_site:
        return made
    own = made.listings[0].model_copy(
        update={"source_id": OWN_SITE.id, "url": "https://necloud.example.org/cloud-day"}
    )
    return made.model_copy(update={"listings": [*made.listings, own]})


def kept(*events: Event) -> list[str]:
    result = apply_run(events, [], sources=SOURCES, refreshed_sources=set(), queue=[], now=NOW)
    return [e.id for e in result.events]


def test_an_ended_eventbrite_only_event_is_deleted() -> None:
    assert kept(event(start_days=-2, end_days=-1.9)) == []


def test_without_an_end_time_the_start_decides() -> None:
    assert kept(event(start_days=-1, end_days=None)) == []


def test_an_event_still_running_or_upcoming_is_kept() -> None:
    running = event(start_days=-0.1, end_days=0.1)
    upcoming = event(start_days=10, end_days=10.2, url=EB_URL.replace("0001", "0002"))
    assert len(kept(running, upcoming)) == 2


def test_a_past_event_also_listed_elsewhere_is_kept() -> None:
    past = event(start_days=-2, end_days=-1.9, also_own_site=True)
    assert kept(past) == [past.id]


def test_the_deletion_is_reported() -> None:
    past = event(start_days=-2, end_days=-1.9)
    result = apply_run([past], [], sources=SOURCES, refreshed_sources=set(), queue=[], now=NOW)
    assert result.removed == [past.id]


def test_the_event_page_links_to_eventbrite_without_nofollow(tmp_path: Path) -> None:
    upcoming = event(start_days=10, end_days=10.2, also_own_site=True).model_copy(
        update={"original_url": "https://necloud.example.org/cloud-day", "slug": "cloud-day"}
    )
    data = make_data(tmp_path / "data", [upcoming])
    assert build(data, tmp_path / "out") == 0
    page = next(t for p, t in html_files(tmp_path / "out").items() if "cloud-day" in p)
    links = re.findall(r'<a [^>]*href="' + re.escape(EB_URL) + r'"[^>]*>', page)
    assert links, "the event page must link the Eventbrite page"
    assert all("nofollow" not in a for a in links)
