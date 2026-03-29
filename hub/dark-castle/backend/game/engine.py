"""
Game engine module.
Coordinate world state, command parsing, and action execution.
"""

import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from .actions import ActionHandler
from .logger import GameLogger
from .parser import CommandParser
from .world import GameWorld


class GameEngine:
    """Primary game engine for a single session."""

    def __init__(self):
        self.game_id: str = ""
        self.world: Optional[GameWorld] = None
        self.parser: Optional[CommandParser] = None
        self.action_handler: Optional[ActionHandler] = None
        self.initialized: bool = False
        self.logger: Optional[GameLogger] = None

    def new_game(self) -> Dict[str, Any]:
        """Start a new game session."""
        self.game_id = str(uuid.uuid4())
        self.world = GameWorld()
        self.parser = CommandParser()

        self.logger = GameLogger()
        log_file = self.logger.start_new_session(self.game_id)
        print(f"[Game] New session log: {log_file}")

        data_dir = Path(__file__).parent / "data"
        self.world.load_data(str(data_dir / "rooms.json"), str(data_dir / "items.json"))

        self.action_handler = ActionHandler(self.world)
        self.initialized = True

        initial_response = self._get_initial_response()
        if self.logger:
            self.logger.log_initial_state(self.world.get_visible_state())

        return initial_response

    def _get_initial_response(self) -> Dict[str, Any]:
        """Build the opening text shown when a game starts."""
        intro_message = """
===============================================================
               Dark Castle: Night of Awakening
===============================================================

Lightning tears across the sky, and you awaken with a violent start.

When your vision steadies, you realize you are standing inside the hall
of an unfamiliar castle. Candlelight flickers weakly against the stone,
and the storm outside howls without mercy.

You remember nothing about how you arrived here.

When you try the great door behind you, a strange violet seal flares to life.
Whatever trapped you here will not let you leave so easily.

Somewhere in this castle there must be a special key strong enough to
break the seal. You will need to search every room, solve every puzzle,
and uncover the castle's secrets if you want to escape.

Type 'help' to view the command list.
Good luck, adventurer.

===============================================================
"""

        room = self.world.get_current_room()
        room_desc = self._describe_room(room)

        return {
            "game_id": self.game_id,
            "success": True,
            "message": intro_message + "\n" + room_desc,
            "state": self.world.get_visible_state(),
            "game_over": False,
        }

    def process_command(self, input_text: str) -> Dict[str, Any]:
        """Process a line of player input."""
        if not self.initialized:
            return {
                "success": False,
                "message": "The game is not initialized yet. Start a new game first.",
                "state": None,
                "game_over": False,
            }

        if self.world.flags.get("game_won"):
            return {
                "success": False,
                "message": "The game is already over. You escaped the castle. Type 'restart' to begin again.",
                "state": self.world.get_visible_state(),
                "game_over": True,
            }

        if input_text.strip().lower() in ["restart", "reset", "new game"]:
            if self.logger:
                self.logger.end_session(self.world.get_visible_state(), "abandoned")
            return self.new_game()

        command = self.parser.parse(input_text)
        result = self.action_handler.execute(command)

        self.world.add_message(f"> {input_text}")
        self.world.add_message(result.message)

        response = {
            "success": result.success,
            "message": result.message,
            "state": self.world.get_visible_state(),
            "game_over": result.game_over,
            "turn": self.world.turn_count,
        }

        if self.logger:
            self.logger.log_command(
                command=input_text,
                response=response,
                turn=self.world.turn_count,
                state=self.world.get_visible_state(),
            )

        return response

    def get_state(self) -> Dict[str, Any]:
        """Return the current state payload."""
        if not self.initialized:
            return {
                "initialized": False,
                "message": "The game has not been initialized.",
            }

        return {
            "initialized": True,
            "game_id": self.game_id,
            "state": self.world.get_visible_state(),
            "full_state": self.world.to_dict(),
        }

    def get_valid_actions(self) -> Dict[str, Any]:
        """Return the currently available actions for agent-driven play."""
        if not self.initialized:
            return {"valid_actions": []}

        actions = []
        room = self.world.get_current_room()
        can_see = self.world.can_see()

        for direction, room_id in room.exits.items():
            target_room = self.world.get_room(room_id)
            if target_room and not target_room.locked:
                if not (room_id == "attic" and not self.world.flags.get("ladder_placed")):
                    actions.append(f"go {direction}")

        actions.append("look")
        actions.append("inventory")

        if can_see:
            room_items = self.world.get_items_in_room(self.world.current_room)
            for item in room_items:
                if item.portable and item.id not in self.world.inventory:
                    actions.append(f"take {item.name}")
                actions.append(f"examine {item.name}")

            for item_id in self.world.inventory:
                item = self.world.get_item(item_id)
                if item:
                    actions.append(f"drop {item.name}")
                    if item.state.get("lit") is False:
                        actions.append(f"light {item.name}")

        return {
            "valid_actions": actions,
            "current_room": room.id,
            "can_see": can_see,
        }

    def _describe_room(self, room) -> str:
        """Build the initial room description shown at game start."""
        if room.dark and not self.world.has_light_source():
            return f"[{room.name}]\n\n{room.dark_description}"

        description = f"[{room.name}]\n\n{self.world.get_dynamic_room_description(room.id)}"

        visible_items = [
            item for item in self.world.get_items_in_room(room.id) if item.portable and not item.hidden
        ]
        if visible_items:
            item_names = [item.name for item in visible_items]
            description += f"\n\nYou notice: {', '.join(item_names)}."

        if room.exits:
            description += f"\n\nExits: {', '.join(room.exits.keys())}"

        return description


game_sessions: Dict[str, GameEngine] = {}


def get_or_create_game(session_id: str = None) -> GameEngine:
    """Return an existing game engine or create a new one."""
    if session_id and session_id in game_sessions:
        return game_sessions[session_id]

    engine = GameEngine()
    if session_id:
        game_sessions[session_id] = engine
    return engine


def create_new_game() -> tuple[str, GameEngine]:
    """Create a new game engine and store it in the session map."""
    engine = GameEngine()
    engine.new_game()
    game_sessions[engine.game_id] = engine
    return engine.game_id, engine
