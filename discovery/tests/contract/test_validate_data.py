"""Contract for `netc validate-data` (T031): the CI gate on every change to data/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from netc.cli import main
from netc.storage import DataStore
from tests.data_samples import make_category, make_event, make_override, make_review, make_source

pytestmark = pytest.mark.contract

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
MONTH = Path("events/2026/2026-10.json")


def run(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["validate-data", "--data-dir", str(data_dir)])
    out = capsys.readouterr()
    return code, out.out + out.err


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """A small valid data directory: one trusted source, one published event."""
    store = DataStore(tmp_path / "data")
    store.write_source(make_source())
    store.write_events([make_event()])
    store.write_categories([make_category()])
    return store.root


def edit_first_event(root: Path, **changes: Any) -> None:
    path = root / MONTH
    events = json.loads(path.read_text(encoding="utf-8"))
    events[0].update(changes)
    path.write_text(json.dumps(events), encoding="utf-8")


# --- Passing data


def test_valid_data_passes(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(data, capsys)
    assert code == 0, out
    assert "OK" in out


def test_the_repositorys_data_directory_passes(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(REPO_DATA, capsys)
    assert code == 0, out


def test_empty_directory_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(tmp_path, capsys)
    assert code == 0, out


def test_missing_directory_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(tmp_path / "nope", capsys)
    assert code == 1
    assert "not found" in out


# --- Schema violations


def test_missing_required_field_fails(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = data / MONTH
    events = json.loads(path.read_text(encoding="utf-8"))
    del events[0]["title"]
    path.write_text(json.dumps(events), encoding="utf-8")
    code, out = run(data, capsys)
    assert code == 1
    assert "2026-10.json" in out
    assert "title" in out


def test_unknown_field_fails(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    edit_first_event(data, rsvp_count=3)
    code, out = run(data, capsys)
    assert code == 1
    assert "rsvp_count" in out


def test_bad_enum_in_source_yaml_fails(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = data / "sources" / "src_omaha-python.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("trust: trusted", "trust: verified"),
        encoding="utf-8",
    )
    code, out = run(data, capsys)
    assert code == 1
    assert "src_omaha-python.yaml" in out
    assert "trust" in out


def test_malformed_json_is_reported_not_raised(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (data / "candidates.json").write_text("[{oops", encoding="utf-8")
    code, out = run(data, capsys)
    assert code == 1
    assert "candidates.json" in out
    assert "Traceback" not in out


def test_wrong_container_type_fails(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (data / "mentions.json").write_text("{}", encoding="utf-8")
    code, out = run(data, capsys)
    assert code == 1
    assert "mentions.json" in out


# --- Non-HTTPS URLs


@pytest.mark.parametrize(
    "url",
    ["http://www.meetup.com/omaha-python/events/123/", "javascript:alert(1)", "https://10.0.0.1/e"],
)
def test_non_https_original_url_fails(
    url: str, data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edit_first_event(data, original_url=url)
    code, out = run(data, capsys)
    assert code == 1
    assert "original_url" in out


def test_non_https_source_feed_url_fails(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = data / "sources" / "src_omaha-python.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "feed_url: http://example.com/feed.ics\n",
        encoding="utf-8",
    )
    code, out = run(data, capsys)
    assert code == 1
    assert "feed_url" in out


# --- HTML in text fields


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "<b>Bold</b> meetup"),
        ("summary", "Hi <img src=x onerror=alert(1)>"),
        ("title", "<!-- c -->x"),
    ],
)
def test_html_in_text_fields_fails(
    field: str, value: str, data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edit_first_event(data, **{field: value})
    code, out = run(data, capsys)
    assert code == 1
    assert field in out
    assert "plain text" in out


def test_html_in_nested_location_fails(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    edit_first_event(data, location={"venue": "<script>x</script>", "online": False})
    code, out = run(data, capsys)
    assert code == 1
    assert "venue" in out


# --- Probationary sources


def probationary_setup(root: Path) -> DataStore:
    store = DataStore(root)
    store.write_source(
        make_source(trust="probationary", origin="discovered", found_via="web_search")
    )
    return store


def test_published_event_from_only_probationary_sources_fails(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    probationary_setup(data)
    code, out = run(data, capsys)
    assert code == 1
    assert "probationary" in out


def test_approved_review_item_allows_publication(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = probationary_setup(data)
    event_id = store.read_events()[0].id
    store.write_review_queue([make_review(ref=event_id, decision="approved", decided_in_pr=12)])
    code, out = run(data, capsys)
    assert code == 0, out


@pytest.mark.parametrize("decision", ["pending", "rejected"])
def test_unapproved_review_item_does_not_allow_publication(
    decision: str, data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = probationary_setup(data)
    event_id = store.read_events()[0].id
    store.write_review_queue([make_review(ref=event_id, decision=decision)])
    code, _ = run(data, capsys)
    assert code == 1


def test_pending_review_event_from_probationary_source_passes(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    probationary_setup(data)
    edit_first_event(data, review_state="pending_review")
    code, out = run(data, capsys)
    assert code == 0, out


def test_one_trusted_listing_is_enough(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = probationary_setup(data)
    store.write_source(make_source("src_aim-institute", name="AIM Institute"))
    event = store.read_events()[0]
    second = event.listings[0].model_copy(update={"source_id": "src_aim-institute"})
    store.write_events([event.model_copy(update={"listings": [event.listings[0], second]})])
    code, out = run(data, capsys)
    assert code == 0, out


# --- Cross-file consistency


def test_listing_from_unknown_source_fails(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (data / "sources" / "src_omaha-python.yaml").unlink()
    code, out = run(data, capsys)
    assert code == 1
    assert "src_omaha-python" in out


def test_source_file_name_must_match_its_id(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = data / "sources" / "src_omaha-python.yaml"
    src.rename(data / "sources" / "src_other-name.yaml")
    code, out = run(data, capsys)
    assert code == 1
    assert "src_other-name.yaml" in out


def test_event_in_the_wrong_month_file_fails(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (data / MONTH).rename(data / "events/2026/2026-09.json")
    code, out = run(data, capsys)
    assert code == 1
    assert "2026-09.json" in out


def test_duplicate_ids_and_slugs_fail(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = data / MONTH
    events = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(events + events), encoding="utf-8")
    code, out = run(data, capsys)
    assert code == 1
    assert "duplicate" in out


def test_unknown_category_fails_when_categories_are_defined(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edit_first_event(data, categories=["quantum-basket-weaving"])
    code, out = run(data, capsys)
    assert code == 1
    assert "quantum-basket-weaving" in out


def test_override_for_unknown_event_fails(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    DataStore(data).write_overrides([make_override("evt_ffffffffffff")])
    code, out = run(data, capsys)
    assert code == 1
    assert "evt_ffffffffffff" in out


def test_open_review_ids_must_exist_in_the_queue(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    DataStore(data).write_review_open(["rev_aaaaaaaaaaaa"])
    code, out = run(data, capsys)
    assert code == 1
    assert "rev_aaaaaaaaaaaa" in out


def test_all_problems_are_reported_in_one_run(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edit_first_event(data, title="<b>x</b>", original_url="http://example.com/")
    (data / "mentions.json").write_text("{}", encoding="utf-8")
    code, out = run(data, capsys)
    assert code == 1
    for expected in ("title", "original_url", "mentions.json"):
        assert expected in out


def test_huge_values_do_not_flood_the_report(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edit_first_event(data, title="<b>" + "x" * 100_000)
    code, out = run(data, capsys)
    assert code == 1
    assert len(out) < 5_000


# --- Other subcommands are registered


@pytest.mark.parametrize(
    "command", ["discover-events", "discover-sources", "apply-review", "build-site"]
)
def test_planned_subcommands_exist_but_are_not_implemented_yet(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([command]) == 2
    assert "not implemented" in capsys.readouterr().err
