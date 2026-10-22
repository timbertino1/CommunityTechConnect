"""`netc build-site` writes /data/map.json for the home page's header map (T152; research R15)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.data_samples import utc
from tests.site_support import build, make_data, site_event

pytestmark = pytest.mark.integration


def at(city: str | None, **overrides: Any) -> dict[str, Any]:
    location = {"venue": None, "city": city, "state": "NE", "online": False}
    return {"location": location, **overrides}


def map_json(tmp_path: Path, *events: Any) -> dict[str, Any]:
    data = make_data(tmp_path / "data", list(events))
    assert build(data, tmp_path / "site") == 0
    result: dict[str, Any] = json.loads((tmp_path / "site" / "data" / "map.json").read_text())
    return result


def test_pins_are_upcoming_event_cities_with_counts(tmp_path: Path) -> None:
    result = map_json(
        tmp_path,
        site_event("https://a.example.org/1", "One", utc(2026, 11, 1), "one", **at("Omaha")),
        site_event("https://a.example.org/2", "Two", utc(2026, 11, 2), "two", **at("omaha")),
        site_event(
            "https://a.example.org/3",
            "Three",
            utc(2026, 11, 3),
            "three",
            **at("Kearney", area="other_ne"),
        ),
    )
    assert result["pins"] == [
        {"city": "Kearney", "lat": 40.7, "lon": -99.08, "events": 1},
        {"city": "Omaha", "lat": 41.26, "lon": -95.94, "events": 2},
    ]


def test_no_pin_for_past_cancelled_online_unreviewed_or_unknown_cities(tmp_path: Path) -> None:
    result = map_json(
        tmp_path,
        site_event("https://a.example.org/p", "Past", utc(2026, 9, 1), "past", **at("Omaha")),
        site_event("https://a.example.org/c", "Off", utc(2026, 11, 1), "off",
                   **at("Lincoln", area="lincoln", status="cancelled")),
        site_event("https://a.example.org/o", "Remote", utc(2026, 11, 1), "remote",
                   location={"venue": None, "city": None, "state": None, "online": True},
                   area="online"),
        site_event("https://a.example.org/r", "Review", utc(2026, 11, 1), "review",
                   **at("Omaha", review_state="pending_review")),
        site_event("https://a.example.org/u", "Nowhere", utc(2026, 11, 1), "nowhere",
                   **at("Smallville", area="other_ne")),
    )  # fmt: skip
    assert result["pins"] == []


def test_towns_are_every_point_in_the_table(tmp_path: Path) -> None:
    towns = map_json(tmp_path)["towns"]
    names = [t["name"] for t in towns]
    assert names == sorted(names)
    assert {"name": "Scottsbluff", "lat": 41.87, "lon": -103.67} in towns
    assert all(set(t) == {"name", "lat", "lon"} for t in towns)
