"""
Data types and adapters for environment log analysis.
Defines the contract between raw environment data and the analysis engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Set, runtime_checkable


@dataclass(frozen=True)
class CommandState:
    """Represents the state of the environment at a specific point in time."""

    location: Optional[str] = None
    inventory: List[str] = field(default_factory=list)
    # Generic metadata for fields that don't fit into location/inventory
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CommandState:
        """Create a CommandState from a raw dictionary."""
        # Standard GBQA keys are 'room' and 'inventory'
        return cls(
            location=data.get("room") or data.get("url"),
            inventory=data.get("inventory", []),
            metadata={k: v for k, v in data.items() if k not in ("room", "inventory", "url")},
        )


@dataclass(frozen=True)
class NormalizedCommand:
    """Represents a normalized record of a single command execution."""

    turn: int
    command: str
    success: bool
    message: str
    terminal: bool = False
    timestamp: Optional[datetime] = None
    state: Optional[CommandState] = None
    # Raw response data for debugging or specialized analysis
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedSession:
    """Represents a full normalized environment session."""

    commands: List[NormalizedCommand]
    result: str = "in_progress"
    total_turns: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LogAdapter(Protocol):
    """Protocol for converting raw environment logs into normalized formats."""

    def normalize_session(self, raw_data: Dict[str, Any]) -> NormalizedSession:
        """Convert raw session data into a NormalizedSession."""
        ...

    def normalize_debug_output(self, raw_text: str) -> str:
        """Optionally clean up or format raw debug output."""
        ...

    def get_movement_verbs(self) -> Set[str]:
        """Return verbs that typically result in a location/URL change."""
        ...

    def get_removal_verbs(self) -> Set[str]:
        """Return verbs that typically result in items being removed from inventory."""
        ...


class DefaultLogAdapter:
    """Default implementation for standard GBQA/Dark-Castle log format."""

    def normalize_session(self, raw_data: Dict[str, Any]) -> NormalizedSession:
        raw_commands = raw_data.get("commands", [])
        normalized_commands = []

        for cmd_dict in raw_commands:
            ts_str = cmd_dict.get("timestamp")
            ts = None
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    pass

            resp = cmd_dict.get("response", {})
            state_data = cmd_dict.get("state_snapshot", {})

            normalized_commands.append(
                NormalizedCommand(
                    turn=cmd_dict.get("turn", 0),
                    command=cmd_dict.get("command", ""),
                    success=resp.get("success", True),
                    message=resp.get("message", ""),
                    terminal=resp.get("terminal", False),
                    timestamp=ts,
                    state=CommandState.from_dict(state_data) if state_data else None,
                    raw_response=resp,
                )
            )

        return NormalizedSession(
            commands=normalized_commands,
            result=raw_data.get("result", "in_progress"),
            total_turns=raw_data.get("total_turns", len(normalized_commands)),
            metadata={k: v for k, v in raw_data.items() if k not in ("commands", "result", "total_turns")},
        )

    def normalize_debug_output(self, raw_text: str) -> str:
        return raw_text

    def get_movement_verbs(self) -> Set[str]:
        return {"go", "enter", "climb", "down", "up", "move", "north", "south", "east", "west"}

    def get_removal_verbs(self) -> Set[str]:
        return {"drop", "put", "use", "combine", "give", "throw", "eat", "drink"}


class PlaywrightLogAdapter:
    """Adapter for Computer-Use / Web environments."""

    def normalize_session(self, raw_data: Dict[str, Any]) -> NormalizedSession:
        default_adapter = DefaultLogAdapter()
        return default_adapter.normalize_session(raw_data)

    def normalize_debug_output(self, raw_text: str) -> str:
        return raw_text

    def get_movement_verbs(self) -> Set[str]:
        return {"click", "navigate", "type", "submit", "press"}

    def get_removal_verbs(self) -> Set[str]:
        return {"delete", "remove", "clear", "extract"}
