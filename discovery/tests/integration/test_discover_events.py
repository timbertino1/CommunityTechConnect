"""`netc discover-events --offline` end to end (T053; FR-006, FR-008)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from netc.cli import main
from netc.storage import DataStore
from tests.data_samples import make_source

pytestmark = pytest.mark.integration

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "integration"
NOW = "2026-10-18T12:00:00Z"


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    for name in ("categories.yaml", "areas.yaml"):
        shutil.copy(REPO_DATA / name, root / name)
    store = DataStore(root)
    store.write_source(
        make_source(
            "src_unl-computing",
            name="UNL School of Computing",
            url="https://events.example.edu/cse/upcoming/",
            feed_url="https://events.example.edu/cse/upcoming/?format=ics",
            connector="ical",
            default_area="lincoln",
        )
    )
    store.write_source(
        make_source(
            "src_drupal-nebraska",
            name="Drupal Nebraska",
            url="https://drupal.example.org/ical/1",
            connector="ical",
            default_area="omaha",
        )
    )
    store.write_source(
        make_source(
            "src_partner",
            name="Partner calendar",
            url="https://partner.example.org/events",
            connector="jsonld",
            default_area="lincoln",
        )
    )
    store.write_source(
        make_source(
            "src_broken",
            name="Broken source",
            url="https://broken.example.org/feed.ics",
            connector="ical",
        )
    )
    return root


def discover(data: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, str]:
    code = main(
        [
            "discover-events",
            "--data-dir",
            str(data),
            "--offline",
            "--fixtures",
            str(FIXTURES),
            "--now",
            NOW,
            *extra,
        ]
    )
    out = capsys.readouterr()
    return code, out.out + out.err


def test_a_run_writes_valid_data(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = discover(data, capsys)
    assert code == 0, out
    assert main(["validate-data", "--data-dir", str(data)]) == 0, capsys.readouterr().err


def test_events_are_kept_rejected_and_merged(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    discover(data, capsys)
    events = {e.title: e for e in DataStore(data).read_events()}
    assert set(events) == {
        "Industry in Residence: Nelnet",
        "School of Computing Showcase",
        "Drupal Nebraska meetup",
    }  # "Fall Semester Break" rejected; the private event skipped
    nelnet = events["Industry in Residence: Nelnet"]
    assert {x.source_id for x in nelnet.listings} == {"src_unl-computing", "src_partner"}
    assert nelnet.review_state == "published"
    assert nelnet.area == "lincoln"
    assert events["Drupal Nebraska meetup"].area == "online"


def test_the_broken_source_is_recorded_and_the_run_succeeds(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = discover(data, capsys)
    assert code == 0
    statuses = DataStore(data).read_source_status()
    broken = statuses["src_broken"]
    assert broken.consecutive_failures == 1
    assert broken.last_error is not None and "no offline fixture" in broken.last_error
    assert statuses["src_unl-computing"].consecutive_failures == 0
    assert statuses["src_unl-computing"].events_found_last_run == 3
    assert '"event": "source_failed"' in out


def test_a_second_run_at_the_same_time_changes_nothing(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    discover(data, capsys)
    before = {p: p.read_bytes() for p in sorted(data.rglob("*")) if p.is_file()}
    discover(data, capsys)
    after = {p: p.read_bytes() for p in sorted(data.rglob("*")) if p.is_file()}
    assert after == before


def test_dry_run_writes_nothing(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = discover(data, capsys, "--dry-run")
    assert code == 0
    assert "dry run" in out
    assert DataStore(data).read_events() == []
    assert DataStore(data).read_source_status() == {}


def test_offline_needs_fixtures(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["discover-events", "--data-dir", str(data), "--offline"]) == 2
