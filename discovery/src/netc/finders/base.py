"""What every finder shares (T086-T089; contracts/connectors-and-finders.md "Finder").

A finder turns one channel (web search, links on known pages, news feeds, coverage gaps) into
candidate sources and event mentions. Finders never create sources or events: the evaluator
decides about candidates, and mentions wait to be resolved to an organizer's page (FR-014).

Sites are compared by site key: the host, or for event platforms the group on that host
(two Meetup groups are different sites; two pages of one group are the same site).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Final, Literal, Protocol
from urllib.parse import urlsplit

from netc.fetch import HttpClient
from netc.models import (
    AreaConfig,
    CandidateSource,
    Event,
    EventMention,
    KnownGroup,
    Organizer,
    Source,
)
from netc.pipeline.ai import Ai
from netc.pipeline.places import match_place
from netc.pipeline.sanitize import safe_url, to_plain_text
from netc.search.base import BudgetedSearch, SearchResult

FoundVia = Literal[
    "web_search", "link_graph", "newsletter", "news", "platform", "gap", "suggestion"
]

# Event platforms: the first path segment names the group (Eventbrite organizers use /o/<id>).
PLATFORMS: Final = {"meetup.com": 1, "lu.ma": 1, "luma.com": 1, "eventbrite.com": 2}
PLATFORM_RESERVED: Final = frozenset(
    {
        "find",
        "register",
        "login",
        "logout",
        "signup",
        "topics",
        "cities",
        "apps",
        "blog",
        "help",
        "lp",
        "pro",
        "about",
        "terms",
        "privacy",
        "home",
        "discover",
        "explore",
        "search",
        "create",
        "e",
        "d",
        "signin",
        "organizer",
        "organizations",
        "b",
        "cc",
        "help-center",
    }
)
# Sites that are never event sources: social networks, encyclopedias, job boards.
SKIP_HOSTS: Final = frozenset(
    {
        "facebook.com",
        "linkedin.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "youtube.com",
        "tiktok.com",
        "reddit.com",
        "wikipedia.org",
        "indeed.com",
        "glassdoor.com",
        "github.com",
        "medium.com",
        "google.com",
        "apple.com",
        "amazon.com",
        "yelp.com",
        "tripadvisor.com",
    }
)
_ARTICLE: Final = re.compile(r"/(19|20)\d\d/|/(news|blog|article|articles|story|stories|press)/")


@dataclass
class FinderContext:
    now: datetime
    areas: AreaConfig
    http: HttpClient | None = None
    search: BudgetedSearch | None = None
    ai: Ai | None = None
    sources: list[Source] = field(default_factory=list)
    candidates: list[CandidateSource] = field(default_factory=list)
    """Every candidate already on file, whatever its result."""
    known_groups: list[KnownGroup] = field(default_factory=list)
    organizers: list[Organizer] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    news_feeds: list[str] = field(default_factory=list)

    def known_keys(self) -> set[str]:
        urls = [s.url for s in self.sources] + [s.feed_url for s in self.sources if s.feed_url]
        urls += [c.url for c in self.candidates]
        return {k for k in (site_key(u) for u in urls) if k}


@dataclass
class FinderResult:
    candidates: list[CandidateSource] = field(default_factory=list)
    mentions: list[EventMention] = field(default_factory=list)
    stats: Counter[str] = field(default_factory=Counter)
    searched_groups: dict[str, datetime] = field(default_factory=dict)
    """Known groups (by name) searched for in this run, to update their last_searched."""
    processed_messages: list[str] = field(default_factory=list)
    """Inbox messages (by hash) this finder is done with; deleted once the run's data is
    written."""


class Finder(Protocol):
    name: ClassVar[str]

    def run(self, ctx: FinderContext) -> FinderResult: ...


def site_key(url: str) -> str | None:
    """The host (without www.), or host/group for event platforms; None for unusable URLs."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").removeprefix("www.")
    if not host:
        return None
    depth = PLATFORMS.get(host)
    if depth is None:
        return host
    segments = [s for s in parts.path.split("/") if s][:depth]
    if len(segments) < depth or (segments[0].lower() in PLATFORM_RESERVED and depth == 1):
        return None
    if depth == 2 and segments[0] != "o":
        return None
    return "/".join([host, *(s.lower() for s in segments)])


