"""Interaction-mode helpers for the standalone agent harness."""

from __future__ import annotations

from typing import Any

try:
    from gbqa.protocol.interaction import (  # type: ignore[import-not-found]
        INTERACTION_MODE_TO_BACKEND,
        backend_type_for_interaction_mode,
        interaction_mode_for_backend_type,
        normalize_interaction_mode,
    )
except ModuleNotFoundError:
    INTERACTION_MODE_TO_BACKEND = {
        "terminal": "api",
        "browser": "playwright_mcp",
        "computer": "computer_use",
    }
    _INTERACTION_MODE_ALIASES = {
        "api": "terminal",
        "cli": "terminal",
        "shell": "terminal",
        "code": "terminal",
        "computer_use": "computer",
        "computeruse": "computer",
        "gui": "computer",
    }
    _INTERACTION_MODE_BY_BACKEND = {
        backend_type: mode
        for mode, backend_type in INTERACTION_MODE_TO_BACKEND.items()
    }

    def normalize_interaction_mode(value: Any) -> str:
        text = str(value or "").strip().lower().replace("-", "_")
        if text in {"", "default"}:
            return "default"
        return _INTERACTION_MODE_ALIASES.get(text, text)

    def backend_type_for_interaction_mode(mode: Any) -> str:
        normalized = normalize_interaction_mode(mode)
        if normalized not in INTERACTION_MODE_TO_BACKEND:
            raise ValueError(f"Unsupported interaction mode: {mode}")
        return INTERACTION_MODE_TO_BACKEND[normalized]

    def interaction_mode_for_backend_type(backend_type: Any) -> str:
        text = str(backend_type or "").strip()
        return _INTERACTION_MODE_BY_BACKEND.get(text, text)
