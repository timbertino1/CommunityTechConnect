"""Tavily web search (T085; gate V4 decision, 2026-10-17).

A basic search costs one credit; raw page content is not requested. The key is sent only in the
Authorization header (never in the body, a URL or an error message) and comes from the
SEARCH_API_KEY secret in the `discovery` environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, ClassVar, Final

from netc.fetch import FetchError
from netc.fetch.api import ApiClient
from netc.pipeline.sanitize import safe_url, to_plain_text
from netc.search.base import SearchError, SearchResult

TAVILY_URL: Final = "https://api.tavily.com/search"
MAX_RESULTS: Final = 20


class TavilyProvider:
    name: ClassVar[str] = "tavily"

    def __init__(self, api_key: str, api: ApiClient) -> None:
        self._key = api_key
        self._api = api

    @classmethod
    def from_env(cls, api: ApiClient, env: Mapping[str, str] = os.environ) -> TavilyProvider:
        key = env.get("SEARCH_API_KEY", "").strip()
        if not key:
            raise SearchError("SEARCH_API_KEY is not set")
        return cls(key, api)

    def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
        payload = {
            "query": query,
            "max_results": max(1, min(count, MAX_RESULTS)),
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        try:
            response = self._api.post_json(
                TAVILY_URL, payload, headers={"Authorization": f"Bearer {self._key}"}
            )
        except FetchError as exc:
            raise SearchError(f"Tavily search failed: {exc}") from None
        if response.status >= 400:
            raise SearchError(f"Tavily returned HTTP {response.status}")
        if not isinstance(response.data, dict) or not isinstance(
            response.data.get("results"), list
        ):
            raise SearchError("Tavily returned an unexpected response")
        return [r for r in (_result(item) for item in response.data["results"]) if r is not None]


def _result(item: Any) -> SearchResult | None:
    if not isinstance(item, dict):
        return None
    url = safe_url(item.get("url") if isinstance(item.get("url"), str) else None)
    if url is None:
        return None
    title = item.get("title") if isinstance(item.get("title"), str) else ""
    snippet = item.get("content") if isinstance(item.get("content"), str) else ""
    return SearchResult(to_plain_text(title, 300), url, to_plain_text(snippet, 600))
