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
from urllib.parse import parse_qsl, urlsplit

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
from netc.pipeline.places import PlaceMatch, match_place
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
        # Never read on Meetup (gate V1): its search, GraphQL and API endpoints.
        "gql",
        "gql2",
        "api",
        "meetup_api",
        "account",
        "members",
    }
)
# Luma calendar iCal feeds: https://api.lu.ma/ics/get?entity=calendar&id=cal-... (gate V3).
LUMA_FEED_HOSTS: Final = frozenset({"api.lu.ma", "api.luma.com"})
_LUMA_CALENDAR_ID: Final = re.compile(r"cal-[A-Za-z0-9]{4,40}")
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
        # Reference, rankings and directories (from the Oct 2026 candidate backlog).
        "britannica.com",
        "usnews.com",
        "princetonreview.com",
        "municode.com",
        "ycombinator.com",
        # Job boards.
        "ziprecruiter.com",
        "monster.com",
        # Vendor documentation, support and product pages.
        "microsoft.com",
        "atlassian.com",
        "redhat.com",
        "gitlab.com",
        "hubspot.com",
        "codecademy.com",
        "hackingwithswift.com",
        # Link wrappers.
        "safelinks.protection.outlook.com",
        # Other Lincolns: schools, companies and a carmaker, none of them in Lincoln, NE.
        "lincoln.edu",
        "lincolnu.edu",
        "lincolntech.edu",
        "lincolneducationalservices.com",
        "lincolnfinancial.com",
        "lincoln.com",
        "lincolncanada.com",
        # Not tech groups, though their meeting calendars look like one (owner, 2026-10-24).
        "omahaaa.org",
    }
)
NOT_SOURCE_PATH: Final = re.compile(
    r"/(login|log-in|signin|sign-in|account|accounts|myaccount|dashboard|portal|parentportal|"
    r"jobs|careers|support|help)(/|$)|add_event_to_calendar|\.pdf$",
    re.IGNORECASE,
)
"""Pages that are never an event source: sign-ins, accounts, jobs, help, one-event calendar
links and documents."""
PLATFORM_LOCALE: Final = re.compile(r"/[a-z]{2}-[a-z]{2}/?$", re.IGNORECASE)
"""A platform's home page in another language, like meetup.com/de-de/."""
ELSEWHERE_HOST: Final = re.compile(r"lincolnshire|\.(uk|ca|au|nz)$")
"""Sites outside the US, including England's Lincoln and Lincolnshire."""
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


def luma_calendar_feed(url: str) -> str | None:
    """The https feed URL if ``url`` is a Luma calendar's iCal feed (``webcal://`` too), the
    only way Luma is read (gate V3); otherwise None."""
    found = _luma_calendar(url)
    return None if found is None else f"https://{found[0]}/ics/get?entity=calendar&id={found[1]}"


def _luma_calendar(url: str) -> tuple[str, str] | None:
    value = url.strip()
    if value[:9].lower() == "webcal://":
        value = "https://" + value[9:]
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if (
        parts.scheme.lower() != "https"
        or host not in LUMA_FEED_HOSTS
        or port not in (None, 443)
        or parts.username is not None
        or parts.path.rstrip("/") != "/ics/get"
    ):
        return None
    query = dict(parse_qsl(parts.query))
    calendar = query.get("id", "")
    if query.get("entity") != "calendar" or not _LUMA_CALENDAR_ID.fullmatch(calendar):
        return None
    return host, calendar


def site_key(url: str) -> str | None:
    """The host (without www.), or host/group for event platforms; None for unusable URLs.
    A Luma calendar feed's key is luma.com/<calendar id>, whichever Luma host serves it."""
    luma = _luma_calendar(url)
    if luma is not None:
        return f"luma.com/{luma[1].lower()}"
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


def not_a_source(url: str) -> str | None:
    """Why ``url`` can't be an event source, judged from the address alone (no fetch), or
    None. Cheap enough to run on every candidate before anything is fetched."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if _skip_host(host):
        return "not an event source"
    if ELSEWHERE_HOST.search(host):
        return "not an event source: a site outside the US"
    if host in PLATFORMS and PLATFORM_LOCALE.match(parts.path):
        return "not an event source: the platform's own home page"
    if NOT_SOURCE_PATH.search(parts.path):
        return "not an event source: a sign-in, account, jobs, help or document page"
    return None


def candidate_url(url: str) -> str | None:
    """The URL to evaluate for a site: the group page on a platform, the feed for a Luma
    calendar, the page itself elsewhere."""
    feed = luma_calendar_feed(url)
    if feed is not None:
        return feed
    safe = safe_url(url)
    if safe is None:
        return None
    parts = urlsplit(safe)
    host = (parts.hostname or "").removeprefix("www.")
    if not_a_source(safe) is not None:
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
    if found_via == "web_search" and not _names_nebraska(place, text, url, areas):
        # A topic x place query can still return pages about anything (cricket schedules for
        # "Omaha cloud user group", Dayton flights for "Lincoln tech conference"). Gap checks
        # are exempt: their queries name the group itself.
        return None
    if host not in PLATFORMS and _ARTICLE.search(urlsplit(url).path):
        return make_mention(result.title, [url], channel="web_search")
    target = candidate_url(url)
    if target is None:
        return None
    return make_candidate(
        target, found_via=found_via, now=now, evidence=[evidence, f"result: {result.title}"]
    )


def _names_nebraska(place: PlaceMatch, text: str, url: str, areas: AreaConfig) -> bool:
    """The result's title, snippet or address names a Nebraska place."""
    if place.area is not None or place.state == "NE" or "nebraska" in text.casefold():
        return True
    words = re.sub(r"[^A-Za-z]+", " ", urlsplit(url).netloc + " " + urlsplit(url).path)
    found = match_place(words, areas)
    return found.area is not None or "nebraska" in words.casefold()


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
