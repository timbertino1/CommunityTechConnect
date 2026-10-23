"""Cost on events and the source default (T157; FR-052): free, paid (with a price label when
the source gives one), or unknown, which is never guessed."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.data_samples import make_event, make_source

pytestmark = pytest.mark.unit


def test_cost_is_unknown_unless_set() -> None:
    event = make_event()
    assert event.cost is None and event.price is None


@pytest.mark.parametrize(("cost", "price"), [("free", None), ("paid", None), ("paid", "$25")])
def test_free_paid_and_a_price(cost: str, price: str | None) -> None:
    event = make_event(cost=cost, price=price)
    assert (event.cost, event.price) == (cost, price)


@pytest.mark.parametrize(
    ("cost", "price"),
    [("free", "$25"), (None, "$25"), ("paid", "<b>$25</b>"), ("paid", "x" * 41), ("cheap", None)],
)
def test_a_price_needs_paid_and_is_short_plain_text(cost: str | None, price: str | None) -> None:
    with pytest.raises(ValidationError):
        make_event(cost=cost, price=price)


def test_a_source_may_say_its_events_are_free_and_nothing_else() -> None:
    assert make_source(default_cost="free").default_cost == "free"
    assert make_source().default_cost is None
    with pytest.raises(ValidationError):
        make_source(default_cost="paid")
