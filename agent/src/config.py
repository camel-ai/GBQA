"""Configuration loader for QA Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import os

import yaml


@dataclass
class Config:
    """Strongly-typed config wrapper."""

    raw: Dict[str, Any]
    root_dir: str

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def get_section(self, key: str) -> Dict[str, Any]:
        section = self.raw.get(key, {})
        if not isinstance(section, dict):
            return {}
        return section

    def get_game(self, game_id: str) -> Optional[Dict[str, Any]]:
        games = self.get_section("games")
        return games.get(game_id)

    def resolve_path(self, path: str) -> str:
        """Resolve a possibly-relative path from the config directory."""
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.root_dir, path))


def load_config(path: str) -> Config:
    """Load configuration from YAML file."""
    resolved_path = os.path.abspath(path)
    with open(resolved_path, "r", encoding="utf-8") as file_handle:
        raw = yaml.safe_load(file_handle) or {}
    root_dir = os.path.dirname(resolved_path)
    return Config(raw=raw, root_dir=root_dir)
