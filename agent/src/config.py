"""Configuration loader for QA Agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config_layers import load_toml_dict


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

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        tasks = self.get_section("tasks")
        if task_id in tasks:
            return tasks.get(task_id)
        task_slug = task_id.rsplit("/", maxsplit=1)[-1]
        return tasks.get(task_slug)

    def resolve_path(self, path: str) -> str:
        """Resolve a possibly-relative path from the config directory."""
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.root_dir, path))


def load_config(path: str) -> Config:
    """Load configuration from TOML file."""
    resolved_path = os.path.abspath(path)
    raw = load_toml_dict(resolved_path)
    root_dir = os.path.dirname(resolved_path)
    return Config(raw=raw, root_dir=root_dir)
