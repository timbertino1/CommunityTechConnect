"""`netc discover-events --offline` end to end (T053; FR-006, FR-008)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from netc.cli import main
from netc.storage import DataStore
from tests.data_samples import make_event, make_override, make_source, utc

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
        "Nelnet Engineering Tech Talk",
        "Computing Research Showcase",
        "Drupal Nebraska meetup",
    }  # "Fall Semester Break" rejected; the private event skipped
    nelnet = events["Nelnet Engineering Tech Talk"]
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


def test_the_run_report_describes_the_run(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "report.md"
    code, out = discover(data, capsys, "--report", str(path))
    assert code == 0, out
    text = path.read_text(encoding="utf-8")
    assert text.startswith("## Discovery run · ")
    assert "**Sources:** 3 read, 1 failed, 0 skipped." in text
    for name in ("UNL School of Computing", "Drupal Nebraska", "Partner calendar"):
        assert f"| {name} | ✅ ok" in text
    assert "| Broken source | ❌ failed (first failure) |" in text
    assert "### Added to the site" in text
    assert "`Nelnet Engineering Tech Talk`" in text
    assert "from UNL School of Computing, Partner calendar" in text
    assert "dropped: `Fall Semester Break` (`no safe https link" in text


def test_the_report_explains_a_run_where_nothing_was_due(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    discover(data, capsys)
    path = tmp_path / "report.md"
    discover(data, capsys, "--report", str(path))
    text = path.read_text(encoding="utf-8")
    assert "| UNL School of Computing | ⏭️ not due yet |" in text
    assert "0 added to the site, 0 held for review, 0 updated." in text


def test_dry_run_writes_nothing(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = discover(data, capsys, "--dry-run")
    assert code == 0
    assert "dry run" in out
    assert DataStore(data).read_events() == []
    assert DataStore(data).read_source_status() == {}


def test_offline_needs_fixtures(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["discover-events", "--data-dir", str(data), "--offline"]) == 2


def test_an_override_survives_a_re_run(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    discover(data, capsys)
    store = DataStore(data)
    talk = next(e for e in store.read_events() if e.title == "Nelnet Engineering Tech Talk")
    store.write_overrides(
        [make_override(talk.id, categories=["ai-ml"], area="omaha", reason="wrong topic")]
    )
    discover(data, capsys, "--force")
    after = next(e for e in DataStore(data).read_events() if e.id == talk.id)
    assert after.visibility == "hidden"
    assert after.categories == ["ai-ml"]
    assert after.area == "omaha"
    assert "categories" not in after.inferred and "area" not in after.inferred
    assert main(["validate-data", "--data-dir", str(data)]) == 0, capsys.readouterr().err


# --- The monthly link check (T118)


def test_on_the_first_of_the_month_gone_pages_of_past_events_are_flagged(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = DataStore(data)
    gone = make_event(
        url="https://gone.example.org/talk", start=utc(2026, 9, 1, 23),
        source_id="src_drupal-nebraska", first_seen=utc(2026, 8, 1),
    )  # fmt: skip
    store.write_events([gone])
    report = tmp_path / "report.md"
    args = ["--offline", "--fixtures", str(FIXTURES), "--now", "2026-11-01T11:00:00Z"]
    code = main(["discover-events", "--data-dir", str(data), *args, "--report", str(report)])
    out = capsys.readouterr()
    assert code == 0, out.err
    [stored] = [e for e in store.read_events() if e.id == gone.id]
    assert stored.original_unavailable is True
    assert "**Past events' original pages:** 1 page checked; 1 may be gone." in report.read_text(
        encoding="utf-8"
    )
    assert '"event": "link_check_done"' in out.err


def test_other_days_do_not_check_links(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "report.md"
    code, out = discover(data, capsys, "--report", str(report))
    assert code == 0, out
    assert "original pages" not in report.read_text(encoding="utf-8")
    assert "link_check_done" not in out
