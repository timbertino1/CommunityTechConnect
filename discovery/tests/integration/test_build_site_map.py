"""`netc build-site` and the home page's header map: /data/map.json (T152) and the page markup,
vendored three.js and static image (T153); research R15."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from selectolax.lexbor import LexborHTMLParser

from netc.cli import main
from tests.data_samples import utc
from tests.site_support import NOW, WEB, build, html_files, make_data, site_event

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


# --- The header map on the page (T153)


def pages(tmp_path: Path) -> dict[str, LexborHTMLParser]:
    data = make_data(tmp_path / "data", [])
    assert build(data, tmp_path / "site") == 0
    return {k: LexborHTMLParser(v) for k, v in html_files(tmp_path / "site").items()}


def test_the_home_page_has_a_hidden_decorative_map(tmp_path: Path) -> None:
    home = pages(tmp_path)["index.html"]
    [box] = home.css("[data-header-map]")
    assert box.attributes["aria-hidden"] == "true"
    [canvas] = box.css("canvas")
    [still] = box.css("img")
    assert "hidden" in canvas.attributes and "hidden" in still.attributes
    assert still.attributes["alt"] == ""
    # The loader is an external module (CSP script-src 'self'); the title stays real text.
    scripts = [s.attributes for s in home.css("script")]
    assert scripts == [
        {"type": "module", "src": "/js/home.js"},
        {"type": "module", "src": "/js/filters.js"},  # T113
    ]
    [h1] = home.css("h1")
    assert " ".join(h1.text().split()) == "Every Nebraska tech event, in one place."


def test_other_pages_have_no_map(tmp_path: Path) -> None:
    for name, page in pages(tmp_path).items():
        if name != "index.html":
            assert not page.css("[data-header-map]"), name
            assert not [
                s for s in page.css("script") if s.attributes.get("src") == "/js/home.js"
            ], name


def test_build_copies_the_vendored_three_js(tmp_path: Path) -> None:
    web = tmp_path / "web"
    shutil.copytree(WEB, web, ignore=shutil.ignore_patterns("node_modules", "vendor"))
    (web / "vendor").mkdir()
    (web / "vendor" / "three.js").write_text("export const Scene = 1;\n")
    data = make_data(tmp_path / "data", [])
    out = tmp_path / "site"
    assert main(["build-site", "--data", str(data), "--out", str(out), "--web", str(web),
                 "--now", NOW]) == 0  # fmt: skip
    assert (out / "vendor" / "three.js").read_text() == "export const Scene = 1;\n"
    assert sorted(p.name for p in (out / "vendor").iterdir()) == ["three.js"]


def test_the_static_image_is_a_small_webp() -> None:
    image = (WEB / "img" / "header-map.webp").read_bytes()
    assert image[:4] == b"RIFF" and image[8:12] == b"WEBP"
    assert len(image) <= 40 * 1024


def test_only_header_map_js_imports_three() -> None:
    importers = sorted(
        p.name for p in (WEB / "js").glob("*.js") if "/vendor/three.js" in p.read_text()
    )
    assert importers == ["header-map.js"]
