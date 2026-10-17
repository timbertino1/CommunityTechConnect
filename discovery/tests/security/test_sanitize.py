"""Sanitization of untrusted text and URLs (FR-047, FR-048, data-model validation rules)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from netc.pipeline.sanitize import contains_markup, safe_url, scrub_pii, to_plain_text

pytestmark = pytest.mark.security

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sanitize"
MB = 1024 * 1024


# --- to_plain_text: no markup survives


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<script>alert(1)</script>Hello", "Hello"),
        ("<SCRIPT SRC=https://evil.example/x.js></SCRIPT>Hi", "Hi"),
        ("<style>p { color: red }</style>Styled", "Styled"),
        ('<img src="x" onerror="alert(1)">Pic', "Pic"),
        ('<a href="javascript:alert(1)">Click</a>', "Click"),
        ('<svg onload="alert(1)"><script>x</script></svg>Vector', "Vector"),
        ("<iframe src='https://evil.example'></iframe>Framed", "Framed"),
        ("<noscript>tracker</noscript>Visible", "Visible"),
        ("<template><b>t</b></template>Shown", "Shown"),
        ("<!-- <script>alert(1)</script> -->Comment", "Comment"),
        ("<b>Bold</b> and <i>italic</i>", "Bold and italic"),
        ("Unclosed <b>tag", "Unclosed tag"),
        ("<p>one</p><p>two</p>three<br>four", "one two three four"),
        ("<ul><li>a</li><li>b</li></ul>", "a b"),
    ],
)
def test_markup_is_removed(raw: str, expected: str) -> None:
    assert to_plain_text(raw, 200) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pizza &amp; talks", "Pizza & talks"),
        ("Caf&eacute; &#169; &#x2014; done", "Café © — done"),
        ("5 &lt; 6 and 7 &gt; 3", "5 < 6 and 7 > 3"),
        ("a < b > c", "a < b > c"),
        ("R&D and AT&T", "R&D and AT&T"),
    ],
)
def test_entities_are_decoded_to_plain_text(raw: str, expected: str) -> None:
    assert to_plain_text(raw, 200) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "&lt;script&gt;alert(1)&lt;/script&gt;Text",
        "&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;Text",
        "&lt;img src=x onerror=alert(1)&gt;Text",
        "<<script>script>alert(1)<</script>/script>Text",
    ],
)
def test_escaped_or_nested_markup_cannot_become_a_tag(raw: str) -> None:
    result = to_plain_text(raw, 200)
    assert not contains_markup(result)
    assert "Text" in result
    assert "<script" not in result.lower()
    assert "<img" not in result.lower()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("zero\u200bwidth\u200c\u200d\ufeffjoin", "zerowidthjoin"),
        ("bidi\u202eesrever\u202c ok", "bidiesrever ok"),
        ("isolates\u2066x\u2069", "isolatesx"),
        ("soft\u00adhyphen", "softhyphen"),
        ("null\x00byte\x07bell\x1b[31m", "nullbytebell[31m"),
        ("del\x7fchar \x85next", "delchar next"),
        ("tab\tnew\nline\r\nend", "tab new line end"),
        ("nbsp\u00a0and\u2003em\u3000ideo", "nbsp and em ideo"),
        ("   lots    of\n\n\n  space   ", "lots of space"),
        ("line\u2028sep\u2029para", "line sep para"),
    ],
)
def test_invisible_and_control_characters_are_removed_and_whitespace_normalized(
    raw: str, expected: str
) -> None:
    assert to_plain_text(raw, 200) == expected


def test_text_is_unicode_normalized() -> None:
    # "e" + combining acute becomes the single precomposed character.
    assert to_plain_text("Cafe\u0301", 200) == "Café"


def test_none_and_empty_become_empty_string() -> None:
    assert to_plain_text(None, 100) == ""
    assert to_plain_text("", 100) == ""
    assert to_plain_text("<p> </p>\u200b", 100) == ""


# --- to_plain_text: length


def test_short_text_is_not_truncated() -> None:
    assert to_plain_text("x" * 500, 500) == "x" * 500


def test_long_text_is_truncated_at_a_word_boundary_with_ellipsis() -> None:
    text = "Monthly meetup about Python packaging and testing practices"
    result = to_plain_text(text, 30)
    assert len(result) <= 30
    assert result.endswith("…")
    assert result == "Monthly meetup about Python…"


def test_long_word_without_spaces_is_cut_hard() -> None:
    result = to_plain_text("a" * 1000, 50)
    assert result == "a" * 49 + "…"


@pytest.mark.parametrize("max_len", [1, 2, 200, 280, 500])
def test_output_never_exceeds_max_len(max_len: int) -> None:
    text = "word " * 1000
    assert len(to_plain_text(text, max_len)) <= max_len


def test_ten_megabyte_plain_string_is_handled() -> None:
    result = to_plain_text("Tech " * (2 * MB), 500)
    assert 0 < len(result) <= 500
    assert result.startswith("Tech Tech")


def test_ten_megabyte_html_string_is_handled() -> None:
    raw = "<div><script>alert(1)</script><b>Talk</b></div>" * (10 * MB // 48)
    result = to_plain_text(raw, 500)
    assert 0 < len(result) <= 500
    assert not contains_markup(result)
    assert "alert" not in result


@pytest.mark.parametrize(
    "raw",
    [
        "<div" * 300_000,  # unclosed tags: once took minutes (quadratic regex)
        "<p " * 300_000,
        "<" + "a" * 1_000_000,
        "&" * 2_000_000,
        "<b>" * 500_000,
    ],
    ids=["unclosed-div", "unclosed-p-attrs", "endless-tag-name", "ampersands", "open-bold"],
)
def test_pathological_input_is_processed_quickly(raw: str) -> None:
    start = time.perf_counter()
    result = to_plain_text(raw, 500)
    assert time.perf_counter() - start < 5.0
    assert not contains_markup(result)


def test_markup_inside_attribute_values_does_not_leak() -> None:
    assert to_plain_text('<p title="<script>">x</p>', 200) == "x"
    assert to_plain_text("<div data-x='a>b'>y</div>", 200) == "y"


def test_max_len_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_len"):
        to_plain_text("x", 0)


# --- A realistic hostile page


def test_malicious_page_fixture_becomes_harmless_plain_text() -> None:
    raw = (FIXTURES / "malicious_event.html").read_text(encoding="utf-8")
    result = to_plain_text(raw, 500)
    assert not contains_markup(result)
    for forbidden in ("alert", "javascript:", "document.cookie", "Should not appear", "\u200b"):
        assert forbidden not in result
    assert result.startswith("Omaha Python Meetup Join us for lightning talks & pizza! Register")
    assert "Doors at 6pm." in result
    assert all(ch.isprintable() for ch in result)


# --- contains_markup


@pytest.mark.parametrize("text", ["<b>", "</p>", "<!-- x -->", "<!doctype html>", "<?xml", "x<img"])
def test_contains_markup_detects_tags(text: str) -> None:
    assert contains_markup(text)


@pytest.mark.parametrize(
    "text", ["5 < 6", "a<3", "x <= y", "C++ & C#", "-> arrow <-", "< script>", "<>", ""]
)
def test_contains_markup_ignores_plain_comparisons(text: str) -> None:
    assert not contains_markup(text)


# --- safe_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.meetup.com/omaha-python/", "https://www.meetup.com/omaha-python/"),
        ("HTTPS://Example.COM/Events?id=7", "https://example.com/Events?id=7"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:443/x", "https://example.com/x"),
        ("  https://example.com/x  ", "https://example.com/x"),
        ("https://example.com/e#2026-10-20", "https://example.com/e#2026-10-20"),
        ("https://bücher.example/", "https://xn--bcher-kva.example/"),
    ],
)
def test_safe_url_accepts_and_normalizes_https_urls(url: str, expected: str) -> None:
    assert safe_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        " javascript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "http://example.com/",
        "ftp://example.com/",
        "mailto:someone@example.com",
        "//example.com/",
        "/relative/path",
        "https://user@example.com/",
        "https://user:pass@example.com/",
        "https://192.168.0.1/",
        "https://8.8.8.8/",
        "https://[::1]/",
        "https://2130706433/",
        "https://example.com:8443/",
        "https://localhost/",
        "https://intranet/",
        "https://exa mple.com/",
        "https://example.com/a b",
        "https://example.com/\x00",
        "https://example.com/" + "a" * 2100,
        "",
        "   ",
    ],
)
def test_safe_url_rejects_unsafe_urls(url: str) -> None:
    assert safe_url(url) is None


def test_safe_url_accepts_none() -> None:
    assert safe_url(None) is None


# --- scrub_pii


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Email jane.doe+events@example.com for info", "Email for info"),
        ("Contact: <a@b.co>", "Contact: <>"),
        ("Write mailto:organizer@group.org today", "Write today"),
        ("Call (402) 555-0199 now", "Call now"),
        ("Call 402-555-0199.", "Call ."),
        ("Call 402.555.0199", "Call"),
        ("Call +1 402 555 0199", "Call"),
        ("Call 1-800-555-0199 toll free", "Call toll free"),
        ("Text 4025550199 please", "Text please"),
        ("Intl +44 20 7946 0958 ok", "Intl ok"),
    ],
)
def test_scrub_pii_removes_emails_and_phone_numbers(text: str, expected: str) -> None:
    assert scrub_pii(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Meetup on 2026-10-20 at 6:30 PM",
        "Room 1200, Omaha NE 68102",
        "Python 3.13 and Node 24",
        "Version 10.2.0 released",
        "Capacity 150 people, $25 ticket",
        "Founded in 2019",
        "Visit https://example.com/events/12345678",
    ],
)
def test_scrub_pii_keeps_ordinary_numbers(text: str) -> None:
    assert scrub_pii(text) == text
