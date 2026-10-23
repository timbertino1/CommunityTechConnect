"""The link-graph finder (T087; research R6).

Groups link to each other: co-hosts, sponsors' meetups, chapters, venues' calendars. From the
pages of known organizers and groups, this reads one page each (no crawling past it) and keeps
the outbound links that look like a group, an events page or a calendar. Event-platform pages
aren't used as starting points: they are read as sources already, and Meetup asks for slow
access (gate V1). At most MAX_PAGES are read a run, starting further along the list each week
so every page comes round.
"""

from __future__ import annotations

import re
from typing import ClassVar, Final
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser

from netc.fetch import FetchError
from netc.fetch.urls import join_url
from netc.finders.base import (
    PLATFORMS,
    FinderContext,
    FinderResult,
    candidate_url,
    luma_calendar_feed,
    make_candidate,
    merge_leads,
    site_key,
)
from netc.pipeline.sanitize import safe_url, to_plain_text

MAX_PAGES: Final = 20
MAX_LINKS_PER_PAGE: Final = 300
_PATH_WORDS: Final = re.compile(
    r"(events?|calendar|meetups?|ical|\.ics|conference|hackathon|workshops?|chapter|user-?groups?)"
    r"(/|\.|$|-|\?)",
    re.IGNORECASE,
)
_TEXT_WORDS: Final = re.compile(
    r"\b(meetups?|user groups?|users|events?|calendar|conference|hackathon|chapter|community|"
    r"devs|developers|hackers|club|group)\b",
    re.IGNORECASE,
)


def pages_to_visit(ctx: FinderContext) -> list[str]:
    urls = [o.url for o in ctx.organizers if o.url]
    urls += [link for g in ctx.known_groups for link in g.links]
    urls += [s.url for s in ctx.sources]
    pages = [u for u in dict.fromkeys(urls) if _host(u) not in PLATFORMS]
    if len(pages) <= MAX_PAGES:
        return pages
    week = ctx.now.isocalendar().week
    start = (week * MAX_PAGES) % len(pages)
    rotated = pages[start:] + pages[:start]
    return rotated[:MAX_PAGES]


class LinkGraphFinder:
    name: ClassVar[str] = "link_graph"

    def run(self, ctx: FinderContext) -> FinderResult:
        result = FinderResult()
        if ctx.http is None:
            result.stats["skipped_no_http"] += 1
            return result
        seen = ctx.known_keys()
        for page in pages_to_visit(ctx):
            try:
                response = ctx.http.get(page, kind="page")
            except FetchError:
                result.stats["errors"] += 1
                continue
            if response.status >= 400:
                result.stats["errors"] += 1
                continue
            result.stats["pages"] += 1
            own = site_key(response.url) or site_key(page)
            for url, text in _links(response.url, response.text):
                if site_key(url) == own or not _looks_like_group(url, text):
                    continue
                target = candidate_url(url)
                if target is None:
                    continue
                lead = make_candidate(
                    target,
                    found_via="link_graph",
                    now=ctx.now,
                    evidence=[f"linked from {page}", f"link text: {text}"],
                )
                merge_leads(result, lead, seen)
        return result


def _links(base: str, html: str) -> list[tuple[str, str]]:
    try:
        tree = LexborHTMLParser(html)
    except Exception:
        return []
    found: list[tuple[str, str]] = []
    for node in tree.css("a[href]")[:MAX_LINKS_PER_PAGE]:
        href = (node.attributes.get("href") or "").strip()
        # A "Subscribe" link to a Luma calendar is often webcal://, which safe_url refuses.
        url = luma_calendar_feed(href) or safe_url(join_url(base, href))
        if url is not None:
            found.append((url, to_plain_text(node.text(), 200)))
    return found


def _looks_like_group(url: str, text: str) -> bool:
    if luma_calendar_feed(url) is not None:
        return True
    if _host(url) in PLATFORMS:
        return site_key(url) is not None
    return bool(_PATH_WORDS.search(urlsplit(url).path) or _TEXT_WORDS.search(text))


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").removeprefix("www.")
    except ValueError:
        return ""
