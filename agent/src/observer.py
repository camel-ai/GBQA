"""Observation parsing utilities."""

from __future__ import annotations

from typing import Any, Dict

from .types import Observation


class ObservationParser:
    """Parse raw API responses into Observation objects."""

    def parse(self, payload: Dict[str, Any]) -> Observation:
        success = bool(payload.get("success", False))
        message = str(payload.get("message", ""))
        state = payload.get("state") or {}
        turn = payload.get("turn")
        game_over = bool(payload.get("game_over", False))
        return Observation(
            success=success,
            message=message,
            state=state,
            raw=payload,
            game_over=game_over,
            turn=turn if isinstance(turn, int) else None,
        )
