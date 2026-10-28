"""Model constraints from data-model.md, and model output vs. the JSON Schemas (T027, T028)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from netc.models import (
    AiCacheEntry,
    CandidateSource,
    Category,
    Event,
    EventMention,
    KnownGroup,
    Organizer,
    Override,
    RawListing,
    ReviewItem,
    SearchUsage,
    Source,
    SourceListing,
    SourceStatus,
    canonical_url,
    event_id_for,
    load_schema,
    make_slug,
)

pytestmark = pytest.mark.unit

HASH = "a" * 64
SPECS = Path(__file__).resolve().parents[3] / "specs" / "001-event-aggregator" / "contracts"


def listing(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source_id": "src_omaha-python",
        "url": "https://www.meetup.com/omaha-python/events/123/",
        "external_id": "123@meetup.com",
        "content_hash": HASH,
        "last_seen": "2026-10-17T12:00:00Z",
        "missing_runs": 0,
    }
    data.update(overrides)
    return data


def event(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "evt_0123456789ab",
        "slug": "omaha-python-meetup-2026-10-20",
        "title": "Omaha Python Meetup",
        "start": "2026-10-20T23:30:00Z",
        "end": "2026-10-21T01:30:00Z",
        "source_tz": "America/Chicago",
        "all_day": False,
        "location": {"venue": "AIM Institute", "city": "Omaha", "state": "NE", "online": False},
        "area": "omaha",
        "organizer_id": "org_omaha-python",
        "summary": "Lightning talks and pizza.",
        "categories": ["software-dev"],
        "original_url": "https://www.meetup.com/omaha-python/events/123/",
        "status": "scheduled",
        "review_state": "published",
        "visibility": "shown",
        "inferred": [],
        "listings": [listing()],
        "series_key": None,
        "first_seen": "2026-10-10T08:00:00Z",
        "last_verified": "2026-10-17T12:00:00Z",
    }
    data.update(overrides)
    return data


def source(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "src_omaha-python",
        "name": "Omaha Python",
        "url": "https://www.meetup.com/omaha-python/",
        "connector": "ical",
        "trust": "trusted",
        "origin": "preconfigured",
        "status": "active",
        "approved_count": 0,
        "rejected_count": 0,
        "added_at": "2026-10-17",
    }
    data.update(overrides)
    return data


# --- Event id, canonical URL, slug


def test_event_id_is_evt_plus_first_12_hex_of_sha256_of_canonical_url() -> None:
    url = "https://www.meetup.com/omaha-python/events/123/"
    expected = "evt_" + hashlib.sha256(url.encode()).hexdigest()[:12]
    assert event_id_for(url) == expected


@pytest.mark.parametrize(
    "variant",
    [
        "HTTPS://WWW.Meetup.com/omaha-python/events/123/",
        "https://www.meetup.com:443/omaha-python/events/123/",
        "https://www.meetup.com/omaha-python/events/123/#details",
        "https://www.meetup.com/omaha-python/events/123/?utm_source=x&utm_medium=email",
        "https://www.meetup.com/omaha-python/events/123/?fbclid=abc",
    ],
)
def test_equivalent_urls_share_one_canonical_form_and_id(variant: str) -> None:
    url = "https://www.meetup.com/omaha-python/events/123/"
    assert canonical_url(variant) == url
    assert event_id_for(variant) == event_id_for(url)


def test_canonical_url_keeps_meaningful_query_parameters() -> None:
    assert (
        canonical_url("https://example.com/e?id=7&utm_campaign=x") == "https://example.com/e?id=7"
    )


def test_canonical_url_rejects_unsafe_urls() -> None:
    with pytest.raises(ValueError, match="https"):
        canonical_url("http://example.com/")


def test_slug_comes_from_title_and_date() -> None:
    assert make_slug("Omaha Python: Lightning Talks!", date(2026, 10, 20)) == (
        "omaha-python-lightning-talks-2026-10-20"
    )
    assert make_slug("Café & Código", date(2026, 1, 2)) == "cafe-codigo-2026-01-02"
    assert make_slug("!!!", date(2026, 1, 2)) == "event-2026-01-02"
    assert len(make_slug("word " * 100, date(2026, 1, 2))) <= 80
    long_title = (
        "Drupal Nebraska Oct 2026/US Central Timezone Quarterly Meeting: AI Framework for Drupal"
    )
    assert make_slug(long_title, date(2026, 10, 21)) == (
        "drupal-nebraska-oct-2026-us-central-timezone-quarterly-meeting-ai-2026-10-21"
    )


# --- Event fields


def test_valid_event_round_trips_with_utc_z_times() -> None:
    model = Event.model_validate(event())
    dumped = model.model_dump(mode="json")
    assert dumped["start"] == "2026-10-20T23:30:00Z"
    assert dumped["listings"][0]["last_seen"] == "2026-10-17T12:00:00Z"
    assert Event.model_validate(dumped) == model


def test_offset_times_are_converted_to_utc_and_naive_times_rejected() -> None:
    model = Event.model_validate(event(start="2026-10-20T18:30:00-05:00", end=None))
    assert model.model_dump(mode="json")["start"] == "2026-10-20T23:30:00Z"
    with pytest.raises(ValidationError, match="time zone"):
        Event.model_validate(event(start="2026-10-20T23:30:00"))


def test_times_are_truncated_to_whole_seconds() -> None:
    model = Event.model_validate(event(start="2026-10-20T23:30:00.123456Z", end=None))
    assert model.start == datetime(2026, 10, 20, 23, 30, tzinfo=UTC)


@pytest.mark.parametrize("bad_id", ["evt_XYZ", "evt_123", "evt_0123456789abc", "0123456789ab"])
def test_event_id_pattern(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(event(id=bad_id))


@pytest.mark.parametrize(("length", "ok"), [(0, False), (1, True), (200, True), (201, False)])
def test_title_is_1_to_200_chars(length: int, ok: bool) -> None:
    data = event(title="x" * length)
    if ok:
        Event.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            Event.model_validate(data)


@pytest.mark.parametrize(
    "field",
    ["title", "summary"],
)
@pytest.mark.parametrize(
    "bad", ["<b>Bold</b>", "Hi <script>x</script>", "a\x00b", "zero\u200bwidth"]
)
def test_text_fields_must_be_plain_text(field: str, bad: str) -> None:
    with pytest.raises(ValidationError, match="plain text"):
        Event.model_validate(event(**{field: bad}))


def test_location_text_must_be_plain_text() -> None:
    with pytest.raises(ValidationError, match="plain text"):
        Event.model_validate(event(location={"venue": "<img src=x>", "online": False}))


def test_plain_text_may_contain_comparison_signs_and_ampersands() -> None:
    Event.model_validate(event(title="C++ & C# for 5 < 6 year olds"))


@pytest.mark.parametrize(("length", "ok"), [(0, True), (500, True), (501, False)])
def test_summary_is_at_most_500_chars(length: int, ok: bool) -> None:
    data = event(summary="x" * length)
    if ok:
        Event.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            Event.model_validate(data)


def test_end_must_not_be_before_start() -> None:
    with pytest.raises(ValidationError, match="end"):
        Event.model_validate(event(end="2026-10-20T23:29:59Z"))
    Event.model_validate(event(end="2026-10-20T23:30:00Z"))
    Event.model_validate(event(end=None))


@pytest.mark.parametrize("cats", [[], ["software-dev", "software-dev"], ["Software Dev"]])
def test_categories_need_at_least_one_unique_slug(cats: list[str]) -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(event(categories=cats))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/e",
        "javascript:alert(1)",
        "https://192.168.0.1/",
        "https://localhost/",
        "",
    ],
)
def test_original_url_is_https_only_with_a_public_hostname(url: str) -> None:
    with pytest.raises(ValidationError, match="https"):
        Event.model_validate(event(original_url=url))


def test_original_url_is_normalized() -> None:
    model = Event.model_validate(event(original_url="HTTPS://Example.COM:443/e"))
    assert model.original_url == "https://example.com/e"


@pytest.mark.parametrize(
    ("field", "good", "bad"),
    [
        ("area", ["omaha", "lincoln", "other_ne", "online"], "council_bluffs"),
        ("status", ["scheduled", "cancelled", "unverified"], "postponed"),
        ("review_state", ["published", "pending_review", "rejected"], "approved"),
        ("visibility", ["shown", "hidden"], "private"),
    ],
)
def test_event_enums(field: str, good: list[str], bad: str) -> None:
    for value in good:
        Event.model_validate(event(**{field: value}))
    with pytest.raises(ValidationError):
        Event.model_validate(event(**{field: bad}))


def test_source_tz_must_be_a_real_zone_and_tz_assumed_defaults_false() -> None:
    model = Event.model_validate(event())
    assert model.tz_assumed is False
    assert model.original_unavailable is False
    with pytest.raises(ValidationError, match="time zone"):
        Event.model_validate(event(source_tz="Mars/Olympus_Mons"))


def test_event_needs_at_least_one_listing() -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(event(listings=[]))


@pytest.mark.parametrize(
    "bad",
    [
        {"url": "http://example.com/"},
        {"content_hash": "abc"},
        {"missing_runs": -1},
        {"source_id": "omaha-python"},
    ],
)
def test_listing_constraints(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SourceListing.model_validate(listing(**bad))


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(event(rsvp_count=12))


def test_inferred_values_are_limited_and_unique() -> None:
    Event.model_validate(event(inferred=["area", "categories"]))
    with pytest.raises(ValidationError):
        Event.model_validate(event(inferred=["title"]))
    with pytest.raises(ValidationError):
        Event.model_validate(event(inferred=["area", "area"]))


def test_public_visibility_requires_published_and_shown() -> None:
    assert Event.model_validate(event()).is_public
    assert not Event.model_validate(event(visibility="hidden")).is_public
    assert not Event.model_validate(event(review_state="pending_review")).is_public


def test_assignments_are_validated() -> None:
    model = Event.model_validate(event())
    with pytest.raises(ValidationError):
        model.title = ""


# --- Source


def test_source_defaults() -> None:
    model = Source.model_validate(source())
    assert model.check_interval_hours == 12
    assert model.rate_limit_seconds == 5
    assert model.added_at == date(2026, 10, 17)


@pytest.mark.parametrize("hours", [0, 25])
def test_check_interval_is_at_most_24_hours(hours: int) -> None:
    with pytest.raises(ValidationError):
        Source.model_validate(source(check_interval_hours=hours))


@pytest.mark.parametrize(
    ("field", "good", "bad"),
    [
        ("trust", ["trusted", "probationary"], "verified"),
        ("origin", ["preconfigured", "admin", "discovered", "suggested"], "scraped"),
        ("status", ["active", "paused", "blocked_by_terms"], "deleted"),
        ("connector", ["ical", "rss", "jsonld", "eventbrite_org", "html_rules"], "meetup_api"),
    ],
)
def test_source_enums(field: str, good: list[str], bad: str) -> None:
    for value in good:
        Source.model_validate(source(**{field: value}))
    with pytest.raises(ValidationError):
        Source.model_validate(source(**{field: bad}))


def test_source_urls_are_https() -> None:
    with pytest.raises(ValidationError):
        Source.model_validate(source(url="http://example.com/"))
    with pytest.raises(ValidationError):
        Source.model_validate(source(feed_url="ftp://example.com/feed"))


# --- Candidate, mention, review item, override


def candidate(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "url": "https://omahadata.example.org/",
        "found_via": "suggestion",
        "evidence": ["suggested via the site form"],
        "result": "pending",
        "reason": "awaiting evaluation",
        "last_evaluated": "2026-10-17T12:00:00Z",
    }
    data.update(overrides)
    return data


def test_candidate_note_is_scrubbed_limited_and_never_serialized() -> None:
    model = CandidateSource.model_validate(
        candidate(note="Monthly meetup. Email jo@example.com or call 402-555-0199.")
    )
    assert model.note == "Monthly meetup. Email or call ."
    assert "note" not in model.model_dump(mode="json")
    assert "note" not in model.model_dump_json()
    with pytest.raises(ValidationError):
        CandidateSource.model_validate(candidate(note="x" * 281))


def test_candidate_result_enum() -> None:
    with pytest.raises(ValidationError):
        CandidateSource.model_validate(candidate(result="maybe"))


def test_mention_links_lose_query_and_fragment() -> None:
    model = EventMention.model_validate(
        {
            "id": "men_0123456789ab",
            "channel": "newsletter",
            "title": "Lincoln DevOps night",
            "date_hint": "Nov 5",
            "place_hint": None,
            "organizer_hint": None,
            "links": ["https://lincolndevops.example.org/events/nov?utm_source=mail#rsvp"],
            "resolution": "unresolved",
            "event_id": None,
            "attempts": 0,
        }
    )
    assert model.links == ["https://lincolndevops.example.org/events/nov"]


def test_review_item_constraints() -> None:
    base = {
        "id": "rev_0123456789ab",
        "kind": "event",
        "ref": "evt_0123456789ab",
        "reason": "probationary source",
        "created": "2026-10-17T12:00:00Z",
        "decision": "pending",
        "decided_in_pr": None,
    }
    ReviewItem.model_validate(base)
    with pytest.raises(ValidationError):
        ReviewItem.model_validate({**base, "decision": "maybe"})
    with pytest.raises(ValidationError):
        ReviewItem.model_validate({**base, "id": "rev_1"})


def test_override_cannot_touch_protected_fields() -> None:
    Override.model_validate(
        {"event_id": "evt_0123456789ab", "visibility": "hidden", "reason": "spam"}
    )
    for field, value in [
        ("original_url", "https://x.example.com/"),
        ("review_state", "published"),
        ("trust", "trusted"),
    ]:
        with pytest.raises(ValidationError):
            Override.model_validate({"event_id": "evt_0123456789ab", "reason": "x", field: value})


def test_raw_listing_accepts_untrusted_input_as_is() -> None:
    raw = RawListing(
        external_id=None,
        url="javascript:alert(1)",
        title="<b>Raw</b>",
        start=datetime(2026, 10, 20, 18, 30),  # naive is allowed before normalization
        end=None,
        tz=None,
        all_day=False,
        location_text=None,
        online=False,
        organizer_text=None,
        description_text="<script>x</script>",
        cancelled=False,
    )
    assert raw.title == "<b>Raw</b>"


# --- Model output validates against the JSON Schemas (T028)


SAMPLES: list[tuple[type[BaseModel], str, dict[str, Any]]] = [
    (Event, "event", event()),
    (Event, "event", event(end=None, tz_assumed=True, inferred=["area"], series_key="omaha-py")),
    (Source, "source", source()),
    (
        Source,
        "source",
        source(
            connector="html_rules",
            trust="probationary",
            origin="discovered",
            found_via="web_search",
            feed_url=None,
            default_area="lincoln",
            html_rules={"item": ".event", "title": "h2", "start": "time", "link": "a"},
            notes="Found by search.",
            updated_at="2026-10-18",
        ),
    ),
    (CandidateSource, "candidate", candidate(note="private")),
    (
        EventMention,
        "mention",
        {
            "id": "men_0123456789ab",
            "channel": "news",
            "title": "Hack Omaha",
            "date_hint": None,
            "place_hint": "Omaha",
            "organizer_hint": None,
            "links": ["https://hackomaha.example.org/"],
            "resolution": "held",
            "event_id": "evt_0123456789ab",
            "attempts": 2,
        },
    ),
    (
        ReviewItem,
        "review_item",
        {
            "id": "rev_0123456789ab",
            "kind": "source",
            "ref": "src_omaha-python",
            "reason": "new source",
            "created": "2026-10-17T12:00:00Z",
            "decision": "approved",
            "decided_in_pr": 12,
        },
    ),
    (
        KnownGroup,
        "known_group",
        {
            "name": "ISACA Omaha",
            "aliases": ["ISACA Omaha Chapter"],
            "area": "omaha",
            "links": ["https://engage.isaca.org/omahachapter/home"],
            "source_ids": [],
            "last_searched": None,
            "cadence_days": 30,
            "status": "active",
        },
    ),
    (
        Category,
        "category",
        {"id": "security", "label": "Security", "keywords": ["owasp", "infosec"]},
    ),
    (
        Organizer,
        "organizer",
        {
            "id": "org_omaha-python",
            "name": "Omaha Python",
            "home_city": "Omaha",
            "url": None,
            "aliases": [],
        },
    ),
    (
        Override,
        "override",
        {"event_id": "evt_0123456789ab", "categories": ["security"], "reason": "fix"},
    ),
    (
        SourceStatus,
        "source_status",
        {
            "last_attempt": "2026-10-17T12:00:00Z",
            "last_success": None,
            "last_error": "HTTP 503",
            "consecutive_failures": 1,
            "events_found_last_run": None,
        },
    ),
    (
        SearchUsage,
        "search_usage",
        {"month": "2026-10", "used": 3, "last_run": {"Omaha tech meetup": "2026-10-20"}},
    ),
    (
        AiCacheEntry,
        "ai_cache_entry",
        {
            "key": "b" * 64,
            "kind": "extract",
            "model": "gpt-5-nano-2025-08-07",
            "at": "2026-10-20T12:00:00Z",
            "result": {"mentions": []},
            "input_tokens": 10,
            "cached_tokens": 0,
            "output_tokens": 2,
        },
    ),
]


@pytest.mark.parametrize(("model", "schema_name", "data"), SAMPLES)
def test_model_json_output_validates_against_its_schema(
    model: type[BaseModel], schema_name: str, data: dict[str, Any]
) -> None:
    dumped = json.loads(model.model_validate(data).model_dump_json())
    Draft202012Validator(load_schema(schema_name)).validate(dumped)


@pytest.mark.parametrize("name", ["event", "source"])
def test_packaged_contract_schemas_match_the_spec(name: str) -> None:
    spec = json.loads((SPECS / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert load_schema(name) == spec


@pytest.mark.parametrize(
    "name",
    [
        "event",
        "source",
        "candidate",
        "mention",
        "review_item",
        "known_group",
        "category",
        "organizer",
        "override",
        "source_status",
        "search_usage",
        "ai_cache_entry",
    ],
)
def test_every_schema_is_a_valid_draft_2020_12_schema(name: str) -> None:
    Draft202012Validator.check_schema(load_schema(name))
