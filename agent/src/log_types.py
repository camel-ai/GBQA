"""Normalized log types and adapter protocol for log analysis.

The LogAnalyzer works exclusively with these normalized types so that
analysis logic is decoupled from any specific game backend log format.
Each backend supplies a LogAdapter that converts its raw session data
into the normalized schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class CommandState:
    """Normalized snapshot of game state at a single turn."""

    room: Optional[str] = None
    inventory: List[str] = field(default_factory=list)


@dataclass
class NormalizedCommand:
    """A single command-response pair in normalized form."""

    turn: int
    timestamp: str
    command: str
    success: bool
    message: str
    game_over: bool = False
    state: Optional[CommandState] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "turn": self.turn,
            "timestamp": self.timestamp,
            "command": self.command,
            "success": self.success,
            "message": self.message,
            "game_over": self.game_over,
        }
        if self.state is not None:
            d["state"] = asdict(self.state)
        return d


@dataclass
class NormalizedSession:
    """A full game session in normalized form."""

    commands: List[NormalizedCommand]
    total_turns: int
    result: str = "in_progress"


class LogAdapter(Protocol):
    """Protocol for converting backend-specific log data into normalized form.

    Implement this for each game backend to decouple log analysis from
    the specific runtime log shape.
    """

    def normalize_session(self, raw_data: Dict[str, Any]) -> NormalizedSession:
        """Convert raw session data (as returned by the backend) into a NormalizedSession."""
        ...

    def normalize_debug_output(self, raw_text: str) -> str:
        """Normalize raw debug/stdout text. Return as-is if no transformation needed."""
        ...


class DefaultLogAdapter:
    """Adapter for the standard GBQA game backend log format.

    Expected raw_data shape (as returned by RuntimeLogProvider.read_session_log):

        {
            "commands": [
                {
                    "turn": int,
                    "timestamp": str (ISO),
                    "command": str,
                    "response": {"success": bool, "message": str, "game_over": bool},
                    "state_snapshot": {"room": str | None, "inventory": [str, ...]}
                },
                ...
            ],
            "total_turns": int,
            "result": str
        }

    Other backends should implement their own LogAdapter to normalize
    their specific format into the same NormalizedSession structure.
    """

    def normalize_session(self, raw_data: Dict[str, Any]) -> NormalizedSession:
        commands: List[NormalizedCommand] = []
        for cmd in raw_data.get("commands", []):
            resp = cmd.get("response", {})
            snap = cmd.get("state_snapshot") or {}
            state = None
            if snap:
                state = CommandState(
                    room=snap.get("room"),
                    inventory=list(snap.get("inventory", [])),
                )
            commands.append(
                NormalizedCommand(
                    turn=cmd.get("turn", 0),
                    timestamp=cmd.get("timestamp", ""),
                    command=cmd.get("command", ""),
                    success=resp.get("success", True),
                    message=resp.get("message", ""),
                    game_over=resp.get("game_over", False),
                    state=state,
                )
            )
        return NormalizedSession(
            commands=commands,
            total_turns=raw_data.get("total_turns", len(commands)),
            result=raw_data.get("result", "in_progress"),
        )

    def normalize_debug_output(self, raw_text: str) -> str:
        return raw_text
