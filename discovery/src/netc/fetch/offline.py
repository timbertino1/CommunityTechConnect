"""HttpClient: what connectors need from a fetcher, and FixtureHttp, an offline one.

``SafeHttp`` is the real implementation. ``FixtureHttp`` answers from files listed in an
``index.json`` (``{"<url>": {"file": "...", "content_type": "...", "status": 200}}``) so that
``netc discover-events --offline --fixtures DIR`` and the integration tests run without a network.
A URL that is not listed fails like an unreachable site.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from netc.fetch.errors import ContentTypeNotAllowedError, FetchError
from netc.fetch.safe_fetch import (
    DEFAULT_CONTENT_TYPES,
    FetchKind,
    FetchResponse,
    _parse_content_type,
)


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        kind: FetchKind = "page",
        allowed_types: Collection[str] | None = None,
        delay_seconds: float | None = None,
    ) -> FetchResponse: ...


class FixtureHttp:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        index: dict[str, Any] = json.loads((directory / "index.json").read_text(encoding="utf-8"))
        self._index = index
        self.requested: list[str] = []

    def get(
        self,
        url: str,
        *,
        kind: FetchKind = "page",
        allowed_types: Collection[str] | None = None,
        delay_seconds: float | None = None,
    ) -> FetchResponse:
        self.requested.append(url)
        entry = self._index.get(url)
        if entry is None:
            raise FetchError(f"{url} could not be fetched: no offline fixture")
        status = int(entry.get("status", 200))
        content_type, charset = _parse_content_type(entry.get("content_type"))
        types = (
            frozenset(t.lower() for t in allowed_types)
            if allowed_types is not None
            else DEFAULT_CONTENT_TYPES[kind]
        )
        if 200 <= status < 300 and content_type not in types:
            raise ContentTypeNotAllowedError(f"{url} returned content type {content_type!r}")
        file = entry.get("file")
        content = (self._dir / file).read_bytes() if file else b""
        return FetchResponse(
            url=url,
            status=status,
            content_type=content_type,
            charset=charset,
            headers=MappingProxyType({"content-type": entry.get("content_type", "")}),
            content=content,
        )
