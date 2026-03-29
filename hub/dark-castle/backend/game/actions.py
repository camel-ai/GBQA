"""
Action handling module.
Implement the game logic for each supported player action.
"""

from typing import Any, Callable, Dict

from .parser import ParsedCommand
from .world import GameWorld, Item


class ActionResult:
    """Result of executing a player action."""

    def __init__(
        self,
        success: bool,
        message: str,
        state_changed: bool = False,
        game_over: bool = False,
    ):
        self.success = success
        self.message = message
        self.state_changed = state_changed
        self.game_over = game_over

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "state_changed": self.state_changed,
            "game_over": self.game_over,
        }


class ActionHandler:
    """Dispatch parsed commands to concrete action handlers."""

    def __init__(self, world: GameWorld):
        self.world = world
        self.handlers: Dict[str, Callable] = {
            "go": self.handle_go,
            "look": self.handle_look,
            "examine": self.handle_examine,
            "inventory": self.handle_inventory,
            "take": self.handle_take,
            "drop": self.handle_drop,
            "put": self.handle_put,
            "open": self.handle_open,
            "close": self.handle_close,
            "use": self.handle_use,
            "light": self.handle_light,
            "unlock": self.handle_unlock,
            "read": self.handle_read,
            "combine": self.handle_combine,
            "climb": self.handle_climb,
            "oil": self.handle_oil,
            "help": self.handle_help,
            "enter": self.handle_enter,
            "empty": self.handle_empty,
            "unknown": self.handle_unknown,
        }

    def execute(self, command: ParsedCommand) -> ActionResult:
        """Execute a parsed command."""
        handler = self.handlers.get(command.action, self.handle_unknown)
        result = handler(command)

        if result.state_changed:
            self.world.increment_turn()

        return result

    def handle_go(self, command: ParsedCommand) -> ActionResult:
        """Move the player to another room."""
        if not command.target:
            return ActionResult(
                False,
                "Where do you want to go? Specify a direction (north/south/east/west/up/down) or a room name.",
            )

        current_room = self.world.get_current_room()
        target = command.target.lower()

        if target not in current_room.exits:
            target_room_id = None
            for direction, room_id in current_room.exits.items():
                if room_id == target:
                    target_room_id = room_id
                    break

            if not target_room_id:
                available_exits = ", ".join(current_room.exits.keys())
                return ActionResult(
                    False,
                    f"You cannot go that way. Available exits: {available_exits}",
                )

            target = list(current_room.exits.keys())[
                list(current_room.exits.values()).index(target_room_id)
            ]

        target_room_id = current_room.exits[target]
        target_room = self.world.get_room(target_room_id)

        if not target_room:
            return ActionResult(False, "That direction seems to lead nowhere.")

        if target_room.locked:
            return ActionResult(
                False,
                f"The way into {target_room.name} is locked. You need the right key to enter.",
            )

        if target_room_id == "attic" and not self.world.flags.get("ladder_placed"):
            return ActionResult(
                False,
                "The trapdoor is too high to reach. You need something to climb on first.",
            )

        self.world.current_room = target_room_id
        target_room.visited = True
        return ActionResult(True, self._describe_room(target_room), state_changed=True)

    def handle_look(self, command: ParsedCommand) -> ActionResult:
        """Describe the current room or examine a target."""
        room = self.world.get_current_room()
        if command.target:
            return self.handle_examine(command)
        return ActionResult(True, self._describe_room(room))

    def handle_examine(self, command: ParsedCommand) -> ActionResult:
        """Examine an item in detail."""
        if not command.target:
            return ActionResult(False, "What do you want to examine?")

        if not self.world.can_see():
            return ActionResult(
                False,
                "It is too dark to make anything out. You need a light source.",
            )

        item = self.world.find_item_by_name(command.target)
        if not item:
            return ActionResult(False, f"You do not see anything here called '{command.target}'.")

        result_text = item.examine_text

        if item.container and item.is_open():
            contents = self.world.get_items_in_container(item.id)
            if contents:
                content_names = [contained_item.name for contained_item in contents]
                result_text += f"\nInside you see: {', '.join(content_names)}."
            else:
                result_text += "\nIt is empty."

        if item.state:
            if item.is_lit():
                result_text += "\nIt is burning, casting a warm and steady light."
            if item.is_locked():
                result_text += "\nIt is locked."

        return ActionResult(True, result_text)

    def handle_inventory(self, command: ParsedCommand) -> ActionResult:
        """List the items in the player's inventory."""
        items = self.world.get_items_in_inventory()
        if not items:
            return ActionResult(True, "Your inventory is empty.")

        lines = []
        for item in items:
            status = " (lit)" if item.is_lit() else ""
            lines.append(f"  - {item.name}{status}")

        result = "You are carrying:\n" + "\n".join(lines)
        result += f"\n({len(items)}/{self.world.MAX_INVENTORY})"
        return ActionResult(True, result)

    def handle_take(self, command: ParsedCommand) -> ActionResult:
        """Pick up an item."""
        if not command.target:
            return ActionResult(False, "What do you want to take?")

        if not self.world.can_see():
            return ActionResult(False, "It is too dark to see anything you could pick up.")

        item = self.world.find_item_by_name(command.target, search_inventory=False)
        if not item:
            return ActionResult(False, f"You do not see anything here called '{command.target}'.")

        if not item.portable:
            return ActionResult(False, f"The {item.name} is fixed in place or too bulky to carry.")

        if item.id in self.world.inventory:
            return ActionResult(False, f"You are already carrying the {item.name}.")

        for container in self.world.items.values():
            if container.container and item.id in container.contents:
                if not container.is_open():
                    return ActionResult(
                        False,
                        f"The {item.name} is inside the {container.name}, but it is closed.",
                    )
                container.contents.remove(item.id)
                break

        if len(self.world.inventory) >= self.world.MAX_INVENTORY:
            return ActionResult(
                False,
                "Your inventory is full. You need to drop something first.",
            )

        self.world.move_item_to_inventory(item)
        item.hidden = False
        return ActionResult(True, f"You pick up the {item.name}.", state_changed=True)

    def handle_drop(self, command: ParsedCommand) -> ActionResult:
        """Drop an item from the inventory."""
        if not command.target:
            return ActionResult(False, "What do you want to drop?")

        item = self.world.find_item_by_name(command.target, search_room=False)
        if not item:
            return ActionResult(False, f"You are not carrying anything called '{command.target}'.")

        if item.id not in self.world.inventory:
            return ActionResult(False, f"You are not carrying the {item.name}.")

        self.world.drop_item(item)
        return ActionResult(True, f"You drop the {item.name}.", state_changed=True)

    def handle_put(self, command: ParsedCommand) -> ActionResult:
        """Place an item into a container."""
        if not command.target:
            return ActionResult(False, "What do you want to put down?")

        if not command.secondary_target:
            return ActionResult(False, "Where do you want to put it?")

        item = self.world.find_item_by_name(command.target, search_room=False)
        container = self.world.find_item_by_name(command.secondary_target)

        if not item:
            return ActionResult(False, f"You are not carrying anything called '{command.target}'.")

        if not container:
            return ActionResult(False, f"You do not see any '{command.secondary_target}' here.")

        if not container.container:
            return ActionResult(False, f"The {container.name} cannot hold items.")

        if not container.is_open():
            return ActionResult(False, f"The {container.name} is closed. Open it first.")

        self.world.put_item_in_container(item, container)
        return ActionResult(
            True,
            f"You place the {item.name} into the {container.name}.",
            state_changed=True,
        )

    def handle_open(self, command: ParsedCommand) -> ActionResult:
        """Open a container or door."""
        if not command.target:
            return ActionResult(False, "What do you want to open?")

        item = self.world.find_item_by_name(command.target)
        if not item:
            return ActionResult(False, f"You do not see anything here called '{command.target}'.")

        if item.id == "sealed_door":
            if self.world.flags.get("door_unlocked"):
                self.world.flags["game_won"] = True
                return ActionResult(
                    True,
                    "As the Key of Awakening turns, the violet seal around the door unravels and fades away. The heavy door creaks open, and moonlight spills into the hall.\n\nYou have escaped the castle. Victory is yours.\n\nCongratulations. You completed Dark Castle: Night of Awakening.",
                    state_changed=True,
                    game_over=True,
                )
            return ActionResult(
                False,
                "The sealed door is held shut by powerful magic. You need a special key to open it.",
            )

        if item.id == "old_chest" and item.is_locked():
            return ActionResult(
                False,
                "The chest is secured with a numeric lock. Try 'enter [number]' to enter a code.",
            )

        if item.id == "iron_door":
            if item.state.get("rusted"):
                return ActionResult(
                    False,
                    "The lock is too badly rusted to force open. Oiling it might help.",
                )
            if not item.is_open():
                item.state["open"] = True
                key_fragment = self.world.get_item("key_fragment_c")
                if key_fragment:
                    key_fragment.hidden = False
                    key_fragment.location = "basement"
                return ActionResult(
                    True,
                    "With the rust loosened, the iron door finally groans open. Behind it is a small hidden chamber, and on the floor you spot a glowing metal fragment.",
                    state_changed=True,
                )

        if item.container:
            if item.is_open():
                return ActionResult(False, f"The {item.name} is already open.")

            if item.is_locked():
                return ActionResult(False, f"The {item.name} is locked.")

            item.state["open"] = True
            contents = self.world.get_items_in_container(item.id)
            for contained_item in contents:
                contained_item.hidden = False

            if contents:
                content_names = [contained_item.name for contained_item in contents]
                return ActionResult(
                    True,
                    f"You open the {item.name}. Inside you find: {', '.join(content_names)}.",
                    state_changed=True,
                )

            return ActionResult(
                True,
                f"You open the {item.name}, but it is empty.",
                state_changed=True,
            )

        return ActionResult(False, f"The {item.name} cannot be opened.")

    def handle_close(self, command: ParsedCommand) -> ActionResult:
        """Close an open container."""
        if not command.target:
            return ActionResult(False, "What do you want to close?")

        item = self.world.find_item_by_name(command.target)
        if not item:
            return ActionResult(False, f"You do not see anything here called '{command.target}'.")

        if not item.container:
            return ActionResult(False, f"The {item.name} cannot be closed.")

        if not item.is_open():
            return ActionResult(False, f"The {item.name} is already closed.")

        item.state["open"] = False
        return ActionResult(True, f"You close the {item.name}.", state_changed=True)

    def handle_use(self, command: ParsedCommand) -> ActionResult:
        """Use an item, optionally on a second target."""
        if not command.target:
            return ActionResult(False, "What do you want to use?")

        item = self.world.find_item_by_name(command.target)
        if not item:
            return ActionResult(False, f"You are not carrying anything called '{command.target}'.")

        if item.id == "ladder":
            if self.world.current_room != "library":
                return ActionResult(False, "There is nowhere useful to set up the ladder here.")
            if item.id not in self.world.inventory:
                return ActionResult(False, "You need to pick up the ladder first.")

            self.world.flags["ladder_placed"] = True
            item.state["placed"] = True
            self.world.drop_item(item, "library")
            return ActionResult(
                True,
                "You set the ladder beneath the trapdoor. Now you can climb up into the attic.",
                state_changed=True,
            )

        if item.id == "complete_key":
            if self.world.current_room != "hall":
                return ActionResult(False, "There is nothing here that fits the Key of Awakening.")

            sealed_door = self.world.get_item("sealed_door")
            if sealed_door:
                self.world.flags["door_unlocked"] = True
                sealed_door.state["locked"] = False
                sealed_door.state["sealed"] = False
                return ActionResult(
                    True,
                    "You slide the Key of Awakening into the lock. Light races along the runes carved into the key and answers the seal on the door. The magic begins to break.\nYou can open the door now.",
                    state_changed=True,
                )

        if item.id == "small_key":
            if command.secondary_target:
                target_lower = command.secondary_target.lower()
                storage_names = ["storage", "storage room", "storeroom"]
                if any(name in target_lower for name in storage_names):
                    return self._unlock_storage()

                target = self.world.find_item_by_name(command.secondary_target)
                if target and target.id == "storage":
                    return self._unlock_storage()

            if self.world.current_room == "hall":
                storage = self.world.get_room("storage")
                if storage and storage.locked:
                    return self._unlock_storage()

            return ActionResult(False, "That key does not seem to fit anything here.")

        if item.id in ["key_fragment_a", "key_fragment_b", "key_fragment_c"]:
            return self.handle_combine(command)

        if command.secondary_target:
            secondary = self.world.find_item_by_name(command.secondary_target)
            if secondary and (item.id == "matches" or item.id in ["candlestick", "oil_lamp"]):
                return self._try_light(item, secondary)

        return ActionResult(False, f"You are not sure how to use the {item.name} here.")

    def handle_light(self, command: ParsedCommand) -> ActionResult:
        """Light a valid target with matches."""
        if not command.target:
            return ActionResult(False, "What do you want to light?")

        target = self.world.find_item_by_name(command.target)
        if not target:
            return ActionResult(False, f"You do not see any '{command.target}' here.")

        matches = self.world.get_item("matches")
        if not matches or matches.id not in self.world.inventory:
            return ActionResult(
                False,
                "You do not have anything to ignite it with. You need matches or another flame.",
            )

        return self._try_light(matches, target)

    def _try_light(self, fire_source: Item, target: Item) -> ActionResult:
        """Attempt to light an object."""
        lightable = ["candlestick", "oil_lamp", "fireplace"]
        if target.id not in lightable:
            return ActionResult(False, f"The {target.name} cannot be lit.")

        if target.is_lit():
            return ActionResult(False, f"The {target.name} is already lit.")

        if target.id == "oil_lamp" and not target.state.get("has_oil"):
            return ActionResult(False, "The oil lamp is out of fuel.")

        target.state["lit"] = True

        if target.id == "fireplace":
            return ActionResult(
                True,
                "You use the matches to light the dry wood in the fireplace. Flames leap upward and warm the whole kitchen.",
                state_changed=True,
            )

        if target.id == "candlestick":
            return ActionResult(
                True,
                "You light the candle in the candlestick. A soft glow spreads around you.",
                state_changed=True,
            )

        return ActionResult(
            True,
            f"You light the {target.name}. It gives off a steady glow.",
            state_changed=True,
        )

    def handle_unlock(self, command: ParsedCommand) -> ActionResult:
        """Unlock a valid target."""
        if not command.target:
            return ActionResult(False, "What do you want to unlock?")

        target = self.world.find_item_by_name(command.target)
        if not target:
            room = self.world.get_room(command.target)
            if room and room.locked:
                if room.lock_key and room.lock_key in self.world.inventory:
                    return self._unlock_storage()

        if not target:
            return ActionResult(False, f"You do not see any '{command.target}' here.")

        if target.id == "sealed_door":
            if "complete_key" in self.world.inventory:
                self.world.flags["door_unlocked"] = True
                target.state["locked"] = False
                return ActionResult(
                    True,
                    "You use the Key of Awakening to break the seal. The door can now be opened.",
                    state_changed=True,
                )
            return ActionResult(
                False,
                "Ordinary keys will not open this magical seal. You need the special key.",
            )

        return ActionResult(False, f"You cannot unlock the {target.name}.")

    def _unlock_storage(self) -> ActionResult:
        """Unlock the storage room door."""
        storage = self.world.get_room("storage")
        small_key = self.world.get_item("small_key")

        if not small_key or small_key.id not in self.world.inventory:
            return ActionResult(False, "You do not have the correct key.")

        if storage:
            storage.locked = False
            return ActionResult(
                True,
                "You unlock the storage room door with the small key. It clicks open.",
                state_changed=True,
            )

        return ActionResult(False, "Something went wrong while trying to unlock the door.")

    def handle_read(self, command: ParsedCommand) -> ActionResult:
        """Read written material."""
        if not command.target:
            return ActionResult(False, "What do you want to read?")

        item = self.world.find_item_by_name(command.target)
        if not item:
            return ActionResult(False, f"You do not see any '{command.target}' here.")

        if item.id == "scroll":
            item.state["read"] = True
            return ActionResult(
                True,
                "You unroll the scroll and read:\n\n'The bell tower sounds three times as the sun falls into the west.\nRemember this number, for it opens the road to the secret.'\n\nBelow the text, someone sketched a chest and wrote the number '3' beside it.",
                state_changed=True,
            )

        if item.id == "diary":
            item.state["read"] = True
            return ActionResult(
                True,
                """You open the diary and one page immediately catches your eye:

'Day 147
The experiment has failed again. The dream of eternal life was only a mirage.
I have divided the work of my life, the Key of Awakening, into three fragments and hidden them in different places.
The first lies at the highest point, guarded by numbers.
The second waits among the clutter to be discovered.
The third rests in the deepest darkness, where rust must be loosened.
Only by gathering all three pieces can the seal be broken and this place be escaped.

If anyone ever reads this, I hope you travel farther than I did.
                                    - Moriarty'""",
                state_changed=True,
            )

        return ActionResult(False, f"There is nothing readable on the {item.name}.")

    def handle_combine(self, command: ParsedCommand) -> ActionResult:
        """Combine the three key fragments into the final key."""
        fragments = ["key_fragment_a", "key_fragment_b", "key_fragment_c"]
        owned_fragments = [fragment for fragment in fragments if fragment in self.world.inventory]

        if len(owned_fragments) < 3:
            missing = 3 - len(owned_fragments)
            if len(owned_fragments) == 0:
                return ActionResult(False, "You do not have any key fragments to combine.")
            return ActionResult(
                False,
                f"You still need {missing} more key fragment(s) before you can assemble the key.",
            )

        for fragment_id in fragments:
            if fragment_id in self.world.inventory:
                self.world.inventory.remove(fragment_id)
            fragment = self.world.get_item(fragment_id)
            if fragment:
                fragment.location = None
                fragment.hidden = True

        complete_key = self.world.get_item("complete_key")
        if complete_key:
            complete_key.hidden = False
            complete_key.location = "inventory"
            self.world.inventory.append("complete_key")

        self.world.flags["key_assembled"] = True
        return ActionResult(
            True,
            "You fit the three fragments together. As the last piece clicks into place, blue, green, and red light surge across the metal and fuse into a single ornate key: the Key of Awakening.\n\nA strange power hums in your hands. This must be what opens the sealed door in the hall.",
            state_changed=True,
        )

    def handle_climb(self, command: ParsedCommand) -> ActionResult:
        """Climb when the environment allows it."""
        if self.world.current_room == "library":
            if self.world.flags.get("ladder_placed"):
                return self.handle_go(ParsedCommand(action="go", target="up"))
            return ActionResult(
                False,
                "The trapdoor is too high to reach. You need to set up something to climb first.",
            )

        return ActionResult(False, "There is nothing here to climb.")

    def handle_oil(self, command: ParsedCommand) -> ActionResult:
        """Use oil on a rusty mechanism."""
        if not command.target:
            return ActionResult(False, "What do you want to oil?")

        target = self.world.find_item_by_name(command.target)
        if not target:
            return ActionResult(False, f"You do not see any '{command.target}' here.")

        if target.id != "iron_door":
            return ActionResult(False, f"The {target.name} does not need oil.")

        oil_lamp = self.world.get_item("oil_lamp")
        if not oil_lamp or oil_lamp.id not in self.world.inventory:
            return ActionResult(
                False,
                "You do not have any oil to use. The oil lamp might help.",
            )

        if not oil_lamp.state.get("has_oil"):
            return ActionResult(False, "The oil lamp is empty.")

        target.state["rusted"] = False
        oil_lamp.state["has_oil"] = False
        return ActionResult(
            True,
            "You carefully pour oil from the lamp into the iron door's rusted lock. The mechanism loosens, and the door should open now.",
            state_changed=True,
        )

    def handle_enter(self, command: ParsedCommand) -> ActionResult:
        """Enter a numeric password."""
        password = command.parameters.get("password") or command.target
        if not password:
            return ActionResult(False, "Enter a number using: enter [number]")

        if self.world.current_room != "attic":
            return ActionResult(False, "There is nothing here that needs a code.")

        old_chest = self.world.get_item("old_chest")
        if not old_chest or not old_chest.is_locked():
            return ActionResult(False, "There is nothing here that needs a code.")

        correct_password = old_chest.state.get("password", "3")
        if str(password) == str(correct_password):
            old_chest.state["locked"] = False
            old_chest.state["open"] = True

            key_fragment = self.world.get_item("key_fragment_a")
            if key_fragment:
                key_fragment.hidden = False

            return ActionResult(
                True,
                "With a soft click, the numeric lock opens. You lift the lid and find a blue-glowing metal shard resting at the bottom of the chest.",
                state_changed=True,
            )

        return ActionResult(False, "The code is incorrect. The lock does not move.")

    def handle_help(self, command: ParsedCommand) -> ActionResult:
        """Show the command help text."""
        help_text = """
[Command Help]

Movement:
  go/move + direction   - Move north, south, east, west, up, or down
  go/move + room name   - Move toward a connected room

Observation:
  look                  - Look around the current room
  examine/x + item      - Inspect an item closely

Items:
  take/pick up + item   - Pick up an item
  drop + item           - Drop an item
  inventory/i           - Check your inventory

Interaction:
  open + item           - Open a container or door
  close + item          - Close a container
  use + item            - Use an item
  use + item + on + target - Use an item on a target
  read + item           - Read written text
  light + item          - Light an item
  combine               - Assemble the key fragments
  enter + number        - Enter a numeric code

Other:
  help                  - Show this help text

[Goal]
Find the three key fragments, assemble the Key of Awakening, and open the sealed door to escape the castle.
"""
        return ActionResult(True, help_text)

    def handle_empty(self, command: ParsedCommand) -> ActionResult:
        """Handle empty input."""
        return ActionResult(False, "Enter a command. Type 'help' to see the available commands.")

    def handle_unknown(self, command: ParsedCommand) -> ActionResult:
        """Handle an unrecognized command."""
        verb = command.parameters.get("verb", command.raw_input)
        return ActionResult(False, f"I do not understand '{verb}'. Type 'help' for the command list.")

    def _describe_room(self, room) -> str:
        """Build a room description with visible items and exits."""
        if room.dark and not self.world.has_light_source():
            return f"[{room.name}]\n\n{room.dark_description}"

        dynamic_desc = self.world.get_dynamic_room_description(room.id)
        description = f"[{room.name}]\n\n{dynamic_desc}"

        portable_items = [
            item
            for item in self.world.get_items_in_room(room.id)
            if item.portable and not item.hidden
        ]
        interactable_items = [
            item
            for item in self.world.get_items_in_room(room.id)
            if not item.portable and not item.hidden
        ]

        if portable_items:
            item_names = [f"'{item.name}'" for item in portable_items]
            description += f"\n\nYou notice: {', '.join(item_names)}"

        if interactable_items:
            item_names = [f'"{item.name}"' for item in interactable_items]
            description += f"\n\nYou could interact with: {', '.join(item_names)}"

        if room.exits:
            exit_str = ", ".join(room.exits.keys())
            description += f"\n\nVisible exits: {exit_str}"

        return description
