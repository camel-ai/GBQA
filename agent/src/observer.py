"""Observation parsing utilities."""

from __future__ import annotations

from typing import Any, Dict, List

from .types import Observation


class ObservationParser:
    """Parse raw API responses into Observation objects."""

    def parse(self, payload: Dict[str, Any]) -> Observation:
        success = bool(payload.get("success", False))
        message = str(payload.get("message", ""))
        state = payload.get("state") or {}
        turn = payload.get("turn")
        game_over = bool(payload.get("game_over", False))
        summary = str(payload.get("summary", "")).strip()
        env_state = payload.get("env_state") or {}
        artifacts = payload.get("artifacts") or {}
        execution = payload.get("execution") or {}
        return Observation(
            success=success,
            message=message,
            state=state,
            raw=payload,
            game_over=game_over,
            turn=turn if isinstance(turn, int) else None,
            summary=summary or message,
            env_state=env_state if isinstance(env_state, dict) else {},
            artifacts=artifacts if isinstance(artifacts, dict) else {},
            execution=execution if isinstance(execution, dict) else {},
        )

    @staticmethod
    def build_game_client_summary(payload: Dict[str, Any]) -> str:
        """Build a planner-facing summary from a command API payload."""
        message = str(payload.get("message", "")).strip()
        state = payload.get("state") or {}
        room = state.get("room", {}) if isinstance(state, dict) else {}
        room_name = str(room.get("name", "")).strip()
        exits = room.get("exits", [])
        exit_text = ", ".join(str(item) for item in exits) if isinstance(exits, list) else ""
        inventory = state.get("inventory", [])
        inventory_count = len(inventory) if isinstance(inventory, list) else 0
        light_source_text = ObservationParser._light_source_text(inventory)
        can_see = state.get("can_see", None)
        visibility_text = "on" if can_see else "off" if can_see is not None else "unknown"
        hud_parts = []
        if room_name:
            hud_parts.append(f"current room={room_name}")
        if inventory_count or isinstance(inventory, list):
            hud_parts.append(f"inventory load={inventory_count}/6")
        if isinstance(payload.get("turn"), int):
            hud_parts.append(f"current turn={payload['turn']}")
        if light_source_text:
            hud_parts.append(f"light_source={light_source_text}")
        if visibility_text:
            hud_parts.append(f"visibility={visibility_text}")
        if exit_text:
            hud_parts.append(f"exits=[{exit_text}]")
        lines = [line for line in [message, ", ".join(hud_parts)] if line]
        return "\n\n".join(lines).strip()

    @staticmethod
    def _light_source_text(inventory: Any) -> str:
        lit_items: List[str] = []
        if isinstance(inventory, list):
            for item in inventory:
                if not isinstance(item, dict):
                    continue
                item_state = item.get("state", {})
                if isinstance(item_state, dict) and item_state.get("lit") is True:
                    lit_items.append(str(item.get("name", "unknown")))
        return "on" if lit_items else "off"
