"""Tool registry for game API calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from .game_clients import GameClient


ToolHandler = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass
class Tool:
    """Describes a callable tool."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: ToolHandler

    def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.handler(payload)


class ToolRegistry:
    """Registers and invokes tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def invoke(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            return {"success": False, "message": f"Unknown tool: {name}"}
        return self._tools[name].invoke(payload)


def register_standard_game_tools(
    registry: ToolRegistry,
    game_client: GameClient,
) -> None:
    """Register the standard GBQA game tool surface."""
    registry.register(
        Tool(
            name="game_new",
            description="Create a new agent game session.",
            parameters={"type": "object", "properties": {}},
            handler=lambda _: game_client.new_game(),
        )
    )
    registry.register(
        Tool(
            name="game_command",
            description="Send a command to the game.",
            parameters={
                "type": "object",
                "properties": {
                    "game_id": {"type": "string"},
                    "command": {"type": "string"},
                },
                "required": ["game_id", "command"],
            },
            handler=lambda payload: game_client.send_command(
                payload["game_id"], payload["command"]
            ),
        )
    )
    registry.register(
        Tool(
            name="game_state",
            description="Get current game state.",
            parameters={
                "type": "object",
                "properties": {"game_id": {"type": "string"}},
                "required": ["game_id"],
            },
            handler=lambda payload: game_client.get_state(payload["game_id"]),
        )
    )
