"""Small, valid sample records for storage and validate-data tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from netc.models import (
    CandidateSource,
    Category,
    Event,
    EventMention,
    KnownGroup,
    Organizer,
    Override,
    ReviewItem,
    Source,
    SourceStatus,
    event_id_for,
)

HASH = "b" * 64


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def make_event(
    slug: str = "omaha-python-meetup-2026-10-20",
    start: datetime | None = None,
    url: str = "https://www.meetup.com/omaha-python/events/123/",
    source_id: str = "src_omaha-python",
    **overrides: Any,
) -> Event:
    start = start or utc(2026, 10, 20, 23, 30)
    data: dict[str, Any] = {
        "id": event_id_for(url),
        "slug": slug,
        "title": "Omaha Python Meetup",
        "start": start,
        "end": None,
        "source_tz": "America/Chicago",
        "all_day": False,
        "location": {"venue": "AIM Institute", "city": "Omaha", "state": "NE", "online": False},
        "area": "omaha",
        "summary": "Lightning talks and pizza.",
        "categories": ["software-dev"],
        "original_url": url,
        "status": "scheduled",
        "review_state": "published",
        "visibility": "shown",
        "inferred": [],
        "listings": [
            {
                "source_id": source_id,
                "url": url,
                "content_hash": HASH,
                "last_seen": utc(2026, 10, 17, 12),
                "missing_runs": 0,
            }
        ],
        "first_seen": utc(2026, 10, 10, 8),
        "last_verified": utc(2026, 10, 17, 12),
    }
    data.update(overrides)
    return Event.model_validate(data)


def make_source(source_id: str = "src_omaha-python", **overrides: Any) -> Source:
    data: dict[str, Any] = {
        "id": source_id,
        "name": "Omaha Python",
        "url": "https://www.meetup.com/omaha-python/",
        "connector": "ical",
        "trust": "trusted",
        "origin": "preconfigured",
        "status": "active",
        "added_at": "2026-10-17",
    }
    data.update(overrides)
    return Source.model_validate(data)


def make_candidate(
    url: str = "https://omahadata.example.org/", **overrides: Any
) -> CandidateSource:
    data: dict[str, Any] = {
        "url": url,
        "found_via": "web_search",
        "evidence": ["query: omaha data meetup"],
        "result": "pending",
        "reason": "awaiting evaluation",
        "last_evaluated": utc(2026, 10, 17, 12),
    }
    data.update(overrides)
    return CandidateSource.model_validate(data)


def make_mention(mention_id: str = "men_0123456789ab") -> EventMention:
    return EventMention.model_validate(
        {
            "id": mention_id,
            "channel": "newsletter",
            "title": "Lincoln DevOps night",
            "links": ["https://lincolndevops.example.org/events/nov"],
        }
    )


def make_review(review_id: str = "rev_0123456789ab", **overrides: Any) -> ReviewItem:
    data: dict[str, Any] = {
        "id": review_id,
        "kind": "event",
        "ref": "evt_0123456789ab",
        "reason": "probationary source",
        "created": utc(2026, 10, 17, 12),
    }
    data.update(overrides)
    return ReviewItem.model_validate(data)


def make_known_group(name: str = "ISACA Omaha") -> KnownGroup:
    return KnownGroup.model_validate({"name": name, "area": "omaha"})


def make_organizer(org_id: str = "org_omaha-python") -> Organizer:
    return Organizer.model_validate({"id": org_id, "name": "Omaha Python", "home_city": "Omaha"})


def make_category(cat_id: str = "software-dev", label: str = "Software development") -> Category:
    return Category.model_validate({"id": cat_id, "label": label, "keywords": ["python", "code"]})


def make_override(event_id: str, **overrides: Any) -> Override:
    data: dict[str, Any] = {"event_id": event_id, "visibility": "hidden", "reason": "duplicate"}
    data.update(overrides)
    return Override.model_validate(data)


def make_status(**overrides: Any) -> SourceStatus:
    data: dict[str, Any] = {"last_attempt": utc(2026, 10, 17, 12), "consecutive_failures": 0}
    data.update(overrides)
    return SourceStatus.model_validate(data)
