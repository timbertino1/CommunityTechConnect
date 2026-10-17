"""Place text to a Nebraska area, using data/areas.yaml (FR-003, FR-036).

Order: an explicit other state ("Lincoln, CA", "Denver, Colorado") or a listed out-of-state place
wins first, so Nebraska town names that also exist elsewhere are not misplaced. Then a known venue,
a city, an exact ZIP, a ZIP prefix (Omaha and Lincoln before the rest of Nebraska), and finally a
bare "NE"/"Nebraska" for the rest of the state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

from netc.models import Area, AreaConfig

type How = Literal[
    "state_other", "out_of_state", "venue", "city", "zip", "zip_prefix", "state", "none"
]

_STATES: Final = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}  # fmt: skip

# A state code or name only counts right after a comma ("Omaha, NE", "Denver, Colorado"), so street
# names such as "Washington St" or a word like "OR" are not read as states.
_STATE_AFTER_COMMA: Final = re.compile(
    r",\s*(?P<state>"
    + "|".join(sorted({*_STATES, *_STATES.values()}, key=len, reverse=True))
    + r")(?=\s+\d{5}|\s*,|\s*$|\s+(?:USA|US|United States)\b)",
    re.IGNORECASE,
)
_NEBRASKA_WORD: Final = re.compile(r"\bNebraska\b", re.IGNORECASE)
_ZIP: Final = re.compile(r"(?<!\d)(\d{5})(?:-\d{4})?(?!\d)")
_NAME_TO_CODE: Final = {name.casefold(): code for code, name in _STATES.items()}


@dataclass(frozen=True)
class PlaceMatch:
    area: Area | None
    city: str | None
    state: str | None
    """Two-letter code when the text names a state."""
    out_of_state: bool
    how: How


def match_place(text: str | None, areas: AreaConfig) -> PlaceMatch:
    if not text or not text.strip():
        return PlaceMatch(None, None, None, False, "none")
    folded = text.casefold()
    state = _state(text)
    city_area, city = _city(text, areas)

    for place in areas.out_of_state:
        if _has_word(folded, place.name.casefold()) or any(z in text for z in place.zips):
            return PlaceMatch(None, place.name, place.state, True, "out_of_state")
    if state is not None and state != "NE":
        return PlaceMatch(None, city, state, True, "state_other")

    for area in areas.areas:
        if any(venue.casefold() in folded for venue in area.venues):
            return PlaceMatch(area.id, city, state or "NE", False, "venue")
    if city_area is not None:
        return PlaceMatch(city_area, city, state or "NE", False, "city")

    zips = _ZIP.findall(text)
    if zips:
        code = zips[-1]
        for area in areas.areas:
            if code in area.zips:
                return PlaceMatch(area.id, None, "NE", False, "zip")
        for area_id in ("omaha", "lincoln", "other_ne"):
            if code[:3] in areas.area(area_id).zip_prefixes:
                return PlaceMatch(area_id, None, "NE", False, "zip_prefix")

    if state == "NE" or _NEBRASKA_WORD.search(text):
        return PlaceMatch("other_ne", None, "NE", False, "state")
    return PlaceMatch(None, None, None, False, "none")


def _state(text: str) -> str | None:
    found = [m.group("state") for m in _STATE_AFTER_COMMA.finditer(text)]
    if not found:
        return None
    last = found[-1]
    return last.upper() if len(last) == 2 else _NAME_TO_CODE[last.casefold()]


def _city(text: str, areas: AreaConfig) -> tuple[Area | None, str | None]:
    """The longest gazetteer city named as a whole word (so "South Sioux City" beats "City")."""
    folded = text.casefold()
    best: tuple[int, Area | None, str | None] = (0, None, None)
    for area in areas.areas:
        for city in area.cities:
            if len(city) > best[0] and _has_word(folded, city.casefold()):
                best = (len(city), area.id, city)
    return best[1], best[2]


def _has_word(folded_text: str, folded_phrase: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(folded_phrase)}(?![\w])", folded_text) is not None
