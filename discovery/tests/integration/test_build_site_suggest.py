"""`netc build-site`: the /suggest/ page (T132; FR-020, FR-022, contracts/workers.md section 1,
contracts/site-urls.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from selectolax.lexbor import LexborHTMLParser

from netc.cli import main
from netc.site.build import SUGGEST_ENDPOINT, TURNSTILE_SITE_KEY
from tests.data_samples import utc
from tests.site_support import NOW, WEB, build, html_files, make_data, site_event

pytestmark = pytest.mark.integration

ENDPOINT = "https://netc-suggest.example-acct.workers.dev/suggest"
NOTICE = (
    "The address you suggest may become public. Notes are private, used only to evaluate your "
    "suggestion, and deleted after 30 days. Please don't include personal information."
)
TURNSTILE_SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js"
SUGGEST_CSP = (
    "Content-Security-Policy: default-src 'self'; script-src 'self' "
    "https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; "
    "connect-src 'self' https://netc-suggest.example-acct.workers.dev; img-src 'self' data:; "
    "style-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action https://netc-suggest.example-acct.workers.dev; frame-ancestors 'none'"
)


def data(tmp_path: Path) -> Path:
    event = site_event("https://a.example.org/e", "Rust Night", utc(2026, 11, 10, 23),
                       "rust-night-2026-11-10")  # fmt: skip
    return make_data(tmp_path / "data", [event])


@pytest.fixture
def site(tmp_path: Path) -> Path:
    out = tmp_path / "dist"
    args = ["build-site", "--data", str(data(tmp_path)), "--out", str(out), "--web", str(WEB)]
    assert main([*args, "--now", NOW, "--suggest-endpoint", ENDPOINT]) == 0
    return out


def page(out: Path, path: str) -> Any:
    return LexborHTMLParser((out / path / "index.html").read_text(encoding="utf-8"))


def flat(node: Any) -> str:
    return " ".join(node.text().split())


def test_without_an_endpoint_there_is_no_form_or_link(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    args = ["build-site", "--data", str(data(tmp_path)), "--out", str(out), "--web", str(WEB)]
    assert main([*args, "--now", NOW, "--suggest-endpoint", ""]) == 0
    assert not (out / "suggest").exists()
    pages = html_files(out)
    assert not any(
        "/suggest/" in text or "challenges.cloudflare.com" in text for text in pages.values()
    )
    assert "/suggest/*" not in (out / "_headers").read_text(encoding="utf-8")


def test_the_form_posts_the_address_and_note_to_the_worker(site: Path) -> None:
    form = page(site, "suggest").css_first("form[data-suggest]")
    assert form.attributes["method"] == "post"
    assert form.attributes["action"] == ENDPOINT
    url = form.css_first('input[name="url"]')
    assert url.attributes["type"] == "url" and "required" in url.attributes
    assert url.attributes["maxlength"] == "2048"
    note = form.css_first('textarea[name="note"]')
    assert note.attributes["maxlength"] == "280"
    labels = {flat(label) for label in form.css("label")}
    assert labels == {"Web address", "Note (optional)"}
    for field in (url, note):
        assert form.css_first(f'label[for="{field.attributes["id"]}"]') is not None


def test_the_privacy_notice_is_shown_word_for_word(site: Path) -> None:
    assert flat(page(site, "suggest").css_first("form .notice")) == NOTICE


def test_turnstile_uses_the_public_site_key(site: Path) -> None:
    widget = page(site, "suggest").css_first("form .cf-turnstile")
    assert widget.attributes["data-sitekey"] == TURNSTILE_SITE_KEY
    assert TURNSTILE_SITE_KEY.startswith("0x")


def test_the_result_is_announced(site: Path) -> None:
    status = page(site, "suggest").css_first("[data-suggest-status]")
    assert status.attributes["role"] == "status"


def test_every_page_links_to_the_form(site: Path) -> None:
    for name, text in html_files(site).items():
        if name == "404.html" or name.startswith("calendar/index"):
            continue
        tree = LexborHTMLParser(text)
        assert tree.css_first('footer a[href="/suggest/"]') is not None, name
    about = flat(page(site, "about"))
    assert "Suggest it" in about and "Cloudflare Turnstile" in about


def test_only_the_suggest_page_loads_turnstile_and_nothing_else_is_external(site: Path) -> None:
    for name, text in html_files(site).items():
        tree = LexborHTMLParser(text)
        external = [
            node.attributes.get("src") or node.attributes.get("href") or ""
            for node in tree.css("script[src], link[href], img[src], iframe")
            if urlsplit(node.attributes.get("src") or node.attributes.get("href") or "").netloc
        ]
        assert external == ([TURNSTILE_SCRIPT] if name == "suggest/index.html" else []), name


def test_the_suggest_form_asks_for_nothing_personal(site: Path) -> None:
    form = page(site, "suggest").css_first("form[data-suggest]")
    names = {f.attributes.get("name") for f in form.css("input, textarea, select")}
    assert names == {"url", "note"}


def test_headers_get_the_suggest_block_replacing_the_site_csp(site: Path) -> None:
    lines = [line.strip() for line in (site / "_headers").read_text(encoding="utf-8").splitlines()]
    block = lines[lines.index("/suggest/*") :]
    assert block[1] == "! Content-Security-Policy"
    assert block[2] == SUGGEST_CSP
    assert lines[0] == "/*"  # the site-wide rules are still first


def test_the_deployed_worker_is_the_default(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    assert build(data(tmp_path), out) == 0
    form = page(out, "suggest").css_first("form[data-suggest]")
    assert form.attributes["action"] == SUGGEST_ENDPOINT
    assert urlsplit(SUGGEST_ENDPOINT).hostname == "netc-suggest.tim-bertino.workers.dev"


def test_an_endpoint_must_be_https(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "dist"
    args = ["build-site", "--data", str(data(tmp_path)), "--out", str(out), "--web", str(WEB)]
    assert main([*args, "--now", NOW, "--suggest-endpoint", "http://w.example/suggest"]) == 1
    assert "https" in capsys.readouterr().err
