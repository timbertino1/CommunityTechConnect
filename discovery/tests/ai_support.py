"""Helpers for AI tests: a scripted client, sample inputs, and an OpenAI mock transport."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from netc.pipeline.ai import Ai, AiCache, AiReply
from netc.pipeline.classify import ClassifyInput

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
CATEGORY_IDS = ["ai-ml", "security", "software-dev", "general-tech"]
EMAILS = Path(__file__).parent / "fixtures" / "finders" / "emails"


class ScriptedClient:
    """Answers each call with the next scripted reply; records what it was sent."""

    model = "test-model"

    def __init__(self, *replies: Any, tokens: tuple[int, int] = (1_000, 100)) -> None:
        self._replies = list(replies)
        self._tokens = tokens
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, system: str, data: str, schema_name: str, schema: dict[str, Any]
    ) -> AiReply:
        self.calls.append(
            {"system": system, "data": data, "schema_name": schema_name, "schema": schema}
        )
        reply = self._replies.pop(0) if self._replies else None
        if isinstance(reply, AiReply):
            return reply
        return AiReply(reply, self._tokens[0], 0, self._tokens[1])


def ai(
    tmp_path: Path, client: ScriptedClient | None, *, budget: float = 1.0, now: datetime = NOW
) -> Ai:
    return Ai(client, AiCache(tmp_path / "cache" / "ai", now=now), now=now, budget_usd=budget)


def unclear(title: str = "Community night", summary: str = "Come hang out.") -> ClassifyInput:
    return ClassifyInput(title=title, summary=summary, organizer=None, area=None, online=False,
                         source_area=None)  # fmt: skip


def verdict(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "relevant": True,
        "nebraska": True,
        "area": "omaha",
        "categories": ["ai-ml"],
        "confidence": 0.9,
        "reason": "AI meetup in Omaha",
    }
    data.update(overrides)
    return data


def email_text(name: str) -> str:
    raw = (EMAILS / name).read_text(encoding="utf-8")
    return raw.split("\n\n", 1)[1]


def chat_completion(content: str | None, *, refusal: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_792_000_000,
        "model": "gpt-5-nano-2025-08-07",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 1_200,
            "completion_tokens": 80,
            "total_tokens": 1_280,
            "prompt_tokens_details": {"cached_tokens": 200},
        },
    }


def openai_transport(
    reply: dict[str, Any], seen: list[dict[str, Any]]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(200, json=reply)

    return handler
