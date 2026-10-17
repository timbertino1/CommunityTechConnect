"""RawListing -> clean, typed fields -> Event (T058; FR-003, FR-025, FR-029, FR-031, FR-047/48).

Everything a connector produced is untrusted. Here it becomes plain text with length limits,
a safe https link, UTC times with the source zone kept, a Location, and an area from the
gazetteer. Listings without a usable title or link, or placed outside Nebraska by a host that is
not a Nebraska group, are dropped with a reason.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal
from urllib.parse import urlsplit

from netc.models import (
    Area,
    AreaConfig,
    Event,
    InferredField,
    Location,
    RawListing,
    Source,
    SourceListing,
    event_id_for,
    make_slug,
)
from netc.pipeline.places import match_place
from netc.pipeline.sanitize import safe_url, to_plain_text
from netc.pipeline.timeutil import CENTRAL, to_event_times

TITLE_MAX: Final = 200
SUMMARY_MAX: Final = 500
VENUE_MAX: Final = 200
ADDRESS_MAX: Final = 300
ORGANIZER_MAX: Final = 200
EXTERNAL_ID_MAX: Final = 512

type ReviewState = Literal["published", "pending_review", "rejected"]

# Organizer values some feeds use when they have none.
_PLACEHOLDER_ORGANIZERS: Final = frozenset({"unknown", "n/a", "na", "none", "tbd", "-"})


@dataclass(frozen=True)
class Dropped:
    reason: str


@dataclass(frozen=True)
class Normalized:
    event_id: str
    slug: str
    title: str
    summary: str
    start: datetime
    end: datetime | None
    source_tz: str
    tz_assumed: bool
    all_day: bool
    location: Location
    area: Area | None
    original_url: str
    organizer: str | None
    cancelled: bool
    listing: SourceListing
    inferred: tuple[InferredField, ...] = field(default=())
    nebraska_host: bool = False
    """The source is a Nebraska group (it has a default area)."""


def normalize(
    raw: RawListing, source: Source, areas: AreaConfig, *, now: datetime
) -> Normalized | Dropped:
    title = to_plain_text(raw.title, TITLE_MAX)
    if not title:
        return Dropped("no title after cleaning")
    original_url = safe_url(raw.url) or _upgraded_same_host(raw.url, source)
    if original_url is None:
        return Dropped("no safe https link to the original event page")

    times = to_event_times(raw.start, raw.end, tz=raw.tz, all_day=raw.all_day)
    inferred: list[InferredField] = []
    if times.tz_assumed:
        inferred.append("source_tz")

    location_text = to_plain_text(raw.location_text, ADDRESS_MAX)
    place = match_place(location_text, areas)
    nebraska_host = source.default_area is not None
    area: Area | None = place.area
    if place.out_of_state:
        if not nebraska_host:
            return Dropped(f"outside Nebraska ({location_text or place.state})")
        area = source.default_area
        inferred.append("area")
    elif area is None and raw.online and place.how == "none":
        area = "online"
    elif area is None and source.default_area is not None:
        area = source.default_area
        inferred.append("area")

    venue = location_text.split(",", 1)[0].strip()[:VENUE_MAX] if location_text else ""
    location = Location(
        venue=venue or None,
        address=location_text or None,
        city=place.city if not place.out_of_state else None,
        state=place.state if place.state and len(place.state) == 2 else None,
        online=raw.online,
    )
    summary = to_plain_text(raw.description_text, SUMMARY_MAX)
    local_day = times.start.astimezone(CENTRAL).date()
    listing = SourceListing(
        source_id=source.id,
        url=original_url,
        external_id=to_plain_text(raw.external_id, EXTERNAL_ID_MAX) or None,
        content_hash=_content_hash(
            title, summary, times.start, times.end, location_text, original_url, raw.cancelled
        ),
        last_seen=now,
        missing_runs=0,
    )
    return Normalized(
        event_id=event_id_for(original_url),
        slug=make_slug(title, local_day),
        title=title,
        summary=summary,
        start=times.start,
        end=times.end,
        source_tz=times.source_tz,
        tz_assumed=times.tz_assumed,
        all_day=times.all_day,
        location=location,
        area=area,
        original_url=original_url,
        organizer=_organizer(raw.organizer_text),
        cancelled=raw.cancelled,
        listing=listing,
        inferred=tuple(inferred),
        nebraska_host=nebraska_host,
    )


def to_event(
    item: Normalized,
    *,
    categories: list[str],
    review_state: ReviewState,
    now: datetime,
    area: Area | None = None,
) -> Event:
    """Build the Event. ``area`` (from classification) is used only when normalize found none."""
    inferred: list[InferredField] = ["categories", *item.inferred]
    final_area = item.area
    if final_area is None:
        if area is None:
            raise ValueError(f"{item.event_id}: no area could be determined")
        final_area = area
        inferred.append("area")
    return Event(
        id=item.event_id,
        slug=item.slug,
        title=item.title,
        start=item.start,
        end=item.end,
        source_tz=item.source_tz,
        tz_assumed=item.tz_assumed,
        all_day=item.all_day,
        location=item.location,
        area=final_area,
        summary=item.summary,
        categories=categories,
        original_url=item.original_url,
        status="cancelled" if item.cancelled else "scheduled",
        review_state=review_state,
        visibility="shown",
        inferred=list(dict.fromkeys(inferred)),
        listings=[item.listing],
        first_seen=now,
        last_verified=now,
    )


def _upgraded_same_host(url: str | None, source: Source) -> str | None:
    """``http://`` links on the very host we read over https are upgraded to https (some
    feeds still write http links for pages they serve over https). Other hosts stay strict."""
    if not url or not url.strip().lower().startswith("http://"):
        return None
    candidate = safe_url("https://" + url.strip()[len("http://") :])
    if candidate is None:
        return None
    fetched_hosts = {urlsplit(u).hostname for u in (source.url, source.feed_url) if u}
    return candidate if urlsplit(candidate).hostname in fetched_hosts else None


def _organizer(value: str | None) -> str | None:
    text = to_plain_text(value, ORGANIZER_MAX)
    return None if not text or text.casefold() in _PLACEHOLDER_ORGANIZERS else text


def _content_hash(
    title: str,
    summary: str,
    start: datetime,
    end: datetime | None,
    location: str,
    url: str,
    cancelled: bool,
) -> str:
    """Fingerprint of what visitors see, for change detection and the AI cache."""
    data = [
        title,
        summary,
        start.isoformat(),
        end.isoformat() if end else None,
        location,
        url,
        cancelled,
    ]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode("utf-8")).hexdigest()
