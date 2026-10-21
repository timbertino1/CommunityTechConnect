"""Data models mirroring data-model.md and the JSON Schemas in netc/schemas (T028).

Models validate stored data; they do not clean it. Untrusted text is cleaned earlier
(netc.pipeline.sanitize) and must already be plain text by the time it reaches a model.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import unicodedata
from datetime import UTC, date, datetime
from importlib.resources import files
from typing import Annotated, Any, Final, Literal, Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

from netc.pipeline.sanitize import is_plain_text, safe_url, scrub_pii, to_plain_text

# ---------------------------------------------------------------- shared field types


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a time zone; it is stored as UTC")
    return value.astimezone(UTC).replace(microsecond=0)


def _format_utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


UtcDatetime = Annotated[
    datetime,
    AfterValidator(_utc),
    PlainSerializer(_format_utc, return_type=str, when_used="json"),
]


def _plain(value: str) -> str:
    if not is_plain_text(value):
        raise ValueError("must be plain text (no HTML, control, or invisible characters)")
    return value


def _plain_note(value: str) -> str:
    if not is_plain_text(value, allow_newlines=True):
        raise ValueError("must be plain text (no HTML, control, or invisible characters)")
    return value


def _https(value: str) -> str:
    url = safe_url(value)
    if url is None:
        raise ValueError("must be a safe https:// URL with a public hostname")
    return url


def _https_without_query(value: str) -> str:
    parts = urlsplit(_https(value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _unique[T](items: list[T]) -> list[T]:
    if len(set(items)) != len(items):
        raise ValueError("items must be unique")
    return items


def _zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {value!r}") from exc
    return value


def _scrubbed_note(value: str) -> str:
    return scrub_pii(to_plain_text(value, 280))


Title = Annotated[str, StringConstraints(min_length=1, max_length=200), AfterValidator(_plain)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200), AfterValidator(_plain)]
Summary = Annotated[str, StringConstraints(max_length=500), AfterValidator(_plain)]
Reason = Annotated[str, StringConstraints(min_length=1, max_length=280), AfterValidator(_plain)]
Hint = Annotated[str, StringConstraints(max_length=200), AfterValidator(_plain)]
ShortText = Annotated[str, StringConstraints(max_length=100), AfterValidator(_plain)]
HttpsUrl = Annotated[str, StringConstraints(max_length=2048), AfterValidator(_https)]
CleanHttpsUrl = Annotated[
    str, StringConstraints(max_length=2048), AfterValidator(_https_without_query)
]
TimeZoneName = Annotated[str, StringConstraints(min_length=1), AfterValidator(_zone)]

EventId = Annotated[str, StringConstraints(pattern=r"^evt_[a-f0-9]{12}$")]
SourceId = Annotated[str, StringConstraints(pattern=r"^src_[a-z0-9-]{1,80}$")]
OrganizerId = Annotated[str, StringConstraints(pattern=r"^org_[a-z0-9-]{1,80}$")]
MentionId = Annotated[str, StringConstraints(pattern=r"^men_[a-f0-9]{12}$")]
ReviewId = Annotated[str, StringConstraints(pattern=r"^rev_[a-f0-9]{12}$")]
CategoryId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,40}$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,120}$")]
ContentHash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]

Area = Literal["omaha", "lincoln", "other_ne", "online"]
FoundVia = Literal[
    "web_search", "link_graph", "newsletter", "news", "platform", "gap", "suggestion"
]
InferredField = Literal[
    "categories", "area", "location", "organizer_id", "end", "source_tz", "summary"
]

DEFAULT_TZ: Final = "America/Chicago"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class _OmitNone(_Model):
    """Serializes without keys whose value is None (for schemas where the keys are optional
    but null is not allowed)."""

    @model_serializer(mode="wrap")
    def _omit_none(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        return {key: value for key, value in data.items() if value is not None}


# ---------------------------------------------------------------- identifiers

_TRACKING_PARAMS: Final = frozenset(
    {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "ref_src", "_hsenc", "_hsmi", "igshid"}
)


def canonical_url(url: str) -> str:
    """The safe https form of ``url`` without fragment or tracking parameters."""
    safe = safe_url(url)
    if safe is None:
        raise ValueError(f"not a safe https:// URL: {url!r}")
    parts = urlsplit(safe)
    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        kept = [
            (key, value)
            for key, value in pairs
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
        ]
        if len(kept) != len(pairs):
            query = urlencode(kept)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def event_id_for(url: str) -> str:
    """``evt_`` + first 12 hex chars of SHA-256 of the canonical original URL."""
    return "evt_" + hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:12]


_SLUG_DATE_LEN: Final = len("-2026-01-01")


SLUG_MAX: Final = 80
"""Short enough to share, and to keep build paths under Windows' 260-character limit."""


