"""Neutralize untrusted text and URLs before they are stored (FR-047, FR-048).

Everything collected from sources is stored as plain text: no tags, no entities, no invisible
or control characters. Output encoding (Jinja autoescape) happens later, when the site is built.
"""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Final
from urllib.parse import urlsplit

import nh3

from netc.fetch.errors import UnsafeURLError
from netc.fetch.urls import vet_url

MAX_URL_LENGTH: Final = 2048

# Bound the work done on hostile input. Markup is stripped from at most this many characters;
# after that only a prefix comfortably larger than any field limit is kept.
_MAX_INPUT_CHARS: Final = 2_000_000
_TEXT_WINDOW_FACTOR: Final = 8
_TEXT_WINDOW_EXTRA: Final = 4096
_MAX_CLEAN_PASSES: Final = 4

# Elements whose content is never visible text, or is active content: dropped entirely.
_DROP_CONTENT_TAGS: Final = frozenset(
    {
        "script", "style", "noscript", "template", "iframe", "frame", "frameset", "noframes",
        "object", "embed", "applet", "svg", "math", "head", "title", "textarea", "xmp",
        "noembed", "plaintext",
    }
)  # fmt: skip

# Block-level elements become spaces so "<p>one</p><p>two</p>" reads "one two". nh3 keeps
# only these tags, with every attribute removed, so the bare tags it emits are easy to replace.
_BLOCK_TAGS: Final = frozenset(
    {
        "p", "div", "br", "hr", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4",
        "h5", "h6", "tr", "td", "th", "table", "thead", "tbody", "section", "article",
        "header", "footer", "nav", "aside", "main", "blockquote", "pre", "figure",
        "figcaption", "address", "details", "summary", "option",
    }
)  # fmt: skip
# After nh3, every "<" in text is escaped, so any remaining tag is one of _BLOCK_TAGS.
_BARE_TAG = re.compile(r"</?[a-z0-9]+\s*/?>")
# What an HTML parser treats as the start of a tag, end tag, comment, or bogus comment:
# "<" immediately followed by a letter, "/", "!", or "?". ("< b" and "5 < 6" are text.)
_MARKUP = re.compile(r"<[A-Za-z/!?]")
_WHITESPACE = re.compile(r"\s+")
# Unicode categories removed outright: control, format (zero-width, bidi overrides, BOM,
# soft hyphen), surrogate, private use.
_DROP_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs", "Co"})

_EMAIL = re.compile(
    r"(?:mailto:)?[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
    re.IGNORECASE,
)
# North American numbers: (402) 555-0199, 402-555-0199, 402.555.0199, +1 402 555 0199.
_PHONE_NANP = re.compile(
    r"(?<![\w.+])(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)"
)
# International numbers written with a leading "+": +44 20 7946 0958.
_PHONE_INTL = re.compile(r"(?<![\w.+])\+[2-9]\d{0,2}(?:[\s.-]?\(?\d{1,4}\)?){2,5}(?!\w)")


def contains_markup(text: str) -> bool:
    """True if ``text`` contains anything that could be parsed as an HTML tag or comment."""
    return _MARKUP.search(text) is not None


def to_plain_text(value: str | None, max_len: int) -> str:
    """Convert untrusted HTML or text to safe, normalized plain text of at most ``max_len``.

    Tags are removed (script, style, and similar elements with their content), entities are
    decoded, invisible and control characters are dropped, whitespace is collapsed, and long
    text is cut at a word boundary with an ellipsis.
    """
    if max_len < 1:
        raise ValueError(f"max_len must be at least 1, not {max_len}")
    if not value:
        return ""

    text = _strip_markup(value[:_MAX_INPUT_CHARS])
    text = text[: max_len * _TEXT_WINDOW_FACTOR + _TEXT_WINDOW_EXTRA]
    text = unicodedata.normalize("NFC", text)
    text = _WHITESPACE.sub(" ", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in _DROP_CATEGORIES)
    text = _WHITESPACE.sub(" ", text).strip()
    return _truncate(text, max_len)


def safe_url(url: str | None) -> str | None:
    """Return the normalized URL if it is a safe ``https://`` link, otherwise None.

    Accepts only https on port 443 with a public-looking hostname (no IP literals, localhost,
    or single-label names) and no user info. Purely syntactic: never resolves or fetches.
    """
    if not url:
        return None
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        return None
    if any(ch.isspace() or unicodedata.category(ch) in _DROP_CATEGORIES for ch in url):
        return None
    try:
        vetted = vet_url(url, upgrade_http=False)
    except UnsafeURLError:
        return None
    fragment = urlsplit(url).fragment
    return f"{vetted}#{fragment}" if fragment else vetted


def scrub_pii(text: str) -> str:
    """Remove e-mail addresses and phone numbers, then tidy the remaining spaces."""
    text = _EMAIL.sub("", text)
    text = _PHONE_NANP.sub("", text)
    text = _PHONE_INTL.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def _strip_markup(text: str) -> str:
    # Decoding entities can reveal new markup ("&lt;script&gt;"), so clean until stable.
    for _ in range(_MAX_CLEAN_PASSES):
        cleaned = nh3.clean(
            text,
            tags=set(_BLOCK_TAGS),
            attributes={"*": set()},  # "*" also clears nh3's default generic title/lang
            clean_content_tags=set(_DROP_CONTENT_TAGS),
            strip_comments=True,
            link_rel=None,
        )
        text = html.unescape(_BARE_TAG.sub(" ", cleaned))
        if not contains_markup(text):
            return text
    # Still markup-like after repeated passes: break every remaining tag opener.
    return _MARKUP.sub(lambda m: " " + m.group(0)[1:], text)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 1]
    space = cut.rfind(" ")
    if space > (max_len - 1) // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-\N{EN DASH}\N{EM DASH}") + "\N{HORIZONTAL ELLIPSIS}"
