"""Event.published_at and Event.changed_at (feature 002 T002; 002 data-model.md)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError
from pydantic import ValidationError as ModelError

from netc.models import load_schema
from tests.data_samples import make_event, utc

pytestmark = pytest.mark.unit

FIRST_SEEN = utc(2026, 10, 10, 8)


def dumped(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(make_event(**overrides).model_dump_json())
    return data


def test_both_default_to_null() -> None:
    event = make_event()
    assert event.published_at is None
    assert event.changed_at is None
    data = dumped()
    assert data["published_at"] is None
    assert data["changed_at"] is None


def test_they_serialize_as_utc_z_strings() -> None:
    data = dumped(published_at=utc(2026, 10, 11, 9), changed_at=utc(2026, 10, 12, 10, 30))
    assert data["published_at"] == "2026-10-11T09:00:00Z"
    assert data["changed_at"] == "2026-10-12T10:30:00Z"


def test_published_before_first_seen_is_refused() -> None:
    with pytest.raises(ModelError, match="published_at"):
        make_event(first_seen=FIRST_SEEN, published_at=utc(2026, 10, 9))


def test_changed_before_published_is_refused() -> None:
    with pytest.raises(ModelError, match="changed_at"):
        make_event(published_at=utc(2026, 10, 12), changed_at=utc(2026, 10, 11))


def test_changed_without_published_is_allowed() -> None:
    """Events stored before feature 002 have no published_at; a later change still records."""
    assert make_event(changed_at=utc(2026, 10, 9)).changed_at == utc(2026, 10, 9)


def test_schema_accepts_the_fields_and_still_refuses_unknown_ones() -> None:
    validator = Draft202012Validator(load_schema("event"))
    validator.validate(dumped())
    validator.validate(dumped(published_at=utc(2026, 10, 11), changed_at=utc(2026, 10, 12)))
    with pytest.raises(ValidationError):
        validator.validate({**dumped(), "updated_at": "2026-10-12T00:00:00Z"})
