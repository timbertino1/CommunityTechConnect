"""The newsletter finder (T099; research R8, R10; FR-014).

Local tech newsletters arrive at events@<domain>; the inbox Worker stores each raw message in
Workers KV under its SHA-256. This finder reads them, turns each into plain text plus clean
links, and asks the AI extractor for the upcoming events it mentions. Mentions wait to be
resolved to the organizer's own page like any other.

Everything kept from an email can end up public, so links are cleaned before anything sees
them: query strings and fragments are removed, and unsubscribe, preference, "view in browser"
and tracking/redirect links are dropped (matched against the List-Unsubscribe header, the link
text and known patterns), so nothing in the repository could manage the inbox's subscriptions.
Nothing from an email is stored but its mentions; the message hash is used only as the KV key.

The finder never deletes: it reports the messages it is done with, and discover_sources deletes
them after the run's data is written. An email the AI couldn't answer for stays for next time;
the AI cache means a message read twice is still sent only once.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import ClassVar, Final
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from netc.finders.base import FinderContext, FinderResult
from netc.inbox.kv import Inbox, InboxError
from netc.pipeline.extract import extract_mentions
from netc.pipeline.sanitize import safe_url, scrub_pii, to_plain_text

MAX_MESSAGES_PER_RUN: Final = 25
MAX_TEXT_CHARS: Final = 20_000  # the AI's per-email cap (T080)

# Mail-service hosts that only ever redirect, track, or show the email itself.
TRACKING_DOMAINS: Final = frozenset(
    {
        "list-manage.com", "campaign-archive.com", "mailchi.mp", "sendgrid.net", "mandrillapp.com",
        "hubspotlinks.com", "hubspotemail.net", "mailgun.org", "createsend.com", "cmail19.com",
        "cmail20.com", "rs6.net", "convertkit-mail.com", "convertkit-mail2.com", "mlsend.com",
        "sendibt3.com", "awstrack.me", "t.co", "lnkd.in",
    }
)  # fmt: skip
# First host labels of click-tracking subdomains (click.news.example.com, links.example.com).
TRACKING_LABELS: Final = frozenset(
    {"click", "clicks", "link", "links", "lnk", "track", "tracking", "trk", "email-link"}
)
# Path segments of management and tracking pages. Not "subscribe": a calendar to subscribe to
# is exactly what we want.
BLOCKED_SEGMENTS: Final = frozenset(
    {
        "unsubscribe", "unsub", "u", "optout", "opt-out", "preferences", "preference-center",
        "email-preferences", "manage-preferences", "manage-subscription", "subscription-center",
        "redirect", "track", "click", "clicks", "webversion", "web-version", "view-online",
        "view-in-browser", "forward", "forward-to-a-friend",
    }
)  # fmt: skip
BLOCKED_LABEL: Final = re.compile(
    r"unsubscribe|opt[- ]?out|(manage|update|change)\s+(your\s+)?(email\s+)?"
    r"(preferences|subscription|settings)|email\s+preferences|"
    r"view\s+(this\s+)?(email|newsletter|issue|message)?\s*(in\s+(your\s+|a\s+)?browser|online|"
    r"as\s+a\s+web\s*page)|forward\s+to\s+a\s+friend",
    re.IGNORECASE,
)
_URL_IN_TEXT: Final = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)
_HEADER_URL: Final = re.compile(r"<(https?://[^>\s]+)>", re.IGNORECASE)


@dataclass(frozen=True)
class Newsletter:
    text: str
    """Plain text for the AI, with each kept link next to the words it was on."""
    links: list[str]
    """Clean, public links, in order of appearance."""


def read_newsletter(raw: bytes) -> Newsletter:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    unsubscribe = frozenset(
        c
        for c in (
            clean_link(u) for u in _HEADER_URL.findall(str(message.get("list-unsubscribe", "")))
        )
        if c is not None
    )
    subject = to_plain_text(str(message.get("subject", "")), 300)
    body = message.get_body(preferencelist=("html", "plain"))
    content = ""
    if body is not None:
        try:
            content = str(body.get_content())
        except (LookupError, ValueError, TypeError, AttributeError):
            content = ""
    if body is not None and body.get_content_type() == "text/html":
        text, links = _from_html(content, unsubscribe)
    else:
        text, links = _from_plain(content, unsubscribe)
    text = to_plain_text(scrub_pii(f"{subject}\n\n{text}"), MAX_TEXT_CHARS)
    return Newsletter(text, list(dict.fromkeys(links)))


def clean_link(
    url: str, *, label: str = "", unsubscribe: frozenset[str] = frozenset()
) -> str | None:
    """The link without its query string or fragment, or None if it must not be kept."""
    safe = safe_url(url)
    if safe is None:
        return None
    parts = urlsplit(safe)
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    host = (parts.hostname or "").lower()
    segments = {s.lower() for s in parts.path.split("/") if s}
    if (
        clean in unsubscribe
        or BLOCKED_LABEL.search(label)
        or host.split(".", 1)[0] in TRACKING_LABELS
        or any(host == d or host.endswith(f".{d}") for d in TRACKING_DOMAINS)
        or segments & BLOCKED_SEGMENTS
        or any(v.lower().startswith(("http:", "https:")) for _, v in parse_qsl(parts.query))
        or (host.endswith("substack.com") and "redirect" in segments)
    ):
        return None
    return clean


class NewsletterFinder:
    name: ClassVar[str] = "newsletter"

    def __init__(self, inbox: Inbox | None) -> None:
        self._inbox = inbox

    def run(self, ctx: FinderContext) -> FinderResult:
        result = FinderResult()
        if self._inbox is None:
            result.stats["skipped_no_inbox"] += 1
            return result
        if ctx.ai is None:
            result.stats["skipped_no_ai"] += 1
            return result
        try:
            keys = self._inbox.keys()
        except InboxError:
            result.stats["errors"] += 1
            return result
        if len(keys) > MAX_MESSAGES_PER_RUN:
            result.stats["left_for_later"] = len(keys) - MAX_MESSAGES_PER_RUN
        seen: set[str] = set()
        for key in keys[:MAX_MESSAGES_PER_RUN]:
            try:
                raw = self._inbox.read(key)
            except InboxError:
                result.stats["errors"] += 1
                continue
            if raw is None:
                result.stats["gone"] += 1
                continue
            if hashlib.sha256(raw).hexdigest() != key:
                # Not written by the inbox Worker: never read, just cleared away.
                result.stats["bad_hash"] += 1
                result.processed_messages.append(key)
                continue
            letter = read_newsletter(raw)
            found = extract_mentions(letter.text, letter.links, ai=ctx.ai, channel="newsletter")
            if found is None:
                result.stats["ai_unusable"] += 1
                continue
            for mention in found:
                if mention.id not in seen:
                    seen.add(mention.id)
                    result.mentions.append(mention)
            result.processed_messages.append(key)
            result.stats["processed"] += 1
        return result


def _from_plain(content: str, unsubscribe: frozenset[str]) -> tuple[str, list[str]]:
    links: list[str] = []
    lines = []
    for line in content.splitlines():

        def keep(match: re.Match[str], line: str = line) -> str:
            url = match.group(0).rstrip(".,;:!?")
            cleaned = clean_link(url, label=line, unsubscribe=unsubscribe)
            if cleaned is None:
                return ""
            links.append(cleaned)
            return cleaned + match.group(0)[len(url) :]

        lines.append(_URL_IN_TEXT.sub(keep, line))
    return "\n".join(lines), links


class _HtmlText(HTMLParser):
    _SKIP: ClassVar[frozenset[str]] = frozenset(
        {"script", "style", "head", "title", "noscript", "template", "svg"}
    )
    _BLOCK: ClassVar[frozenset[str]] = frozenset(
        {"p", "br", "li", "div", "tr", "td", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol",
         "table", "section", "article", "hr", "blockquote"}
    )  # fmt: skip

    def __init__(self, unsubscribe: frozenset[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.unsubscribe = unsubscribe
        self.out: list[str] = []
        self.links: list[str] = []
        self._skipping = 0
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BLOCK:
            self.out.append("\n")
        elif tag == "a":
            self._finish_link()
            self._href = next((v for k, v in attrs if k == "href" and v), None) or ""

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skipping = max(0, self._skipping - 1)
        elif tag in self._BLOCK:
            self.out.append("\n")
        elif tag == "a":
            self._finish_link()

    def handle_data(self, data: str) -> None:
        if self._skipping:
            return
        (self._label if self._href is not None else self.out).append(data)

    def close(self) -> None:
        super().close()
        self._finish_link()

    def _finish_link(self) -> None:
        if self._href is None:
            return
        label = "".join(self._label)
        cleaned = clean_link(self._href, label=label, unsubscribe=self.unsubscribe)
        if cleaned is not None:
            self.links.append(cleaned)
            label = f"{label} ({cleaned})"
        elif BLOCKED_LABEL.search(label):
            label = ""
        self.out.append(label)
        self._href = None
        self._label = []


def _from_html(content: str, unsubscribe: frozenset[str]) -> tuple[str, list[str]]:
    parser = _HtmlText(unsubscribe)
    parser.feed(content)
    parser.close()
    return "".join(parser.out), parser.links