def make_slug(title: str, day: date) -> str:
    """URL-safe slug from the title and the event's local date, at most SLUG_MAX characters,
    cut at a word boundary."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    limit = SLUG_MAX - _SLUG_DATE_LEN
    if len(base) > limit:
        cut = base[: limit + 1]
        base = cut[: cut.rfind("-")] if "-" in cut else base[:limit]
    return f"{base.strip('-') or 'event'}-{day.isoformat()}"


@functools.cache
def load_schema(name: str) -> dict[str, Any]:
    """The packaged JSON Schema ``netc/schemas/<name>.schema.json`` (treat as read-only)."""
    text = (files("netc") / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


# ---------------------------------------------------------------- events


class Location(_Model):
    venue: Annotated[str, StringConstraints(max_length=200), AfterValidator(_plain)] | None = None
    address: Annotated[str, StringConstraints(max_length=300), AfterValidator(_plain)] | None = None
    city: ShortText | None = None
    state: Annotated[str, StringConstraints(max_length=2), AfterValidator(_plain)] | None = None
    online: bool


class SourceListing(_Model):
    source_id: SourceId
    url: HttpsUrl
    external_id: (
        Annotated[str, StringConstraints(max_length=512), AfterValidator(_plain)] | None
    ) = None
    content_hash: ContentHash
    last_seen: UtcDatetime
    missing_runs: NonNegativeInt = 0


class Event(_Model):
    id: EventId
    slug: Slug
    title: Title
    start: UtcDatetime
    end: UtcDatetime | None = None
    source_tz: TimeZoneName
    tz_assumed: bool = False
    all_day: bool
    location: Location
    area: Area
    organizer_id: OrganizerId | None = None
    summary: Summary
    categories: Annotated[list[CategoryId], Field(min_length=1), AfterValidator(_unique)]
    original_url: HttpsUrl
    status: Literal["scheduled", "cancelled", "unverified"]
    review_state: Literal["published", "pending_review", "rejected"]
    visibility: Literal["shown", "hidden"]
    inferred: Annotated[list[InferredField], AfterValidator(_unique)]
    listings: Annotated[list[SourceListing], Field(min_length=1)]
    series_key: Annotated[str, StringConstraints(max_length=200)] | None = None
    first_seen: UtcDatetime
    last_verified: UtcDatetime
    original_unavailable: bool = False

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end is not None and self.end < self.start:
            raise ValueError("end must not be before start")
        return self

    @property
    def is_public(self) -> bool:
        return self.review_state == "published" and self.visibility == "shown"


class RawListing(BaseModel):
    """One listing exactly as a connector parsed it. Every text field is untrusted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    external_id: str | None
    url: str | None
    title: str
    start: datetime
    end: datetime | None
    tz: str | None
    all_day: bool
    location_text: str | None
    online: bool
    organizer_text: str | None
    description_text: str | None
    cancelled: bool


# ---------------------------------------------------------------- sources


class HtmlRules(_OmitNone):
    item: Annotated[str, StringConstraints(max_length=200)] | None = None
    title: Annotated[str, StringConstraints(max_length=200)] | None = None
    start: Annotated[str, StringConstraints(max_length=200)] | None = None
    link: Annotated[str, StringConstraints(max_length=200)] | None = None
    location: Annotated[str, StringConstraints(max_length=200)] | None = None


