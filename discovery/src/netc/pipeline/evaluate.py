"""Candidate evaluation (T090; research R6; FR-015, FR-016).

For each candidate due a look: social networks are blocked by their terms; robots.txt is
respected (SafeHttp refuses, and the candidate is marked blocked); Meetup groups are set up the
way the existing Meetup sources are (gate V1), Eventbrite organizers are read through the API
(gate V2), Luma pages are never fetched (gate V3); anything else goes through feed detection. A
sample of the site's upcoming events is then read with the matching reader and judged by the
same rules (and AI) as everyday events:

- at least one Nebraska tech event: added, as a new probationary source (origin "discovered",
  or "suggested" for visitors' suggestions), so its events wait for review (FR-017);
- every event outside Nebraska, or none about tech: rejected, and not looked at again for a
  month (FR-015);
- nothing readable, no upcoming events, or events only a person can judge: needs review.

At most MAX_EVALUATIONS a run, and none started once the run's time is up (``should_stop``);
the rest wait for the next run. Each sample is at most MAX_SAMPLE events: one relevant event is
enough to add a source, and every unclear one can cost an AI call.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser

from netc.connectors.base import Connector, RawPayload
from netc.connectors.detect import Detection, detect
from netc.connectors.eventbrite_org import organizer_id
from netc.fetch import FetchError, HttpClient
from netc.finders.base import SKIP_HOSTS, luma_calendar_feed, site_key
from netc.models import AreaConfig, CandidateSource, Category, FollowLinks, Source
from netc.pipeline.ai import Ai
from netc.pipeline.classify import ClassifyInput, classify
from netc.pipeline.normalize import Dropped, normalize
from netc.pipeline.runner import LogSink
from netc.pipeline.sanitize import to_plain_text

MAX_EVALUATIONS: Final = 25
MAX_SAMPLE: Final = 8
RECHECK_AFTER: Final = timedelta(days=30)
TERMS_BLOCKED: Final = frozenset(
    {
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "twitter.com",
        "x.com",
        "tiktok.com",
    }
)
_TITLE_SUFFIX: Final = re.compile(r"\s*[^\w\s]+\s*(Meetup|Eventbrite|Luma|Home|Events?)\s*$", re.I)

Result = Literal["added", "rejected", "needs_review", "blocked_by_terms"]


@dataclass
class EvaluateResult:
    candidates: list[CandidateSource]
    """All candidates, in the order given, with the evaluated ones updated."""
    added: list[Source] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    stopped_for_time: bool = False
    """``should_stop`` ended the run early; the deferred candidates wait for the next run."""


@dataclass(frozen=True)
class _Verdict:
    result: Result
    reason: str
    source: Source | None = None
    note: str | None = None


def evaluate_candidates(
    candidates: Sequence[CandidateSource],
    *,
    http: HttpClient,
    connectors: Mapping[str, Connector],
    sources: Iterable[Source],
    categories: Sequence[Category],
    areas: AreaConfig,
    now: datetime,
    ai: Ai | None = None,
    max_evaluations: int = MAX_EVALUATIONS,
    should_stop: Callable[[], bool] | None = None,
    log: LogSink | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> EvaluateResult:
    taken = {s.id for s in sources}
    result = EvaluateResult(list(candidates))
    done = 0
    for i, candidate in enumerate(candidates):
        if not _due(candidate, now):
            continue
        if done >= max_evaluations:
            result.counts["deferred"] += 1
            continue
        if result.stopped_for_time or (should_stop is not None and should_stop()):
            result.stopped_for_time = True
            result.counts["deferred"] += 1
            continue
        done += 1
        started = clock()
        verdict = _evaluate(candidate, http, connectors, categories, areas, now, ai, taken)
        if log is not None:
            log(
                json.dumps(
                    {
                        "event": "candidate_evaluated",
                        "host": urlsplit(candidate.url).hostname or "",
                        "result": verdict.result,
                        "seconds": round(clock() - started, 1),
                    }
                )
            )
        evidence = list(candidate.evidence)
        if verdict.note:
            evidence = [*evidence, verdict.note][-50:]
        result.candidates[i] = candidate.model_copy(
            update={
                "result": verdict.result,
                "reason": verdict.reason[:280],
                "last_evaluated": now,
                "evidence": evidence,
            }
        )
        result.counts[verdict.result] += 1
        if verdict.source is not None:
            taken.add(verdict.source.id)
            result.added.append(verdict.source)
    return result


def _due(candidate: CandidateSource, now: datetime) -> bool:
    if candidate.result == "pending":
        return True
    if candidate.result in ("rejected", "needs_review"):
        return now - candidate.last_evaluated >= RECHECK_AFTER
    return False  # added, blocked_by_terms


def _evaluate(
    candidate: CandidateSource,
    http: HttpClient,
    connectors: Mapping[str, Connector],
    categories: Sequence[Category],
    areas: AreaConfig,
    now: datetime,
    ai: Ai | None,
    taken: set[str],
) -> _Verdict:
    host = (urlsplit(candidate.url).hostname or "").removeprefix("www.")
    if any(host == h or host.endswith(f".{h}") for h in TERMS_BLOCKED):
        return _Verdict("blocked_by_terms", "this site's terms don't allow automated reading")
    if any(host == h or host.endswith(f".{h}") for h in SKIP_HOSTS):
        return _Verdict("rejected", "not an event source")

    key = site_key(candidate.url) or host
    origin: Literal["discovered", "suggested"] = (
        "suggested" if candidate.found_via == "suggestion" else "discovered"
    )
    base = {
        "trust": "probationary",
        "origin": origin,
        "found_via": candidate.found_via,
        "status": "active",
        "added_at": now.date(),
        "id": _new_id(key, taken),
    }

    luma_feed = luma_calendar_feed(candidate.url)
    if host in ("lu.ma", "luma.com"):
        # Gate V3: Luma is read only through a calendar's iCal feed, never its pages.
        return _Verdict(
            "needs_review",
            "Luma pages are not read (gate V3); add the calendar's iCal feed (on Luma: the "
            "calendar, then Add iCal Subscription) to the group's links in known_groups.yaml",
        )
    if host == "meetup.com":
        group = key.split("/", 1)[1]
        source = Source.model_validate(
            {
                **base,
                "name": group.replace("-", " ").title(),
                "connector": "jsonld",
                "url": f"https://www.meetup.com/{group}/events/",
                "rate_limit_seconds": 10,
                "follow_links": FollowLinks(path_glob=f"/{group}/events/[0-9]*", max_pages=3),
                "notes": (
                    "Discovered. Meetup (gate V1): public event pages only, 10 s apart, "
                    "no member data."
                ),
            }
        )
    elif organizer_id(candidate.url) is not None:
        # Gate V2: Eventbrite organizers are read through the API (token confirmed at T103),
        # not their pages. The name comes from the page address: /o/<name>-<organizer id>.
        slug = re.sub(r"-?\d+/?$", "", urlsplit(candidate.url).path.removeprefix("/o/"))
        base["id"] = _new_id(f"eventbrite/{slug or key}", taken)
        source = Source.model_validate(
            {
                **base,
                "name": slug.replace("-", " ").title() or "Eventbrite organizer",
                "connector": "eventbrite_org",
                "url": candidate.url,
                "notes": (
                    f"Discovered via {candidate.found_via.replace('_', ' ')}. Eventbrite (gate "
                    "V2): read through the API; ended Eventbrite-only events are deleted."
                ),
            }
        )
    else:
        found: Detection = detect(candidate.url, http)
        if found.kind == "none":
            if "RobotsDisallowedError" in found.reason:
                return _Verdict("blocked_by_terms", "robots.txt disallows reading it")
            return _Verdict("needs_review", found.reason)
        if luma_feed is not None and found.kind != "ical":
            return _Verdict("needs_review", "the Luma feed did not return a calendar")
        if luma_feed is not None:
            base["id"] = _new_id(f"luma/luma-{key.split('/', 1)[1]}", taken)
        source = Source.model_validate(
            {
                **base,
                "name": _name(found.title, host),
                "connector": found.kind,
                "url": candidate.url,
                "feed_url": found.feed_url,
                "notes": f"Discovered via {candidate.found_via.replace('_', ' ')}: {found.reason}.",
            }
        )

    connector = connectors.get(source.connector)
    if connector is None:
        return _Verdict("needs_review", f"no reader for {source.connector} yet")
    try:
        payload = connector.fetch(source, http)
    except FetchError as exc:
        if "RobotsDisallowed" in type(exc).__name__:
            return _Verdict("blocked_by_terms", "robots.txt disallows reading it")
        return _Verdict("needs_review", f"sample events could not be read: {type(exc).__name__}")
    if host == "meetup.com":
        source = source.model_copy(update={"name": _name(_page_title(payload), "") or source.name})
    elif source.connector == "ical" and source.name == host:
        source = source.model_copy(update={"name": _calendar_name(payload) or source.name})
    listings = connector.parse(source, payload).listings[:MAX_SAMPLE]
    return _judge(source, listings, categories, areas, now, ai)


def _judge(
    source: Source,
    listings: Sequence[object],
    categories: Sequence[Category],
    areas: AreaConfig,
    now: datetime,
    ai: Ai | None,
) -> _Verdict:
    tally: Counter[str] = Counter()
    kept_areas: Counter[str] = Counter()
    for raw in listings:
        item = normalize(raw, source, areas, now=now)  # type: ignore[arg-type]
        if isinstance(item, Dropped):
            if item.reason.startswith("outside Nebraska"):
                tally["read"] += 1
                tally["elsewhere"] += 1
            continue
        tally["read"] += 1
        verdict = classify(ClassifyInput.of(item, None), categories, areas, ai=ai)
        if verdict.relevant is True and verdict.area is not None:
            tally["kept"] += 1
            kept_areas[verdict.area] += 1
        elif verdict.nebraska is False:
            tally["elsewhere"] += 1
        elif verdict.relevant is False or not verdict.categories:
            tally["not_tech"] += 1
        else:
            tally["unclear"] += 1

    read = tally["read"]
    note = f"sample: {tally['kept']} of {read} upcoming events relevant ({now:%Y-%m-%d})"
    if read == 0:
        return _Verdict("needs_review", "no upcoming events to judge it by", note=note)
    if tally["kept"]:
        local = [a for a, _ in kept_areas.most_common() if a in ("omaha", "lincoln", "other_ne")]
        added = source.model_copy(update={"default_area": local[0] if local else None})
        return _Verdict("added", "relevant Nebraska tech events", source=added, note=note)
    if tally["elsewhere"] == read:
        return _Verdict("rejected", "its upcoming events are outside Nebraska", note=note)
    if tally["unclear"]:
        return _Verdict("needs_review", "its events need a person to judge", note=note)
    return _Verdict("rejected", f"no tech events among {read} upcoming", note=note)


def _new_id(key: str, taken: set[str]) -> str:
    part = key.split("/", 1)[1] if "/" in key else key
    slug = re.sub(r"[^a-z0-9]+", "-", part.lower()).strip("-")[:70] or "site"
    candidate, n = f"src_{slug}", 2
    while candidate in taken:
        candidate, n = f"src_{slug}-{n}", n + 1
    return candidate


def _name(title: str | None, host: str) -> str:
    name = _TITLE_SUFFIX.sub("", to_plain_text(title or "", 200)).strip()
    return name or host or "New source"


def _calendar_name(payload: RawPayload) -> str | None:
    """A feed's own name (X-WR-CALNAME), for an iCal source that has no page to name it."""
    match = re.search(r"^X-WR-CALNAME:(.+)$", payload.text, re.MULTILINE)
    return to_plain_text(match.group(1), 200) or None if match else None


def _page_title(payload: RawPayload) -> str | None:
    try:
        node = LexborHTMLParser(payload.text).css_first("title")
    except Exception:
        return None
    return node.text() if node else None
