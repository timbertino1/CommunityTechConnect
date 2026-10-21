"""The platform finder (T101-T102; research R6, gates V1 and V3).

Event platforms are read only the ways their terms allow: Meetup through the JSON-LD on public
event pages (gate V1), Luma only through an organizer's calendar iCal feed (gate V3). This
finder fetches and searches nothing. It looks through the links already on file (known groups,
organizers, and the pages of events we list) for Meetup groups and Luma calendar feeds that
aren't sources or candidates yet, and hands them to the evaluator.

Luma event and calendar pages are not candidates: a calendar's feed can only be found by a
person (on Luma: the calendar, then "Add iCal Subscription"), who adds it to the group's links
in known_groups.yaml. Meetup groups are capped per run (gate V1: "a small per-run budget").
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar, Final
from urllib.parse import urlsplit

from netc.finders.base import (
    FinderContext,
    FinderResult,
    candidate_url,
    luma_calendar_feed,
    make_candidate,
    site_key,
)

MAX_MEETUP_PER_RUN: Final = 5


class PlatformFinder:
    name: ClassVar[str] = "platform"

    def run(self, ctx: FinderContext) -> FinderResult:
        result = FinderResult()
        known = ctx.known_keys()
        meetups = 0
        for url, evidence in _links_on_file(ctx):
            target = candidate_url(url)
            if target is None:
                continue
            is_luma = luma_calendar_feed(target) is not None
            is_meetup = urlsplit(target).hostname == "www.meetup.com"
            key = site_key(target)
            if not (is_luma or is_meetup) or key is None or key in known:
                continue
            if is_meetup and meetups >= MAX_MEETUP_PER_RUN:
                result.stats["meetup_left_for_later"] += 1
                continue
            known.add(key)
            meetups += is_meetup
            result.stats["meetup" if is_meetup else "luma"] += 1
            result.candidates.append(
                make_candidate(target, found_via="platform", evidence=[evidence], now=ctx.now)
            )
        return result


def _links_on_file(ctx: FinderContext) -> Iterator[tuple[str, str]]:
    for group in ctx.known_groups:
        for link in group.links:
            yield link, f"listed for the known group {group.name}"
    for organizer in ctx.organizers:
        if organizer.url:
            yield organizer.url, f"the organizer {organizer.name}"
    for event in ctx.events:
        for link in dict.fromkeys([event.original_url, *(x.url for x in event.listings)]):
            yield link, f"linked from the event {event.title}"
