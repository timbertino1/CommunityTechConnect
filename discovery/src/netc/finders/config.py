"""Finder settings from finders/config.yaml (T093)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import yaml

from netc.pipeline.sanitize import safe_url

CONFIG_FILE: Final = Path(__file__).with_name("config.yaml")


@dataclass(frozen=True)
class FinderConfig:
    news_feeds: list[str] = field(default_factory=list)


def load_config(path: Path = CONFIG_FILE) -> FinderConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    feeds = [safe_url(str(u)) for u in raw.get("news_feeds") or []]
    if any(f is None for f in feeds):
        raise ValueError(f"{path}: news_feeds must be safe https URLs")
    return FinderConfig(news_feeds=[f for f in feeds if f is not None])
