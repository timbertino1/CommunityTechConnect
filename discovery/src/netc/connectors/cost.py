"""What an event costs, from what its source says (FR-052). Never guessed: no data, no cost."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from netc.models import Cost


def amount(value: Any) -> Decimal | None:
    """A non-negative amount from a number or a string like "25" or "7.50"; None otherwise."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def from_amounts(amounts: Iterable[Decimal], *, dollars: bool) -> tuple[Cost, str | None] | None:
    """Free when every amount is zero, else paid; a label only for US dollars."""
    found = sorted(amounts)
    if not found:
        return None
    if found[-1] == 0:
        return "free", None
    return "paid", label(found[0], found[-1]) if dollars else None


def label(low: Decimal, high: Decimal) -> str:
    """A label like "$25", "$10-$25" (with an en dash), or "Free-$15"."""
    if low == high:
        return _dollars(low)
    first = "Free" if low == 0 else _dollars(low)
    return f"{first}\N{EN DASH}{_dollars(high)}"


def _dollars(value: Decimal) -> str:
    return f"${value:.0f}" if value == value.to_integral_value() else f"${value:.2f}"
