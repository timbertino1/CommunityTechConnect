"""Event mentions from newsletters and news posts (T083; research R8, R10; FR-014).

The AI lists the specific upcoming events a text mentions. What comes back is only ever an
unresolved EventMention: a title, hints and links. A mention is never published; the resolver
(T091) has to find the organizer's own event page first. The AI can't add links: a mention
keeps only links that were in the text it read (compared without query strings, which is also
how mentions store them).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from netc.models import EventMention
from netc.pipeline.ai import Ai
from netc.pipeline.sanitize import safe_url, to_plain_text

Channel = Literal["newsletter", "news", "web_search"]


def extract_mentions(
    text: str, links: Iterable[str], *, ai: Ai, channel: Channel
) -> list[EventMention] | None:
    """The mentions in ``text``; None when the AI gave no usable answer (try again later)."""
    allowed = {c for c in (_clean(link) for link in links) if c is not None}

    def keep_link(url: str) -> str | None:
        clean = _clean(url)
        return clean if clean in allowed else None

    drafts = ai.extract(text, keep_link)
    if drafts is None:
        return None
    mentions: dict[str, EventMention] = {}
    for draft in drafts:
        title = to_plain_text(draft.title, 200)
        if not title:
            continue
        kept = list(dict.fromkeys(c for c in (_clean(x) for x in draft.links) if c in allowed))
        date_hint = _hint(draft.date_hint)
        digest = hashlib.sha256(f"{channel}|{title.casefold()}|{date_hint or ''}".encode())
        try:
            mention = EventMention(
                id=f"men_{digest.hexdigest()[:12]}",
                channel=channel,
                title=title,
                date_hint=date_hint,
                place_hint=_hint(draft.place_hint),
                organizer_hint=_hint(draft.organizer_hint),
                links=kept,
            )
        except ValidationError:
            continue
        mentions.setdefault(mention.id, mention)
    return list(mentions.values())


def _clean(url: str) -> str | None:
    safe = safe_url(url)
    if safe is None:
        return None
    parts = urlsplit(safe)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _hint(value: str | None) -> str | None:
    return to_plain_text(value, 200) or None if value else None
