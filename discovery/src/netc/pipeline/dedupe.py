"""De-duplication (T059; FR-006, research R11).

Two events are the same when they share a canonical original URL (their id), or when they start
within 30 minutes of each other on the same Central Time day, their titles are at least 85
similar (rapidfuzz token-set ratio), and their locations are compatible (same city, or both
online). Merged events keep every listing and the oldest event's id; the link shown is the
organizer's own page over an event platform, and a platform over an aggregator.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import Final
from urllib.parse import urlsplit

from rapidfuzz import fuzz

from netc.models import Event, InferredField, SourceListing
from netc.pipeline.timeutil import CENTRAL

MAX_START_GAP: Final = timedelta(minutes=30)
MIN_TITLE_SIMILARITY: Final = 85.0

# Hosts where organizers publish events on a shared platform (still the organizer's page).
PLATFORM_HOSTS: Final = frozenset(
    {"meetup.com", "luma.com", "lu.ma", "eventbrite.com", "usnua.com", "groups.drupal.org"}
)
# Sites that list other people's events.
AGGREGATOR_HOSTS: Final = frozenset(
    {"dev.events", "allevents.in", "10times.com", "eventful.com", "happeningnext.com", "patch.com"}
)


def same_event(a: Event, b: Event) -> bool:
    if a.id == b.id:
        return True
    if abs(a.start - b.start) > MAX_START_GAP:
        return False
    if a.start.astimezone(CENTRAL).date() != b.start.astimezone(CENTRAL).date():
        return False
    if fuzz.token_set_ratio(a.title.casefold(), b.title.casefold()) < MIN_TITLE_SIMILARITY:
        return False
    return _compatible_location(a, b)


def deduplicate(events: Iterable[Event]) -> list[Event]:
    """Merge every group of matching events (matches chain), keeping first-seen order."""
    items = list(events)
    parent = list(range(len(items)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if root(i) != root(j) and same_event(items[i], items[j]):
                parent[root(j)] = root(i)

    groups: dict[int, list[Event]] = {}
    for i, event in enumerate(items):
        groups.setdefault(root(i), []).append(event)
    return [merge_all(group) for group in groups.values()]


def merge_all(group: list[Event]) -> Event:
    oldest = min(group, key=lambda e: (e.first_seen, e.id))
    merged = oldest
    for event in group:
        if event is not oldest:
            merged = merge(merged, event)
    return merged


def merge(primary: Event, other: Event) -> Event:
    """Combine ``other`` into ``primary``; ``primary`` keeps its id, slug, and review state."""
    listings = _merge_listings(primary.listings, other.listings)
    best = min((primary, other), key=lambda e: _link_rank(e.original_url))
    categories = list(dict.fromkeys([*primary.categories, *other.categories]))[:3]
    priced = max((primary, other), key=cost_rank)  # ties keep primary
    inferred: list[InferredField] = [f for f in primary.inferred if f != "cost"]
    if cost_rank(priced) == 1:
        inferred.append("cost")
    return primary.model_copy(
        update={
            "original_url": best.original_url,
            "cost": priced.cost,
            "price": priced.price,
            "inferred": inferred,
            "listings": listings,
            "categories": categories,
            "first_seen": min(primary.first_seen, other.first_seen),
            "last_verified": max(primary.last_verified, other.last_verified),
        }
    )


def cost_rank(event: Event) -> int:
    """2 = the event's own page says, 1 = from the source's default, 0 = unknown (FR-052)."""
    if event.cost is None:
        return 0
    return 1 if "cost" in event.inferred else 2


def link_rank(url: str) -> int:
    """0 = the organizer's own site, 1 = an event platform, 2 = an aggregator."""
    return _link_rank(url)


def _link_rank(url: str) -> int:
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    if host in AGGREGATOR_HOSTS:
        return 2
    if host in PLATFORM_HOSTS or host.endswith(".eventbrite.com"):
        return 1
    return 0


def _merge_listings(first: list[SourceListing], second: list[SourceListing]) -> list[SourceListing]:
    """All listings, one per (source, url); a newer copy of a listing replaces the older."""
    merged: dict[tuple[str, str], SourceListing] = {}
    for listing in [*first, *second]:
        key = (listing.source_id, listing.url)
        current = merged.get(key)
        if current is None or listing.last_seen >= current.last_seen:
            merged[key] = listing
    return list(merged.values())


def _compatible_location(a: Event, b: Event) -> bool:
    if a.location.online and b.location.online:
        return True
    if a.location.online != b.location.online:
        return False
    if a.location.city and b.location.city:
        return a.location.city.casefold() == b.location.city.casefold()
    return a.area == b.area
