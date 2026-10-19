"""Markdown that is safe to post on the public repository (PR descriptions, job summaries).

Text from other sites goes inside a code span: GitHub doesn't turn code into @mentions, issue
links, autolinks, images or HTML there, and the text can't contain a backtick, so it can't
close the span early or fake one of our own markers (like a ``rev_`` id). Names we keep in
data/ are shown as plain text with Markdown escaped and mentions and links broken.
"""

from __future__ import annotations

import re
from typing import Final

MAX_TEXT: Final = 140
_SPACE: Final = re.compile(r"\s+")
_MARKDOWN: Final = re.compile(r"([\\`*_{}\[\]<>()#+!|~])")
# GitHub finds @mentions, #123 links and bare URLs after rendering, so escaping doesn't stop
# them; an invisible word joiner after the trigger character does.
_JOIN: Final = "\N{WORD JOINER}"
_TRIGGERS: Final = re.compile(r"([@#]|:(?=//))")


def one_line(text: str, limit: int = MAX_TEXT) -> str:
    text = _SPACE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def code_span(text: str) -> str:
    """Untrusted text as an inline code span. Backticks can't be escaped inside one, so they
    become apostrophes; pipes would still split a table cell, so they become slashes."""
    body = one_line(text).replace("`", "'").replace("|", "/")
    return f"`{body}`" if body else "`-`"


def plain_name(text: str) -> str:
    """A name from data/ as plain text: Markdown escaped, mentions and links broken."""
    escaped = _MARKDOWN.sub(r"\\\1", one_line(text))
    return _TRIGGERS.sub(lambda m: m.group(1) + _JOIN, escaped) or "-"
