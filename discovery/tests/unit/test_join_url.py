"""join_url: urljoin for addresses found in other sites' pages, which never raises (Oct 23 run:
one malformed link stopped the whole discover-sources run)."""

from __future__ import annotations

import pytest

from netc.fetch.urls import join_url

pytestmark = pytest.mark.unit


def test_relative_links_are_resolved() -> None:
    assert join_url("https://ex.org/events/", "nov.ics") == "https://ex.org/events/nov.ics"
    assert join_url("https://ex.org/a", "//cdn.ex.org/f") == "https://cdn.ex.org/f"


@pytest.mark.parametrize("href", ["http://[bad", "https://[::1", "//[foo/bar"])
def test_a_malformed_link_becomes_empty_instead_of_raising(href: str) -> None:
    assert join_url("https://ex.org/", href) == ""
