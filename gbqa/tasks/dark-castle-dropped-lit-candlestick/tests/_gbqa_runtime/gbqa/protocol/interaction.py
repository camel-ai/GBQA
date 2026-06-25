"""Stable interaction-mode names and backend mappings."""

from __future__ import annotations

from typing import Any

INTERACTION_MODE_TO_BACKEND = {
    "terminal": "api",
    "browser": "playwright_mcp",
    "computer": "computer_use",
}

INTERACTION_MODE_ALIASES = {
    "api": "terminal",
    "cli": "terminal",
    "shell": "terminal",
    "code": "terminal",
    "computer_use": "computer",
    "computeruse": "computer",
    "gui": "computer",
}

SUPPORTED_INTERACTION_MODES = frozenset(INTERACTION_MODE_TO_BACKEND)
INTERACTION_MODE_BY_BACKEND = {
    backend_type: mode
    for mode, backend_type in INTERACTION_MODE_TO_BACKEND.items()
}


def normalize_interaction_mode(value: Any) -> str:
    """Normalize public interaction mode/profile aliases."""

    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"", "default"}:
        return "default"
    return INTERACTION_MODE_ALIASES.get(text, text)


def backend_type_for_interaction_mode(mode: Any) -> str:
    """Return the execution backend type for a supported interaction mode."""

    normalized = normalize_interaction_mode(mode)
    if normalized not in INTERACTION_MODE_TO_BACKEND:
        raise ValueError(f"Unsupported interaction mode: {mode}")
    return INTERACTION_MODE_TO_BACKEND[normalized]


def interaction_mode_for_backend_type(backend_type: Any) -> str:
    """Return the public interaction mode for a backend type."""

    text = str(backend_type or "").strip()
    return INTERACTION_MODE_BY_BACKEND.get(text, text)
