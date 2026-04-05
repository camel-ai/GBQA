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


def register_code_reading_tools(
    registry: ToolRegistry,
    game_client: GameClient,
) -> None:
    """Register code tools for listing, reading, searching, writing, restoring, and reading debug logs."""
    registry.register(
        Tool(
            name="code_list_files",
            description="List all source code files in the game.",
            parameters={"type": "object", "properties": {}},
            handler=lambda _: game_client.list_code_files(),
        )
    )
    registry.register(
        Tool(
            name="code_read_file",
            description="Read the content of a source code file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["path"],
            },
            handler=lambda payload: game_client.read_code_file(
                payload["path"],
                start_line=int(payload.get("start_line", 0)),
                end_line=int(payload.get("end_line", 0)),
            ),
        )
    )
    registry.register(
        Tool(
            name="code_search",
            description="Search for a pattern across game source code files.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                },
                "required": ["pattern"],
            },
            handler=lambda payload: game_client.search_code(payload["pattern"]),
        )
    )
    registry.register(
        Tool(
            name="code_write_file",
            description="Modify or overwrite a source code file. Use 'patch' for search-and-replace or 'content' for full overwrite.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "patch": {
                        "type": "object",
                        "properties": {
                            "search": {"type": "string"},
                            "replace": {"type": "string"},
                        }
                    },
                },
                "required": ["path"],
            },
            handler=lambda payload: game_client.write_code_file(
                payload["path"],
                content=payload.get("content", ""),
                patch=payload.get("patch"),
            ),
        )
    )
    registry.register(
        Tool(
            name="code_read_debug_logs",
            description="Read the captured stdout/print logs from the game server.",
            parameters={
                "type": "object",
                "properties": {
                    "clear": {"type": "boolean"},
                    "game_id": {"type": "string"},
                },
            },
            handler=lambda payload: game_client.read_debug_logs(
                payload.get("game_id", ""),
                clear=payload.get("clear", False)
            ),
        )
    )
    registry.register(
        Tool(
            name="code_restore_file",
            description="Restore the last backup for a source code file previously changed with code_write_file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
            handler=lambda payload: game_client.restore_code_file(payload["path"]),
        )
    )


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