class FollowLinks(_Model):
    """jsonld sources: also read same-site pages linked from the source URL whose path matches
    ``path_glob`` (shell-style, e.g. ``/live/nenug-*``), up to ``max_pages``."""

    path_glob: Annotated[str, StringConstraints(pattern=r"^/", max_length=200)]
    max_pages: Annotated[int, Field(ge=1, le=25)] = 10


class Source(_Model):
    id: SourceId
    name: Name
    url: HttpsUrl
    feed_url: HttpsUrl | None = None
    connector: Literal["ical", "rss", "jsonld", "eventbrite_org", "html_rules"]
    trust: Literal["trusted", "probationary"]
    origin: Literal["preconfigured", "admin", "discovered", "suggested"]
    found_via: FoundVia | None = None
    status: Literal["active", "paused", "blocked_by_terms"]
    organizer_id: OrganizerId | None = None
    default_area: Area | None = None
    approved_count: NonNegativeInt = 0
    rejected_count: NonNegativeInt = 0
    check_interval_hours: Annotated[int, Field(ge=1, le=24)] = 24
    rate_limit_seconds: Annotated[int, Field(ge=1, le=3600)] = 5
    html_rules: HtmlRules | None = None
    follow_links: FollowLinks | None = None
    notes: (
        Annotated[str, StringConstraints(max_length=1000), AfterValidator(_plain_note)] | None
    ) = None
    added_at: date
    updated_at: date | None = None


class SourceStatus(_Model):
    last_attempt: UtcDatetime | None = None
    last_success: UtcDatetime | None = None
    last_error: Annotated[str, StringConstraints(max_length=500), AfterValidator(_plain)] | None = (
        None
    )
    consecutive_failures: NonNegativeInt = 0
    events_found_last_run: NonNegativeInt | None = None


class SearchUsage(_Model):
    """Web search bookkeeping in data/state/search_usage.json: this month's query count and
    when each query last ran. Never the results (gate V4)."""

    month: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    used: NonNegativeInt = 0
    last_run: dict[Hint, date] = {}


class AiCacheEntry(_Model):
    """One AI call in data/cache/ai/<YYYY-MM>.jsonl: the checked answer (None when the call
    gave no usable answer) and its token counts. Never the text that was sent."""

    key: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    kind: Literal["classify", "extract"]
    model: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    at: UtcDatetime
    result: dict[str, Any] | list[Any] | None = None
    input_tokens: NonNegativeInt = 0
    cached_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0


# ---------------------------------------------------------------- discovery and review


class CandidateSource(_Model):
    url: HttpsUrl
    found_via: FoundVia
    evidence: Annotated[
        list[
            Annotated[str, StringConstraints(min_length=1, max_length=500), AfterValidator(_plain)]
        ],
        Field(max_length=50),
    ]
    result: Literal["pending", "added", "rejected", "needs_review", "blocked_by_terms"]
    reason: Annotated[str, StringConstraints(max_length=280), AfterValidator(_plain)]
    last_evaluated: UtcDatetime
    note: (
        Annotated[str, StringConstraints(max_length=280), AfterValidator(_scrubbed_note)] | None
    ) = Field(default=None, exclude=True)
    """A visitor's suggestion note: in memory only, never written to data/ (FR-020)."""


class EventMention(_Model):
    id: MentionId
    channel: Literal["newsletter", "news", "web_search"]
    title: Title
    date_hint: Hint | None = None
    place_hint: Hint | None = None
    organizer_hint: Hint | None = None
    links: Annotated[list[CleanHttpsUrl], Field(max_length=20), AfterValidator(_unique)]
    resolution: Literal["unresolved", "resolved", "held", "discarded"] = "unresolved"
    event_id: EventId | None = None
    attempts: NonNegativeInt = 0


class ReviewItem(_Model):
    id: ReviewId
    kind: Literal["event", "source", "suggestion", "mention"]
    ref: Annotated[str, StringConstraints(min_length=1, max_length=2048), AfterValidator(_plain)]
    reason: Reason
    created: UtcDatetime
    decision: Literal["pending", "approved", "rejected"] = "pending"
    decided_in_pr: PositiveInt | None = None


