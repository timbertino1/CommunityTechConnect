"""Visitors' suggestions, as the suggest Worker stored them in KV (T133; FR-020, FR-022,
contracts/workers.md section 1).

Each record is ``{url, note, received_at}``. The address becomes a candidate source
(``found_via: suggestion``), tidied like any other (``candidate_url``); one that can't be a
source (a social media page, say) is set aside for the owner's review instead. The note is
scrubbed of e-mail addresses and phone numbers again and kept on the candidate in memory only:
``CandidateSource.note`` is never serialized, so it reaches no file, PR or issue. Records that
are broken are dropped. Every record read is reported as done, for deletion once the run's
results are written; one that couldn't be read stays for the next run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from netc.finders.base import candidate_url, make_candidate, site_key
from netc.inbox.kv import Inbox, InboxError
from netc.models import CandidateSource
from netc.pipeline.sanitize import safe_url, scrub_pii, to_plain_text

MAX_SUGGESTIONS: Final = 50
"""Read in one run; the Worker allows each visitor 5 an hour, so a backlog is unlikely."""
NOT_A_SOURCE: Final = "suggested, but not a page we can read events from"


@dataclass(frozen=True)
class SetAside:
    url: str
    reason: str


@dataclass
class Suggestions:
    candidates: list[CandidateSource] = field(default_factory=list)
    for_review: list[SetAside] = field(default_factory=list)
    """Suggestions that can't be evaluated automatically: the owner decides."""
    done: list[str] = field(default_factory=list)
    """Keys read (useful or not), to delete once the run's results are written."""


def read_suggestions(inbox: Inbox, *, now: datetime) -> Suggestions:
    found = Suggestions()
    seen: set[str] = set()
    for key in inbox.keys()[:MAX_SUGGESTIONS]:
        try:
            raw = inbox.read(key)
        except InboxError:
            continue  # stays in KV for the next run
        found.done.append(key)
        record = _record(raw)
        if record is None:
            continue
        url, note = record
        target = candidate_url(url)
        if target is None:
            found.for_review.append(SetAside(url, NOT_A_SOURCE))
            continue
        site = site_key(target) or target
        if site in seen:
            continue
        seen.add(site)
        candidate = make_candidate(
            target, found_via="suggestion", evidence=["suggested by a visitor"], now=now
        )
        found.candidates.append(candidate.model_copy(update={"note": note or None}))
    return found


def _record(raw: bytes | None) -> tuple[str, str] | None:
    """The record's https address and scrubbed note, or None if it isn't usable."""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    url = safe_url(data.get("url")) if isinstance(data.get("url"), str) else None
    if url is None:
        return None
    note = data.get("note")
    text = scrub_pii(to_plain_text(note, 280)) if isinstance(note, str) else ""
    return url, text
