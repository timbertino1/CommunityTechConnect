"""Place text to a Nebraska area, including the look-alike traps."""

from __future__ import annotations

from pathlib import Path

import pytest

from netc.models import AreaConfig
from netc.pipeline.places import match_place
from netc.storage import DataStore

pytestmark = pytest.mark.unit

AREAS: AreaConfig = DataStore(Path(__file__).resolve().parents[3] / "data").read_areas()  # type: ignore[assignment]


@pytest.mark.parametrize(
    ("text", "state"),
    [
        ("Javits Center, New York, NY 10001", "NY"),  # "York" is also a Nebraska town
        ("Lincoln Center, Lincoln, CA", "CA"),  # so is "Lincoln"
        ("Coffee shop, Denver, Colorado", "CO"),
        ("Mid-America Center, Council Bluffs, IA 51501", "IA"),
        ("Somewhere, Kansas City, MO", "MO"),
    ],
)
def test_other_states_are_out_of_state(text: str, state: str) -> None:
    match = match_place(text, AREAS)
    assert match.out_of_state is True
    assert match.area is None
    assert match.state == state


@pytest.mark.parametrize(
    ("text", "area"),
    [
        ("Office, 1200 Washington St, Omaha, NE", "omaha"),  # a street named after a state
        ("Hall, York, NE 68467", "other_ne"),
        ("Venue, Lincoln, Nebraska", "lincoln"),
        ("Talk, online or in person, Omaha", "omaha"),  # "or" is not Oregon
        ("Startup space in South Sioux City", "other_ne"),
    ],
)
def test_nebraska_places_are_not_mistaken_for_other_states(text: str, area: str) -> None:
    match = match_place(text, AREAS)
    assert match.out_of_state is False
    assert match.area == area


def test_a_street_number_is_not_taken_for_a_zip() -> None:
    match = match_place("Improving, 18881 W Dodge Road Suite 120E, Omaha, NE", AREAS)
    assert match.area == "omaha"
    assert match.how == "city"


def test_empty_text_matches_nothing() -> None:
    assert match_place("", AREAS).how == "none"
    assert match_place(None, AREAS).how == "none"
