"""
World state management module.
Track rooms, items, and player-visible game state.
"""

import json
from typing import Any, Dict, List, Optional


class Item:
    """Game item."""

    def __init__(self, data: Dict[str, Any]):
        self.id = data["id"]
        self.name = data["name"]
        self.description = data["description"]
        self.portable = data.get("portable", True)
        self.location = data.get("location", None)
        self.container = data.get("container", False)
        self.contents = data.get("contents", [])
        self.state = data.get("state", {})
        self.interactions = data.get("interactions", [])
        self.examine_text = data.get("examine_text", self.description)
        self.hidden = data.get("hidden", False)
        self.requires = data.get("requires", None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "portable": self.portable,
            "location": self.location,
            "container": self.container,
            "contents": self.contents,
            "state": self.state,
            "interactions": self.interactions,
            "examine_text": self.examine_text,
            "hidden": self.hidden,
            "requires": self.requires,
        }

    def is_open(self) -> bool:
        return self.state.get("open", False)

    def is_locked(self) -> bool:
        return self.state.get("locked", False)

    def is_lit(self) -> bool:
        return self.state.get("lit", False)


class Room:
    """Game room."""

    def __init__(self, data: Dict[str, Any]):
        self.id = data["id"]
        self.name = data["name"]
        self.base_description = data.get("base_description", data.get("description", ""))
        self.static_elements = data.get("static_elements", "")
        self.dynamic_elements = data.get("dynamic_elements", [])
        self.description = data.get("description", self.base_description)
        self.exits = data.get("exits", {})
        self.dark = data.get("dark", False)
        self.visited = data.get("visited", False)
        self.locked = data.get("locked", False)
        self.lock_key = data.get("lock_key", None)
        self.requires_item = data.get("requires_item", None)
        self.dark_description = data.get(
            "dark_description",
            "It is pitch-black here. You cannot see anything.",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "base_description": self.base_description,
            "static_elements": self.static_elements,
            "dynamic_elements": self.dynamic_elements,
            "exits": self.exits,
            "dark": self.dark,
            "visited": self.visited,
            "locked": self.locked,
            "lock_key": self.lock_key,
            "requires_item": self.requires_item,
            "dark_description": self.dark_description,
        }


