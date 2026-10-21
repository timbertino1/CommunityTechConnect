"""The link-graph finder: one hop from known organizers' and groups' pages (T087; research R6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from netc.fetch import FixtureHttp
from netc.finders.base import FinderContext
from netc.finders.link_graph import MAX_PAGES, LinkGraphFinder, pages_to_visit
from netc.models import AreaConfig, KnownGroup, Organizer
from netc.storage import DataStore
from tests.ai_support import NOW
from tests.data_samples import make_source

pytestmark = pytest.mark.unit

REPO = DataStore(Path(__file__).resolve().parents[3] / "data")
AREAS: AreaConfig = REPO.read_areas()  # type: ignore[assignment]
PAGES = Path(__file__).resolve().parents[1] / "fixtures" / "finders" / "pages"
ORG_URL = "https://spbuilders.example.org/"


def http(tmp_path: Path, pages: dict[str, str]) -> FixtureHttp:
    index = {
        url: {"file": str(PAGES / name), "content_type": "text/html"} for url, name in pages.items()
    }
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return FixtureHttp(tmp_path)


def org(url: str = ORG_URL) -> Organizer:
    return Organizer(id="org_spb", name="Silicon Prairie Builders", url=url)


def test_group_event_and_calendar_links_become_candidates(tmp_path: Path) -> None:
    ctx = FinderContext(
        now=NOW,
        areas=AREAS,
        http=http(tmp_path, {ORG_URL: "org_with_cohost.html"}),
        organizers=[org()],
    )
    result = LinkGraphFinder().run(ctx)
    assert sorted(c.url for c in result.candidates) == [
        "https://heartlandrust.example.org/",
        "https://lincolnsec.example.org/events",
        "https://www.meetup.com/omaha-data-engineers/",
    ]
    rust = next(c for c in result.candidates if "heartlandrust" in c.url)
    assert rust.found_via == "link_graph"
    assert rust.evidence == [f"linked from {ORG_URL}", "link text: Heartland Rust Users"]
    assert result.stats["pages"] == 1


def test_sponsors_social_links_and_same_site_pages_are_left_out(tmp_path: Path) -> None:
    ctx = FinderContext(
        now=NOW,
        areas=AREAS,
        http=http(tmp_path, {ORG_URL: "org_with_cohost.html"}),
        organizers=[org()],
    )
    urls = {c.url for c in LinkGraphFinder().run(ctx).candidates}
    assert not any("acme-hosting" in u or "twitter" in u or "privacy" in u for u in urls)


def test_known_sites_are_not_found_again(tmp_path: Path) -> None:
    known = make_source("src_rust", url="https://heartlandrust.example.org/events/")
    ctx = FinderContext(
        now=NOW,
        areas=AREAS,
        http=http(tmp_path, {ORG_URL: "org_with_cohost.html"}),
        organizers=[org()],
        sources=[known],
    )
    urls = {c.url for c in LinkGraphFinder().run(ctx).candidates}
    assert "https://heartlandrust.example.org/" not in urls


def test_pages_come_from_organizers_known_groups_and_sources_but_not_platforms() -> None:
    ctx = FinderContext(
        now=NOW,
        areas=AREAS,
        organizers=[org()],
        known_groups=[KnownGroup(name="ISACA Omaha", links=["https://isaca-omaha.example.org/"])],
        sources=[
            make_source("src_a", url="https://group.example.org/events"),
            make_source("src_m", url="https://www.meetup.com/prairie-python/events/"),
        ],
    )
    assert pages_to_visit(ctx) == [
        ORG_URL,
        "https://isaca-omaha.example.org/",
        "https://group.example.org/events",
    ]


def test_at_most_max_pages_a_run_rotating_weekly() -> None:
    groups = [KnownGroup(name=f"G{i}", links=[f"https://g{i}.example.org/"]) for i in range(50)]
    ctx = FinderContext(now=NOW, areas=AREAS, known_groups=groups)
    first = pages_to_visit(ctx)
    later = pages_to_visit(FinderContext(now=NOW.replace(day=27), areas=AREAS, known_groups=groups))
    assert len(first) == MAX_PAGES == 20
    assert first != later


def test_unreadable_pages_are_counted_and_skipped(tmp_path: Path) -> None:
    ctx = FinderContext(now=NOW, areas=AREAS, http=http(tmp_path, {}), organizers=[org()])
    result = LinkGraphFinder().run(ctx)
    assert result.candidates == [] and result.stats["errors"] == 1
