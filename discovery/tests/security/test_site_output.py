"""Built site security (T055; FR-039, FR-047, contracts/site-urls.md headers)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from selectolax.lexbor import LexborHTMLParser

from netc.connectors.jsonld import JsonLdConnector
from netc.models import Event
from netc.pipeline.normalize import Normalized, normalize, to_event
from netc.storage import DataStore
from tests.connector_support import fixture_text, jsonld_source, payload
from tests.data_samples import utc
from tests.site_support import NOW_DT, ROOT, build, html_files, make_data, site_event

pytestmark = pytest.mark.security

CONTRACT_HEADERS = [
    "Content-Security-Policy: default-src 'self'; script-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; style-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'",
    "Strict-Transport-Security: max-age=63072000; includeSubDomains",
    "X-Content-Type-Options: nosniff",
    "Referrer-Policy: strict-origin-when-cross-origin",
    "Permissions-Policy: camera=(), microphone=(), geolocation=()",
]


def hostile_events() -> list[Event]:
    """Events built through the real pipeline from the malicious fixture page, plus text that
    is legal plain text but must still be escaped in HTML."""
    areas = DataStore(ROOT / "data").read_areas()
    assert areas is not None
    source = jsonld_source(default_area="omaha")
    result = JsonLdConnector().parse(
        source, payload(fixture_text("jsonld/malicious.html"), content_type="text/html")
    )
    built: list[Event] = []
    for raw in result.listings:
        item = normalize(raw, source, areas, now=NOW_DT)
        if isinstance(item, Normalized):
            built.append(
                to_event(item, categories=["general-tech"], review_state="published", now=NOW_DT)
            )
    built.append(
        site_event(
            "https://quotes.example.org/e",
            "5 < 6 & \"quotes\" 'too'",
            utc(2026, 11, 3),
            "quotes-2026-11-02",
            summary="Bring a laptop & charger (5 < 6 > 4)",
        )
    )
    return built


@pytest.fixture
def site(tmp_path: Path) -> Path:
    data = make_data(tmp_path / "data", hostile_events())
    out = tmp_path / "dist"
    assert build(data, out) == 0
    return out


def test_payloads_are_escaped_as_text(site: Path) -> None:
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "5 &lt; 6 &amp; " in index
    detail = (site / "events" / "quotes-2026-11-02" / "index.html").read_text(encoding="utf-8")
    assert "Bring a laptop &amp; charger (5 &lt; 6 &gt; 4)" in detail
    assert "&#34;quotes&#34;" in index or "&quot;quotes&quot;" in index
    assert "javascript:" not in index.lower()
    for page in html_files(site).values():
        assert "<script>alert" not in page
        assert "onerror" not in page.lower()


def test_no_inline_scripts_styles_or_event_handlers(site: Path) -> None:
    for name, page in html_files(site).items():
        tree = LexborHTMLParser(page)
        for script in tree.css("script"):
            assert script.attributes.get("src"), f"inline script in {name}"
        assert tree.css("style") == [], name
        for node in tree.css("*"):
            for attr in node.attributes:
                assert not attr.lower().startswith("on"), (name, attr)
                assert attr.lower() != "style", (name, attr)


# The one exception: /suggest/ loads Cloudflare Turnstile's script and posts to the suggestion
# Worker (FR-039); tests/integration/test_build_site_suggest.py checks exactly that.
SUGGEST_PAGE = "suggest/index.html"


def test_pages_load_nothing_from_other_hosts(site: Path) -> None:
    for name, page in html_files(site).items():
        if name == SUGGEST_PAGE:
            continue
        tree = LexborHTMLParser(page)
        for node in tree.css(
            "script[src], link[href], img[src], iframe, source[src], video, audio, embed, object"
        ):
            ref = node.attributes.get("src") or node.attributes.get("href") or ""
            assert not urlsplit(ref).netloc, (name, ref)


FILTER_FIELDS = {"area": "checkbox", "from": "date", "to": "date", "q": "search"}


def test_no_forms_ask_for_personal_information(site: Path) -> None:
    # The only form is the event filter (T112): it reads the page's own events in the browser,
    # sends nothing anywhere, and has no field for anything about the visitor. (The suggestion
    # form, which asks for an address and an optional note only, is checked on its own.)
    for name, page in html_files(site).items():
        if name == SUGGEST_PAGE:
            continue
        tree = LexborHTMLParser(page)
        for form in tree.css("form"):
            assert form.attributes.get("role") == "search", name
            assert (form.attributes.get("method") or "get").lower() == "get", name
            assert (form.attributes.get("action") or "") == "", name
        for field in tree.css("input"):
            kind = FILTER_FIELDS.get(field.attributes.get("name") or "")
            assert kind is not None and field.attributes.get("type") == kind, (name, field.html)
        for select in tree.css("select"):
            assert select.attributes.get("name") == "cat", name


def test_headers_file_has_the_exact_contract_headers(site: Path) -> None:
    lines = [line.strip() for line in (site / "_headers").read_text(encoding="utf-8").splitlines()]
    assert lines[0] == "/*"
    for header in CONTRACT_HEADERS:
        assert header in lines


def test_external_links_do_not_leak_referrers_or_window_access(site: Path) -> None:
    tree = LexborHTMLParser((site / "index.html").read_text(encoding="utf-8"))
    for link in tree.css("a[href^='https://']"):
        assert "noopener" in (link.attributes.get("rel") or "")
