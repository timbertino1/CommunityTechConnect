"""The seed reference data in data/: categories.yaml (T035) and areas.yaml (T036)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from netc.models import AreaConfig
from netc.storage import DataStore, read_raw

pytestmark = pytest.mark.unit

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
STORE = DataStore(REPO_DATA)

SEED_CATEGORIES = [
    ("ai-ml", "AI & Machine Learning"),
    ("security", "Information Security / Cybersecurity"),
    ("software-dev", "Software Development & Programming"),
    ("networking-infra", "Computer Networking & Infrastructure"),
    ("cloud-devops", "Cloud & DevOps"),
    ("data-analytics", "Data & Analytics"),
    ("web-mobile", "Web & Mobile"),
    ("product-design-ux", "Product, Design & UX"),
    ("career-networking", "Career & Professional Networking"),
    ("hardware-iot-makers", "Hardware, IoT & Makers"),
    ("general-tech", "General Tech"),
]


# --- categories.yaml


def test_categories_are_the_fr028_seed_list_in_display_order() -> None:
    assert [(c.id, c.label) for c in STORE.read_categories()] == SEED_CATEGORIES


@pytest.mark.parametrize("category", STORE.read_categories(), ids=lambda c: c.id)
def test_each_category_has_useful_lowercase_keywords(category: Any) -> None:
    assert len(category.keywords) >= 10
    assert all(k == k.lower().strip() for k in category.keywords)


@pytest.mark.parametrize("word", ["it", "data", "meeting", "event", "free", "online", "the"])
def test_no_keyword_is_an_everyday_word(word: str) -> None:
    keywords = {k for c in STORE.read_categories() for k in c.keywords}
    assert word not in keywords


# --- areas.yaml


def test_areas_file_lists_the_four_filter_areas() -> None:
    areas = STORE.read_areas()
    assert areas is not None
    assert [(a.id, a.label) for a in areas.areas] == [
        ("omaha", "Omaha area"),
        ("lincoln", "Lincoln area"),
        ("other_ne", "Other Nebraska"),
        ("online", "Online"),
    ]


@pytest.mark.parametrize(
    "city",
    [
        "Omaha",
        "Bellevue",
        "Papillion",
        "La Vista",
        "Ralston",
        "Elkhorn",
        "Gretna",
        "Bennington",
        "Offutt AFB",
    ],
)
def test_required_omaha_area_cities(city: str) -> None:
    areas = STORE.read_areas()
    assert areas is not None
    assert city in areas.area("omaha").cities


def test_lincoln_and_lancaster_county() -> None:
    areas = STORE.read_areas()
    assert areas is not None
    lincoln = areas.area("lincoln")
    assert "Lincoln" in lincoln.cities
    assert "Waverly" in lincoln.cities
    assert "685" in lincoln.zip_prefixes
    assert "681" in areas.area("omaha").zip_prefixes


def test_council_bluffs_is_out_of_state() -> None:
    areas = STORE.read_areas()
    assert areas is not None
    council_bluffs = next(p for p in areas.out_of_state if p.name == "Council Bluffs")
    assert council_bluffs.state == "IA"
    assert "51501" in council_bluffs.zips


# --- AreaConfig rules


def raw_areas() -> dict[str, Any]:
    data: dict[str, Any] = read_raw(REPO_DATA / "areas.yaml")
    return copy.deepcopy(data)


def test_a_city_cannot_be_in_two_areas() -> None:
    data = raw_areas()
    data["areas"][1]["cities"].append("Omaha")
    with pytest.raises(ValidationError, match="both omaha and lincoln"):
        AreaConfig.model_validate(data)


def test_a_zip_must_be_in_nebraska() -> None:
    data = raw_areas()
    data["areas"][0]["zips"].append("51501")
    with pytest.raises(ValidationError, match="Nebraska ZIP"):
        AreaConfig.model_validate(data)


def test_all_four_areas_are_required() -> None:
    data = raw_areas()
    data["areas"] = data["areas"][:3]
    with pytest.raises(ValidationError, match="exactly once"):
        AreaConfig.model_validate(data)


def test_out_of_state_place_cannot_also_be_a_nebraska_city() -> None:
    data = raw_areas()
    data["out_of_state"].append({"name": "Omaha", "state": "IA", "zips": []})
    with pytest.raises(ValidationError, match="both in Nebraska and out of state"):
        AreaConfig.model_validate(data)
