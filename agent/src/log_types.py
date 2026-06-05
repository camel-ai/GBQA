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
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CommandState:
        """Heuristically extract state from a dictionary."""
        return cls(
            location=data.get("room") or data.get("url") or data.get("location"),
            inventory=data.get("inventory") or data.get("items") or [],
            metadata={k: v for k, v in data.items() if k not in ("room", "url", "inventory", "items", "location")},
        )


@dataclass(frozen=True)
class NormalizedCommand:
    """Represents a normalized record of a single command execution."""

    step: int
    command: str
    success: bool
    message: str
    terminal: bool = False
    timestamp: Optional[datetime] = None
    state: Optional[CommandState] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedSession:
    """Represents a full normalized environment session."""

    commands: List[NormalizedCommand]
    result: str = "in_progress"
    total_steps: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LogAdapter(Protocol):
    """Protocol for converting raw environment logs into normalized formats."""

    def normalize_session(self, raw_data: Dict[str, Any]) -> NormalizedSession: ...
    def normalize_debug_output(self, raw_text: str) -> str: ...
    def get_movement_verbs(self) -> Set[str]: ...
    def get_removal_verbs(self) -> Set[str]: ...


class UniversalLogAdapter:
    """
    A single, robust adapter that handles various GBQA log formats (API, Daytona, Web)
    using heuristic field mapping.
    """

    DEFAULT_MOVEMENT = {"go", "enter", "climb", "down", "up", "move", "north", "south", "east", "west", "navigate", "click"}
    DEFAULT_REMOVAL = {"drop", "put", "use", "combine", "give", "throw", "eat", "drink", "delete", "remove"}

    def __init__(self, movement_verbs: Optional[Set[str]] = None, removal_verbs: Optional[Set[str]] = None):
        self._movement_verbs = movement_verbs or self.DEFAULT_MOVEMENT
        self._removal_verbs = removal_verbs or self.DEFAULT_REMOVAL

    def normalize_session(self, raw_data: Dict[str, Any]) -> NormalizedSession:
        # Heuristically find the list of steps/commands
        steps = raw_data.get("steps") or raw_data.get("commands") or []
        normalized_commands = []

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            
            # 1. Extract observation/response (Daytona wraps in 'observation' or 'environment')
            obs = step.get("observation") or step.get("environment") or step
            resp = obs.get("response") or obs if isinstance(obs, dict) else {"message": str(obs), "success": True}
            
            # 2. Extract command text (Daytona wraps in 'action')
            cmd_text = step.get("command") or step.get("action", {}).get("command") or "unknown"
            
            # 3. Extract state
            state_data = {}
            if isinstance(obs, dict):
                # Try nested keys first, then fall back to the observation itself
                state_data = obs.get("state_snapshot") or obs.get("state") or obs

            # 4. Extract timestamp
            ts_str = step.get("timestamp") or (obs.get("timestamp") if isinstance(obs, dict) else None)
            ts = None
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    pass

            normalized_commands.append(
                NormalizedCommand(
                    step=step.get("step") or i,
                    command=str(cmd_text),
                    success=resp.get("success", True) if isinstance(resp, dict) else True,
                    message=str(resp.get("message", "")) if isinstance(resp, dict) else str(resp),
                    terminal=resp.get("terminal", False) if isinstance(resp, dict) else False,
                    timestamp=ts,
                    state=CommandState.from_dict(state_data) if state_data else None,
                    raw_response=resp if isinstance(resp, dict) else {"raw": resp},
                )
            )

        return NormalizedSession(
            commands=normalized_commands,
            result=raw_data.get("result", "in_progress"),
            total_steps=raw_data.get("total_steps", len(normalized_commands)),
            metadata=raw_data,
        )

    def normalize_debug_output(self, raw_text: str) -> str:
        return raw_text

    def get_movement_verbs(self) -> Set[str]:
        return self._movement_verbs

    def get_removal_verbs(self) -> Set[str]:
        return self._removal_verbs