class Override(_OmitNone):
    event_id: EventId
    visibility: Literal["shown", "hidden"] | None = None
    categories: Annotated[list[CategoryId], Field(min_length=1), AfterValidator(_unique)] | None = (
        None
    )
    area: Area | None = None
    reason: Reason


# ---------------------------------------------------------------- reference data


class Organizer(_Model):
    id: OrganizerId
    name: Name
    home_city: ShortText | None = None
    url: HttpsUrl | None = None
    aliases: Annotated[list[Name], AfterValidator(_unique)] = []


class Category(_Model):
    id: CategoryId
    label: Annotated[str, StringConstraints(min_length=1, max_length=60), AfterValidator(_plain)]
    keywords: Annotated[
        list[
            Annotated[str, StringConstraints(min_length=1, max_length=60), AfterValidator(_plain)]
        ],
        Field(max_length=300),
        AfterValidator(_unique),
    ]


Place = Annotated[str, StringConstraints(min_length=1, max_length=100), AfterValidator(_plain)]
Zip = Annotated[str, StringConstraints(pattern=r"^[0-9]{5}$")]
ZipPrefix = Annotated[str, StringConstraints(pattern=r"^[0-9]{3}$")]

# Nebraska ZIP codes run from 680xx to 693xx (682 is unused).
NEBRASKA_ZIP_PREFIXES: Final = frozenset(f"{n:03d}" for n in range(680, 694)) - {"682"}


class AreaEntry(_Model):
    id: Area
    label: Annotated[str, StringConstraints(min_length=1, max_length=60), AfterValidator(_plain)]
    cities: Annotated[list[Place], AfterValidator(_unique)] = []
    zips: Annotated[list[Zip], AfterValidator(_unique)] = []
    zip_prefixes: Annotated[list[ZipPrefix], AfterValidator(_unique)] = []
    venues: Annotated[list[Name], AfterValidator(_unique)] = []


class OutOfStatePlace(_Model):
    name: Place
    state: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    zips: Annotated[list[Zip], AfterValidator(_unique)] = []


class AreaConfig(_Model):
    """data/areas.yaml: the four areas and the gazetteer that places events in them."""

    areas: list[AreaEntry]
    out_of_state: list[OutOfStatePlace] = []

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if sorted(a.id for a in self.areas) != sorted(["omaha", "lincoln", "other_ne", "online"]):
            raise ValueError("areas must list omaha, lincoln, other_ne and online exactly once")
        _no_overlap("city", [(a.id, c.casefold()) for a in self.areas for c in a.cities])
        _no_overlap("ZIP", [(a.id, z) for a in self.areas for z in a.zips])
        _no_overlap("venue", [(a.id, v.casefold()) for a in self.areas for v in a.venues])
        for area in self.areas:
            for code in [*area.zips, *(p + "00" for p in area.zip_prefixes)]:
                if code[:3] not in NEBRASKA_ZIP_PREFIXES:
                    raise ValueError(f"{area.id}: {code[:3]}xx is not a Nebraska ZIP code range")
        nebraska_cities = {c.casefold() for a in self.areas for c in a.cities}
        for place in self.out_of_state:
            if place.state == "NE" or place.name.casefold() in nebraska_cities:
                raise ValueError(f"{place.name} is listed both in Nebraska and out of state")
        return self

    def area(self, area_id: str) -> AreaEntry:
        return next(a for a in self.areas if a.id == area_id)


def _no_overlap(kind: str, pairs: list[tuple[str, str]]) -> None:
    owner: dict[str, str] = {}
    for area_id, value in pairs:
        if owner.setdefault(value, area_id) != area_id:
            raise ValueError(f"{kind} {value!r} is listed in both {owner[value]} and {area_id}")


class KnownGroup(_Model):
    name: Name
    aliases: Annotated[list[Name], AfterValidator(_unique)] = []
    area: Area | None = None
    links: Annotated[list[HttpsUrl], AfterValidator(_unique)] = []
    source_ids: Annotated[list[SourceId], AfterValidator(_unique)] = []
    last_searched: UtcDatetime | None = None
    cadence_days: PositiveInt | None = None
    status: Literal["active", "quiet", "defunct"] = "active"
