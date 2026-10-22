"""Self-hosted fonts (T150; research R15): Latin-subset woff2 in web/fonts/ with their licenses,
at most 120 KB in all, `font-display: swap`, two preloads, and nothing from Google Fonts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FONTS = ROOT / "web" / "fonts"
CSS = (ROOT / "web" / "css" / "site.css").read_text(encoding="utf-8")
BASE = (ROOT / "discovery" / "src" / "netc" / "site" / "templates" / "base.html").read_text(
    encoding="utf-8"
)
FONT_FACES = re.findall(r"@font-face\s*\{([^}]*)\}", CSS)
BUDGET_BYTES = 120 * 1024


def woff2_files() -> list[Path]:
    return sorted(FONTS.glob("*.woff2"))


def test_fonts_fit_the_budget() -> None:
    assert sum(f.stat().st_size for f in woff2_files()) <= BUDGET_BYTES


def test_every_font_is_woff2() -> None:
    assert woff2_files()
    for font in woff2_files():
        assert font.read_bytes()[:4] == b"wOF2", font.name


@pytest.mark.parametrize("family", ["archivo", "inter", "jetbrains-mono"])
def test_each_family_has_its_font_and_ofl_license(family: str) -> None:
    assert list(FONTS.glob(f"{family}-latin-*.woff2"))
    license_text = (FONTS / f"OFL-{family}.txt").read_text(encoding="utf-8")
    assert "SIL Open Font License" in license_text or "SIL OPEN FONT LICENSE" in license_text


def test_each_font_face_swaps_and_points_at_a_real_file() -> None:
    assert len(FONT_FACES) == len(woff2_files())
    used = set()
    for face in FONT_FACES:
        assert "font-display: swap" in face
        [url] = re.findall(r"url\(\"?/fonts/([^)\"]+)\"?\)", face)
        assert (FONTS / url).is_file()
        used.add(url)
    assert used == {f.name for f in woff2_files()}


def test_only_two_fonts_are_preloaded() -> None:
    preloads = re.findall(r"<link rel=\"preload\"[^>]*>", BASE)
    assert len(preloads) == 2
    for link in preloads:
        assert 'as="font"' in link and 'type="font/woff2"' in link and "crossorigin" in link
        [href] = re.findall(r'href="/fonts/([^"]+)"', link)
        assert (FONTS / href).is_file()


def test_no_google_fonts() -> None:
    templates = ROOT / "discovery" / "src" / "netc" / "site" / "templates"
    sources = [*(ROOT / "web").rglob("*.css"), *(ROOT / "web").rglob("*.html"),
               *templates.rglob("*.html")]  # fmt: skip
    for path in sources:
        if "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "fonts.googleapis.com" not in text and "fonts.gstatic.com" not in text, path
