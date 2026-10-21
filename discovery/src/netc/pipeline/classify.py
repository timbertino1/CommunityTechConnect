"""Rules-first relevance classification (T058; FR-003, FR-028, research R10).

Rules decide the clear cases: exclusion phrases (sales pitches, real estate, academic calendar
dates, student-only events) reject; category keywords from data/categories.yaml accept; a Nebraska
connection is required. When the rules can't decide, the AI is asked (T082), if one is given and
its budget remains; a confident, valid answer decides (``decided_by="ai"``). Otherwise the item
comes back with ``decided_by="none"`` and goes to review, never straight onto the site.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from netc.models import Area, AreaConfig, Category
from netc.pipeline.ai import MIN_CONFIDENCE, Ai
from netc.pipeline.places import match_place

MAX_CATEGORIES: Final = 3
TITLE_WEIGHT: Final = 2
GENERAL: Final = "general-tech"

# Phrases that mark an event as out of scope even when tech words appear.
EXCLUSIONS: Final = (
    "real estate", "mortgage", "insurance seminar", "webinar demo", "product demo", "book a demo",
    "free demo", "sales pitch", "investment opportunity", "get rich", "mlm", "realtor",
    # Socials and services with no tech content (venue calendars)
    "happy hour", "trivia night", "blood drive", "massage",
    # Academic calendars (university feeds)
    "semester break", "student holiday", "priority registration", "last day to", "last day of",
    "final exam", "finals", "commencement",
    "finals week", "tuition due", "residence hall", "move-in day", "spring break", "fall break",
    "no classes", "university closed", "offices closed",
    # Student-only events (university feeds): recruiting, admissions, student life
    "students only", "student-only", "industry in residence", "graduate programs",
    "graduate information", "nvolvement fair", "student advisory board",
    "run with the school of computing", "school of computing showcase",
)  # fmt: skip


@dataclass(frozen=True)
class ClassifyInput:
    title: str
    summary: str
    organizer: str | None
    area: Area | None
    """From normalize; None when the place is unknown."""
    online: bool
    source_area: Area | None
    """The source's default area: set for Nebraska groups."""


@dataclass(frozen=True)
class Classification:
    relevant: bool | None
    nebraska: bool | None
    area: Area | None
    categories: list[str] = field(default_factory=list)
    confidence: float = 0.0
    decided_by: Literal["rules", "ai", "none"] = "none"
    reason: str = ""


def classify(
    item: ClassifyInput,
    categories: Sequence[Category],
    areas: AreaConfig,
    *,
    ai: Ai | None = None,
) -> Classification:
    title = item.title.casefold()
    body = f"{item.summary} {item.organizer or ''}".casefold()

    for phrase in EXCLUSIONS:
        if _has(title, phrase) or _has(body, phrase):
            return Classification(False, None, item.area, [], 0.9, "rules", f"excluded: {phrase}")

    scores = _score(title, body, categories)
    chosen = _choose(scores, categories)
    nebraska, area = _nebraska(item, areas)

    if nebraska is False:
        return Classification(False, False, None, [], 0.9, "rules", "not in Nebraska")
    if not chosen:
        undecided = Classification(None, nebraska, area, [], 0.0, "none", "no tech keywords")
        return _second_opinion(item, undecided, categories, ai)
    confidence = 0.9 if max(scores.values()) >= TITLE_WEIGHT else 0.7
    if nebraska is None:
        undecided = Classification(
            None, None, area, chosen, confidence, "none", "Nebraska connection unclear"
        )
        return _second_opinion(item, undecided, categories, ai)
    return Classification(True, True, area, chosen, confidence, "rules", "tech keywords")


def _second_opinion(
    item: ClassifyInput, undecided: Classification, categories: Sequence[Category], ai: Ai | None
) -> Classification:
    """The AI's answer when it is confident and usable; otherwise the rules' undecided result."""
    if ai is None:
        return undecided
    answer = ai.classify(_ai_text(item), [c.id for c in categories])
    if answer is None or answer.confidence < MIN_CONFIDENCE:
        return undecided
    reason = f"AI: {answer.reason}"[:200]
    if not answer.nebraska:
        return Classification(False, False, None, [], answer.confidence, "ai", reason)
    if not answer.relevant:
        return Classification(False, True, undecided.area, [], answer.confidence, "ai", reason)
    area = undecided.area or (None if answer.area == "unknown" else answer.area)
    if area is None:
        return undecided  # relevant, but nowhere to file it: a person decides
    chosen = list(dict.fromkeys(answer.categories))[:MAX_CATEGORIES] or [GENERAL]
    return Classification(True, True, area, chosen, answer.confidence, "ai", reason)


def _ai_text(item: ClassifyInput) -> str:
    place = item.area or item.source_area or "unknown"
    lines = [
        f"Title: {item.title}",
        f"Organizer: {item.organizer or 'unknown'}",
        f"Online: {'yes' if item.online else 'no'}",
        f"Known area: {place}",
        f"Description: {item.summary}",
    ]
    return "\n".join(lines)


def _score(title: str, body: str, categories: Sequence[Category]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for category in categories:
        score = 0
        for keyword in category.keywords:
            phrase = keyword.casefold()
            if _has(title, phrase):
                score += TITLE_WEIGHT
            elif _has(body, phrase):
                score += 1
        if score:
            scores[category.id] = score
    return scores


def _choose(scores: dict[str, int], categories: Sequence[Category]) -> list[str]:
    """Up to three categories, best first; general-tech only when nothing more specific fits."""
    order = {c.id: i for i, c in enumerate(categories)}
    ranked = sorted(scores, key=lambda cid: (-scores[cid], order.get(cid, 0)))
    specific = [cid for cid in ranked if cid != GENERAL]
    return (specific or ranked)[:MAX_CATEGORIES]


def _nebraska(item: ClassifyInput, areas: AreaConfig) -> tuple[bool | None, Area | None]:
    if item.area in {"omaha", "lincoln", "other_ne"}:
        return True, item.area
    if item.area == "online" or (item.area is None and item.online):
        if item.source_area is not None:
            return True, "online"
        return None, "online"
    place = match_place(f"{item.title}, {item.summary}", areas)
    if place.out_of_state:
        return False, None
    if place.area is not None:
        return True, place.area
    if item.source_area is not None:
        return True, item.source_area
    return None, None


_PATTERNS: dict[str, re.Pattern[str]] = {}


def _has(text: str, phrase: str) -> bool:
    """Whole-word (or whole-symbol) match, allowing a plural "s"/"es"."""
    pattern = _PATTERNS.get(phrase)
    if pattern is None:
        pattern = re.compile(rf"(?<![\w]){re.escape(phrase)}(?:e?s)?(?![\w])")
        _PATTERNS[phrase] = pattern
    return pattern.search(text) is not None
