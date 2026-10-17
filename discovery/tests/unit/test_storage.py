"""Deterministic, atomic reading and writing of data/ (T029)."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest

from netc.storage import DataStore, StorageError
from tests.data_samples import (
    make_candidate,
    make_category,
    make_event,
    make_known_group,
    make_mention,
    make_organizer,
    make_override,
    make_review,
    make_source,
    make_status,
    utc,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path: Path) -> DataStore:
    return DataStore(tmp_path / "data")


def all_files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def write_everything(store: DataStore, seed: int = 0) -> None:
    rng = random.Random(seed)  # noqa: S311 - shuffling test input, not security
    events = [
        make_event(),
        make_event(
            slug="lincoln-devops-2026-11-05",
            start=utc(2026, 11, 6, 0, 0),
            url="https://lincolndevops.example.org/events/nov",
        ),
        make_event(
            slug="security-summit-2027-01-15",
            start=utc(2027, 1, 15, 15, 0),
            url="https://securitysummit.example.org/2027",
        ),
    ]
    candidates = [make_candidate(f"https://group{i}.example.org/") for i in range(4)]
    mentions = [make_mention(f"men_{i:012x}") for i in range(3)]
    reviews = [make_review(f"rev_{i:012x}") for i in range(3)]
    groups = [make_known_group(name) for name in ("ISACA Omaha", "AI Omaha", "OWASP Omaha")]
    organizers = [make_organizer(f"org_group-{i}") for i in range(3)]
    for items in (events, candidates, mentions, reviews, groups, organizers):
        rng.shuffle(items)
    store.write_events(events)
    store.write_source(make_source())
    store.write_source(make_source("src_aim-institute", name="AIM Institute", connector="jsonld"))
    store.write_candidates(candidates)
    store.write_mentions(mentions)
    store.write_review_queue(reviews)
    store.write_review_open([r.id for r in reviews])
    store.write_source_status(
        {"src_omaha-python": make_status(), "src_aim-institute": make_status()}
    )
    store.write_known_groups(groups)
    store.write_organizers(organizers)
    store.write_categories([make_category(), make_category("security", "Security")])
    store.write_overrides([make_override(events[0].id)])


# --- Round trips


def test_every_file_type_round_trips(store: DataStore) -> None:
    write_everything(store)
    assert len(store.read_events()) == 3
    assert {s.id for s in store.read_sources()} == {"src_omaha-python", "src_aim-institute"}
    assert len(store.read_candidates()) == 4
    assert len(store.read_mentions()) == 3
    assert len(store.read_review_queue()) == 3
    assert len(store.read_review_open()) == 3
    assert set(store.read_source_status()) == {"src_omaha-python", "src_aim-institute"}
    assert len(store.read_known_groups()) == 3
    assert len(store.read_organizers()) == 3
    assert [c.id for c in store.read_categories()] == ["software-dev", "security"]
    assert len(store.read_overrides()) == 1


def test_read_values_equal_what_was_written(store: DataStore) -> None:
    event = make_event()
    source = make_source(notes="Monthly.\nSecond Tuesday.")
    store.write_events([event])
    store.write_source(source)
    assert store.read_events() == [event]
    assert store.read_sources() == [source]


def test_missing_files_read_as_empty(store: DataStore) -> None:
    assert store.read_events() == []
    assert store.read_sources() == []
    assert store.read_candidates() == []
    assert store.read_source_status() == {}
    assert store.read_review_open() == []
    assert store.read_categories() == []


# --- Determinism


def test_writing_twice_yields_identical_bytes(store: DataStore) -> None:
    write_everything(store)
    first = all_files(store.root)
    write_everything(store)
    assert all_files(store.root) == first


def test_output_does_not_depend_on_input_order(tmp_path: Path) -> None:
    a, b = DataStore(tmp_path / "a"), DataStore(tmp_path / "b")
    write_everything(a, seed=1)
    write_everything(b, seed=2)
    assert all_files(a.root) == all_files(b.root)


def test_files_use_lf_utf8_sorted_keys_and_trailing_newline(store: DataStore) -> None:
    write_everything(store)
    for name, data in all_files(store.root).items():
        assert data.endswith(b"\n"), name
        assert b"\r\n" not in data, name
        data.decode("utf-8")
    month = store.root / "events" / "2026" / "2026-10.json"
    record = json.loads(month.read_text(encoding="utf-8"))[0]
    assert list(record) == sorted(record)


def test_non_ascii_text_is_written_as_utf8_not_escaped(store: DataStore) -> None:
    store.write_events([make_event(title="Café Código")])
    text = (store.root / "events" / "2026" / "2026-10.json").read_text(encoding="utf-8")
    assert "Café Código" in text


def test_lists_are_sorted_stably(store: DataStore) -> None:
    store.write_candidates(
        [make_candidate("https://b.example.org/"), make_candidate("https://a.example.org/")]
    )
    assert [c.url for c in store.read_candidates()] == [
        "https://a.example.org/",
        "https://b.example.org/",
    ]


def test_candidate_notes_are_never_written(store: DataStore) -> None:
    store.write_candidates([make_candidate(note="call me at 402-555-0199, private note")])
    raw = (store.root / "candidates.json").read_text(encoding="utf-8")
    assert "note" not in raw
    assert "private" not in raw


def test_source_dates_stay_dates_through_yaml(store: DataStore) -> None:
    store.write_source(make_source(updated_at="2026-10-18"))
    (source,) = store.read_sources()
    assert source.added_at.isoformat() == "2026-10-17"
    assert source.updated_at is not None and source.updated_at.isoformat() == "2026-10-18"


# --- Event partitioning by Central Time month


def test_events_are_partitioned_by_central_time_start_month(store: DataStore) -> None:
    halloween_night = make_event(
        slug="late-night-2026-10-31",
        start=utc(2026, 11, 1, 3, 0),  # 10 PM Oct 31 in Omaha (CDT)
        url="https://late.example.org/e",
    )
    november = make_event(
        slug="early-2026-11-01",
        start=utc(2026, 11, 1, 6, 0),  # 1 AM Nov 1 in Omaha (CDT)
        url="https://early.example.org/e",
    )
    store.write_events([halloween_night, november])
    oct_ids = [
        e["id"] for e in json.loads((store.root / "events/2026/2026-10.json").read_text("utf-8"))
    ]
    nov_ids = [
        e["id"] for e in json.loads((store.root / "events/2026/2026-11.json").read_text("utf-8"))
    ]
    assert oct_ids == [halloween_night.id]
    assert nov_ids == [november.id]


def test_events_within_a_month_are_ordered_by_start_then_id(store: DataStore) -> None:
    later = make_event(
        slug="b-2026-10-25", start=utc(2026, 10, 25, 23), url="https://b.example.org/e"
    )
    earlier = make_event(
        slug="a-2026-10-05", start=utc(2026, 10, 5, 23), url="https://a.example.org/e"
    )
    store.write_events([later, earlier])
    assert [e.id for e in store.read_events()] == [earlier.id, later.id]


def test_month_files_without_events_are_removed(store: DataStore) -> None:
    store.write_events(
        [
            make_event(),
            make_event(
                slug="x-2027-01-15", start=utc(2027, 1, 15, 15), url="https://x.example.org/e"
            ),
        ]
    )
    assert (store.root / "events/2027/2027-01.json").exists()
    store.write_events([make_event()])
    assert not (store.root / "events/2027/2027-01.json").exists()
    assert not (store.root / "events/2027").exists()
    assert (store.root / "events/2026/2026-10.json").exists()


def test_duplicate_event_ids_are_refused(store: DataStore) -> None:
    with pytest.raises(StorageError, match="duplicate"):
        store.write_events([make_event(), make_event()])


# --- Atomic writes


def test_failed_write_leaves_the_old_file_and_no_temp_files(
    store: DataStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.write_candidates([make_candidate()])
    path = store.root / "candidates.json"
    before = path.read_bytes()

    def broken_replace(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        store.write_candidates([make_candidate("https://new.example.org/")])
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_unchanged_content_is_not_rewritten(store: DataStore) -> None:
    store.write_candidates([make_candidate()])
    path = store.root / "candidates.json"
    os.utime(path, (1_000_000, 1_000_000))
    store.write_candidates([make_candidate()])
    assert path.stat().st_mtime == 1_000_000


# --- Corrupt input


def test_corrupt_file_raises_storage_error_naming_the_file(store: DataStore) -> None:
    store.root.mkdir(parents=True)
    (store.root / "candidates.json").write_text("[{not json", encoding="utf-8")
    with pytest.raises(StorageError, match=r"candidates\.json"):
        store.read_candidates()


def test_invalid_record_raises_storage_error_naming_the_file(store: DataStore) -> None:
    store.root.mkdir(parents=True)
    (store.root / "candidates.json").write_text(
        '[{"url": "http://x.example.org/"}]', encoding="utf-8"
    )
    with pytest.raises(StorageError, match=r"candidates\.json"):
        store.read_candidates()


def test_repo_data_directory_reads_cleanly() -> None:
    repo_data = Path(__file__).resolve().parents[3] / "data"
    store = DataStore(repo_data)
    store.read_events()
    store.read_candidates()
    store.read_source_status()
    store.read_known_groups()
