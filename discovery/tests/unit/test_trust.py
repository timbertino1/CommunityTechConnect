"""Source trust rules (T092; FR-016-FR-018; data-model.md state transitions)."""

from __future__ import annotations

from typing import Any

import pytest

from netc.models import Source
from netc.pipeline.trust import (
    MIN_REVIEWED_TO_PAUSE,
    PROMOTE_AFTER_APPROVALS,
    apply_trust_rules,
    initial_trust,
)
from tests.data_samples import make_source

pytestmark = pytest.mark.unit


def probationary(approved: int, rejected: int, **overrides: Any) -> Source:
    return make_source(
        trust="probationary",
        origin="discovered",
        found_via="web_search",
        approved_count=approved,
        rejected_count=rejected,
        **overrides,
    )


@pytest.mark.parametrize(
    ("origin", "trust"),
    [
        ("preconfigured", "trusted"),
        ("admin", "trusted"),
        ("discovered", "probationary"),
        ("suggested", "probationary"),
    ],
)
def test_initial_trust_follows_where_a_source_came_from(origin: str, trust: str) -> None:
    assert initial_trust(origin) == trust  # type: ignore[arg-type]


def test_three_approvals_and_no_rejections_promote() -> None:
    assert PROMOTE_AFTER_APPROVALS == 3
    assert apply_trust_rules(probationary(3, 0)).trust == "trusted"
    assert apply_trust_rules(probationary(2, 0)).trust == "probationary"


def test_any_rejection_keeps_a_source_probationary() -> None:
    source = apply_trust_rules(probationary(5, 1))
    assert source.trust == "probationary" and source.status == "active"


def test_a_mostly_rejected_source_is_paused_once_three_are_reviewed() -> None:
    assert MIN_REVIEWED_TO_PAUSE == 3
    assert apply_trust_rules(probationary(1, 2)).status == "paused"
    assert apply_trust_rules(probationary(0, 3)).status == "paused"


def test_one_or_two_rejections_alone_do_not_pause() -> None:
    # A new source isn't paused for its first rejected event or two.
    assert apply_trust_rules(probationary(0, 1)).status == "active"
    assert apply_trust_rules(probationary(0, 2)).status == "active"


def test_an_even_split_is_not_a_majority() -> None:
    assert apply_trust_rules(probationary(2, 2)).status == "active"


def test_trusted_sources_are_never_changed_by_review_counts() -> None:
    source = make_source(trust="trusted", approved_count=0, rejected_count=9)
    assert apply_trust_rules(source) == source


def test_an_already_paused_source_stays_paused() -> None:
    source = probationary(0, 4, status="paused")
    assert apply_trust_rules(source) == source
