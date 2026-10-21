"""Recorded search results for offline runs and tests (T094; quickstart scenario 2).

An index file maps each query to a recorded Tavily response; "*" answers any other query.
Offline runs never spend real searches.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from netc.pipeline.sanitize import safe_url, to_plain_text
from netc.search.base import SearchResult


class FixtureSearch:
    name: ClassVar[str] = "fixtures"

    def __init__(self, index_file: Path) -> None:
        self._dir = index_file.parent
        self._index: dict[str, str] = json.loads(index_file.read_text(encoding="utf-8"))
        self.queries: list[str] = []

    def search(self, query: str, *, count: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        name = self._index.get(query, self._index.get("*"))
        if name is None:
            return []
        data: Any = json.loads((self._dir / name).read_text(encoding="utf-8"))
        results = []
        for item in data.get("results", [])[:count]:
            url = safe_url(item.get("url"))
            if url is not None:
                results.append(
                    SearchResult(
                        to_plain_text(item.get("title", ""), 300),
                        url,
                        to_plain_text(item.get("content", ""), 600),
                    )
                )
        return results