def _skip_host(host: str) -> bool:
    return any(host == h or host.endswith(f".{h}") for h in SKIP_HOSTS)


def candidate_url(url: str) -> str | None:
    """The URL to evaluate for a site: the group page on a platform, the page itself elsewhere."""
    safe = safe_url(url)
    if safe is None:
        return None
    parts = urlsplit(safe)
    host = (parts.hostname or "").removeprefix("www.")
    if _skip_host(host):
        return None
    key = site_key(safe)
    if key is None:
        return None
    if host in PLATFORMS:
        canonical = {"meetup.com": "www.meetup.com", "eventbrite.com": "www.eventbrite.com"}
        return f"https://{canonical.get(host, host)}/{key.split('/', 1)[1]}/"
    return f"https://{parts.netloc}{parts.path or '/'}"


def make_candidate(
    url: str, *, found_via: FoundVia, evidence: Iterable[str], now: datetime
) -> CandidateSource:
    notes = [to_plain_text(e, 500) for e in evidence]
    return CandidateSource(
        url=url,
        found_via=found_via,
        evidence=[n for n in notes if n][:50] or ["found automatically"],
        result="pending",
        reason="awaiting evaluation",
        last_evaluated=now,
    )


def make_mention(
    title: str,
    links: Iterable[str],
    *,
    channel: Literal["newsletter", "news", "web_search"],
    date_hint: str | None = None,
    place_hint: str | None = None,
) -> EventMention | None:
    clean_title = to_plain_text(title, 200)
    if not clean_title:
        return None
    clean_links = list(dict.fromkeys(u for u in (_clean(x) for x in links) if u))[:20]
    digest = hashlib.sha256(f"{channel}|{clean_title.casefold()}|{date_hint or ''}".encode())
    return EventMention(
        id=f"men_{digest.hexdigest()[:12]}",
        channel=channel,
        title=clean_title,
        date_hint=date_hint,
        place_hint=place_hint,
        links=clean_links,
    )


def _clean(url: str) -> str | None:
    safe = safe_url(url)
    if safe is None:
        return None
    parts = urlsplit(safe)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def lead_from_result(
    result: SearchResult,
    *,
    found_via: FoundVia,
    evidence: str,
    now: datetime,
    areas: AreaConfig,
) -> CandidateSource | EventMention | None:
    """A search result as a candidate site, a mention (news and blog posts), or nothing."""
    url = safe_url(result.url)
    if url is None:
        return None
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    if _skip_host(host):
        return None
    # Snippets are sentences: "...in Denver, Colorado." The matcher reads a state only before a
    # comma or the end, so sentence breaks become commas here.
    text = f"{result.title}, {result.snippet}".replace(". ", ", ").rstrip(" .")
    place = match_place(text, areas)
    if place.out_of_state and place.area is None:
        return None
    if host not in PLATFORMS and _ARTICLE.search(urlsplit(url).path):
        return make_mention(result.title, [url], channel="web_search")
    target = candidate_url(url)
    if target is None:
        return None
    return make_candidate(
        target, found_via=found_via, now=now, evidence=[evidence, f"result: {result.title}"]
    )


def merge_leads(
    result: FinderResult, lead: CandidateSource | EventMention | None, seen: set[str]
) -> None:
    """Add a lead unless its site (or mention) is already known or found this run."""
    if lead is None:
        return
    if isinstance(lead, EventMention):
        if lead.id not in seen:
            seen.add(lead.id)
            result.mentions.append(lead)
        return
    key = site_key(lead.url)
    if key and key not in seen:
        seen.add(key)
        result.candidates.append(lead)