class GameWorld:
    """Own all mutable state for a single playthrough."""

    MAX_INVENTORY = 6

    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self.items: Dict[str, Item] = {}
        self.current_room: str = "hall"
        self.inventory: List[str] = []
        self.flags: Dict[str, bool] = {
            "key_assembled": False,
            "door_unlocked": False,
            "game_won": False,
            "ladder_placed": False,
        }
        self.turn_count: int = 0
        self.message_history: List[str] = []

    def load_data(self, rooms_path: str, items_path: str):
        """Load room and item data from JSON files."""
        with open(rooms_path, "r", encoding="utf-8") as file:
            rooms_data = json.load(file)
        with open(items_path, "r", encoding="utf-8") as file:
            items_data = json.load(file)

        for room_data in rooms_data["rooms"]:
            room = Room(room_data)
            self.rooms[room.id] = room

        for item_data in items_data["items"]:
            item = Item(item_data)
            self.items[item.id] = item

    def get_current_room(self) -> Room:
        """Return the player's current room."""
        return self.rooms[self.current_room]

    def get_room(self, room_id: str) -> Optional[Room]:
        """Return a room by id."""
        return self.rooms.get(room_id)

    def get_item(self, item_id: str) -> Optional[Item]:
        """Return an item by id."""
        return self.items.get(item_id)

    def get_items_in_room(self, room_id: str) -> List[Item]:
        """Return all visible items in a room."""
        items = []
        for item in self.items.values():
            if item.location == room_id and not item.hidden:
                items.append(item)
        return items

    def get_items_in_inventory(self) -> List[Item]:
        """Return all items currently in the player's inventory."""
        return [self.items[item_id] for item_id in self.inventory if item_id in self.items]

    def get_items_in_container(self, container_id: str) -> List[Item]:
        """Return all items stored inside an open container."""
        container = self.get_item(container_id)
        if not container or not container.container:
            return []
        return [self.items[item_id] for item_id in container.contents if item_id in self.items]

    def find_item_by_name(
        self,
        name: str,
        search_inventory: bool = True,
        search_room: bool = True,
    ) -> Optional[Item]:
        """Find an item by fuzzy-matching against its name or id."""
        name_lower = name.lower()

        if search_inventory:
            for item_id in self.inventory:
                item = self.items.get(item_id)
                if item and (name_lower in item.name.lower() or name_lower in item.id.lower()):
                    return item

        if search_room:
            for item in self.get_items_in_room(self.current_room):
                if name_lower in item.name.lower() or name_lower in item.id.lower():
                    return item

        for item in self.items.values():
            if item.location == self.current_room:
                if name_lower in item.name.lower() or name_lower in item.id.lower():
                    return item

        if search_room:
            for container in self.items.values():
                if (
                    container.location == self.current_room
                    and container.container
                    and container.is_open()
                ):
                    for content_id in container.contents:
                        content_item = self.items.get(content_id)
                        if content_item and not content_item.hidden:
                            if (
                                name_lower in content_item.name.lower()
                                or name_lower in content_item.id.lower()
                            ):
                                return content_item

        return None

    def has_light_source(self) -> bool:
        """Return whether the player carries a lit light source."""
        for item_id in self.inventory:
            item = self.items.get(item_id)
            if item and item.is_lit():
                return True
        return False

    def can_see(self) -> bool:
        """Return whether the current room is visible to the player."""
        room = self.get_current_room()
        if not room.dark:
            return True
        return self.has_light_source()

    def move_item_to_inventory(self, item: Item) -> bool:
        """Move an item into the player's inventory."""
        if len(self.inventory) >= self.MAX_INVENTORY:
            return False

        if item.location and item.location != "inventory":
            for container in self.items.values():
                if container.container and item.id in container.contents:
                    container.contents.remove(item.id)
                    break

        item.location = "inventory"
        if item.id not in self.inventory:
            self.inventory.append(item.id)
        return True

    def drop_item(self, item: Item, room_id: str = None) -> bool:
        """Drop an item into the current room or a specific room."""
        if room_id is None:
            room_id = self.current_room

        if item.id in self.inventory:
            self.inventory.remove(item.id)

        item.location = room_id
        return True

    def put_item_in_container(self, item: Item, container: Item) -> bool:
        """Place an item into an open container."""
        if not container.container or not container.is_open():
            return False

        if item.id in self.inventory:
            self.inventory.remove(item.id)

        item.location = container.id
        if item.id not in container.contents:
            container.contents.append(item.id)
        return True

    def increment_turn(self):
        """Advance the turn counter."""
        self.turn_count += 1

    def add_message(self, message: str):
        """Append a message to the recent message history."""
        self.message_history.append(message)

    def get_dynamic_room_description(self, room_id: str = None) -> str:
        """Build a room description from the room config and current state."""
        if room_id is None:
            room_id = self.current_room

        room = self.rooms.get(room_id)
        if not room:
            return "Unknown room."

        if not room.dynamic_elements and not room.base_description:
            return room.description

        parts = [room.base_description]

        for element in room.dynamic_elements:
            if self._check_condition(element.get("condition", {}), room_id):
                parts.append(element.get("text", ""))

        if room.static_elements:
            parts.append(room.static_elements)

        return " ".join(filter(None, parts))

    def _check_condition(self, condition: Dict[str, Any], room_id: str) -> bool:
        """Evaluate a room-description condition."""
        cond_type = condition.get("type", "")

        if cond_type == "item_in_room":
            item_id = condition.get("item_id")
            item = self.items.get(item_id)
            return bool(item and item.location == room_id)

        if cond_type == "item_in_container":
            container_id = condition.get("container_id")
            item_id = condition.get("item_id")
            container = self.items.get(container_id)
            item = self.items.get(item_id)
            return bool(container and item and item.location == container_id and item_id in container.contents)

        if cond_type == "item_state":
            item_id = condition.get("item_id")
            state_key = condition.get("state")
            expected_value = condition.get("value")
            item = self.items.get(item_id)
            if item:
                return item.state.get(state_key) == expected_value
            return False

        if cond_type == "flag":
            flag_name = condition.get("flag")
            expected_value = condition.get("value", True)
            return self.flags.get(flag_name, False) == expected_value

        if cond_type == "room_locked":
            target_room_id = condition.get("room_id")
            expected_value = condition.get("value", True)
            target_room = self.rooms.get(target_room_id)
            if target_room:
                return target_room.locked == expected_value
            return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Export the full internal game state."""
        return {
            "current_room": self.current_room,
            "inventory": self.inventory,
            "rooms": {room_id: room.to_dict() for room_id, room in self.rooms.items()},
            "items": {item_id: item.to_dict() for item_id, item in self.items.items()},
            "flags": self.flags,
            "turn_count": self.turn_count,
            "message_history": self.message_history[-20:],
        }

    def get_visible_state(self) -> Dict[str, Any]:
        """Export the player-visible slice of the current state."""
        room = self.get_current_room()
        can_see = self.can_see()

        visible_items = []
        if can_see:
            for item in self.get_items_in_room(self.current_room):
                visible_items.append(
                    {
                        "id": item.id,
                        "name": item.name,
                        "description": item.description,
                    }
                )

        inventory_items = []
        for item in self.get_items_in_inventory():
            inventory_items.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "state": item.state,
                }
            )

        return {
            "room": {
                "id": room.id,
                "name": room.name,
                "description": self.get_dynamic_room_description(room.id)
                if can_see
                else room.dark_description,
                "exits": list(room.exits.keys()) if can_see else [],
                "dark": room.dark and not can_see,
            },
            "items": visible_items,
            "inventory": inventory_items,
            "flags": self.flags,
            "turn_count": self.turn_count,
            "can_see": can_see,
        }
