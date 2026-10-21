"""AI cache and budget: results cached by content hash in data/cache/ai/<YYYY-MM>.jsonl, inputs
truncated, tokens counted, and the monthly budget enforced (T080; research R10, gate V6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from netc.models import AreaConfig, Category
from netc.pipeline.ai import (
    MAX_EMAIL_CHARS,
    MAX_EVENT_CHARS,
    MONTHLY_BUDGET_USD,
    PRICES,
    AiCache,
    AiReply,
    cost_usd,
)
from netc.pipeline.classify import classify
from netc.pipeline.extract import extract_mentions
from netc.storage import DataStore
from tests.ai_support import NOW, ScriptedClient, ai, unclear, verdict

pytestmark = pytest.mark.unit

REPO = DataStore(Path(__file__).resolve().parents[3] / "data")
CATEGORIES: list[Category] = REPO.read_categories()
AREAS: AreaConfig = REPO.read_areas()  # type: ignore[assignment]


def run(tmp_path: Path, client: ScriptedClient, item: object = None, **kw: object) -> object:
    service = ai(tmp_path, client, **kw)  # type: ignore[arg-type]
    result = classify(item or unclear(), CATEGORIES, AREAS, ai=service)  # type: ignore[arg-type]
    service.cache.save()
    return result


def lines(tmp_path: Path, month: str = "2026-10") -> list[dict[str, object]]:
    path = tmp_path / "cache" / "ai" / f"{month}.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_an_answer_is_cached_by_content_and_not_sent_again(tmp_path: Path) -> None:
    client = ScriptedClient(verdict(), verdict())
    run(tmp_path, client)
    run(tmp_path, client)
    assert len(client.calls) == 1
    [entry] = lines(tmp_path)
    assert len(str(entry["key"])) == 64 and entry["kind"] == "classify"
    assert entry["result"] == verdict()


def test_the_cache_holds_answers_not_source_text(tmp_path: Path) -> None:
    run(tmp_path, ScriptedClient(verdict()), unclear("Secret sauce night", "Bring snacks."))
    text = (tmp_path / "cache" / "ai" / "2026-10.jsonl").read_text(encoding="utf-8")
    assert "Secret sauce" not in text and "snacks" not in text


def test_changed_text_is_asked_again(tmp_path: Path) -> None:
    client = ScriptedClient(verdict(), verdict())
    run(tmp_path, client, unclear("Night A"))
    run(tmp_path, client, unclear("Night B"))
    assert len(client.calls) == 2


def test_last_months_answers_are_still_used(tmp_path: Path) -> None:
    september = datetime(2026, 9, 28, tzinfo=UTC)
    run(tmp_path, ScriptedClient(verdict()), now=september)
    client = ScriptedClient(verdict())
    run(tmp_path, client)
    assert client.calls == []
    assert not (tmp_path / "cache" / "ai" / "2026-10.jsonl").exists()


def test_event_text_is_truncated(tmp_path: Path) -> None:
    client = ScriptedClient(verdict())
    run(tmp_path, client, unclear("Long one", "word " * 5_000))
    assert len(client.calls[0]["data"]) <= MAX_EVENT_CHARS


def test_email_text_is_truncated(tmp_path: Path) -> None:
    client = ScriptedClient({"mentions": []})
    extract_mentions("line\n" * 10_000, [], ai=ai(tmp_path, client), channel="newsletter")
    assert len(client.calls[0]["data"]) <= MAX_EMAIL_CHARS


def test_cost_comes_from_tokens_and_gate_v6_prices() -> None:
    # gpt-5-nano: $0.05 input, $0.005 cached input, $0.40 output per million tokens.
    assert PRICES.input == 0.05 and PRICES.cached_input == 0.005 and PRICES.output == 0.40
    assert cost_usd(AiReply(None, 1_000_000, 0, 0)) == pytest.approx(0.05)
    assert cost_usd(AiReply(None, 1_000_000, 1_000_000, 0)) == pytest.approx(0.005)
    assert cost_usd(AiReply(None, 0, 0, 1_000_000)) == pytest.approx(0.40)


def test_spend_adds_up_and_the_budget_stops_calls(tmp_path: Path) -> None:
    # Each call: 1M input + 1M output tokens = $0.45; a $1 budget allows three calls
    # (the third starts at $0.90 spent), then stops.
    client = ScriptedClient(*[verdict()] * 5, tokens=(1_000_000, 1_000_000))
    for n in range(5):
        run(tmp_path, client, unclear(f"Night {n}"))
    assert len(client.calls) == 3
    cache = AiCache(tmp_path / "cache" / "ai", now=NOW)
    assert cache.spent_usd() == pytest.approx(1.35)


def test_failed_and_refused_calls_still_count(tmp_path: Path) -> None:
    client = ScriptedClient(AiReply(None, 2_000_000, 0, 0, refusal="no"), verdict())
    run(tmp_path, client, unclear("A"))
    cache = AiCache(tmp_path / "cache" / "ai", now=NOW)
    assert cache.spent_usd() == pytest.approx(0.10)
    [entry] = lines(tmp_path)
    assert entry["result"] is None


def test_a_refused_answer_is_asked_again_next_time(tmp_path: Path) -> None:
    client = ScriptedClient(AiReply(None, 10, 0, 1, refusal="no"), verdict())
    run(tmp_path, client)
    run(tmp_path, client)
    assert len(client.calls) == 2


def test_only_this_months_spend_counts(tmp_path: Path) -> None:
    run(
        tmp_path,
        ScriptedClient(verdict(), tokens=(10_000_000, 0)),
        now=datetime(2026, 9, 1, tzinfo=UTC),
    )
    client = ScriptedClient(verdict())
    run(tmp_path, client, unclear("New in October"))
    assert len(client.calls) == 1


def test_the_default_budget_is_about_a_dollar() -> None:
    assert MONTHLY_BUDGET_USD == 1.0


def test_no_client_means_no_ai(tmp_path: Path) -> None:
    result = classify(unclear(), CATEGORIES, AREAS, ai=ai(tmp_path, None))
    assert result.decided_by == "none"
