"""
Command parsing module.
Convert player input into structured commands the game engine can execute.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ParsedCommand:
    """Structured command produced by the parser."""

    action: str
    target: Optional[str] = None
    secondary_target: Optional[str] = None
    raw_input: str = ""
    parameters: Dict[str, Any] = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}


class CommandParser:
    """Natural-language command parser for the text adventure."""

    DIRECTION_ALIASES = {
        "n": "north",
        "north": "north",
        "s": "south",
        "south": "south",
        "e": "east",
        "east": "east",
        "w": "west",
        "west": "west",
        "u": "up",
        "up": "up",
        "d": "down",
        "down": "down",
    }

    ROOM_ALIASES = {
        "hall": "hall",
        "main hall": "hall",
        "entrance hall": "hall",
        "corridor": "corridor",
        "hallway": "corridor",
        "passage": "corridor",
        "library": "library",
        "study": "library",
        "attic": "attic",
        "loft": "attic",
        "bedroom": "bedroom",
        "bed room": "bedroom",
        "kitchen": "kitchen",
        "storage": "storage",
        "storage room": "storage",
        "storeroom": "storage",
        "basement": "basement",
        "cellar": "basement",
    }

    ACTION_PATTERNS = {
        "go": ["go", "move", "walk", "head", "travel", "proceed"],
        "look": ["look", "l", "observe", "see", "view"],
        "examine": ["examine", "x", "inspect", "check", "study", "look at"],
        "inventory": ["inventory", "inv", "i", "items", "bag", "backpack"],
        "take": ["take", "get", "grab", "pick", "pick up", "acquire", "collect"],
        "drop": ["drop", "put down", "discard", "leave", "release"],
        "put": ["put", "place", "insert", "put in", "put into", "place in"],
        "open": ["open", "open up"],
        "close": ["close", "shut", "close up"],
        "use": ["use", "apply", "utilize", "employ"],
        "light": ["light", "ignite", "kindle", "burn", "light up", "set fire"],
        "unlock": ["unlock", "unlock with"],
        "read": ["read", "peruse", "browse"],
        "combine": ["combine", "merge", "assemble", "join", "put together", "piece together"],
        "climb": ["climb", "climb up", "ascend", "scale"],
        "oil": ["oil", "lubricate", "grease"],
        "help": ["help", "h", "?", "commands", "hint"],
        "enter": ["enter", "input", "type", "dial"],
    }

    PREPOSITIONS = ["on", "with", "in", "into", "to", "at", "using", "inside"]

    def __init__(self):
        self.word_to_action = {}
        for action, words in self.ACTION_PATTERNS.items():
            for word in words:
                self.word_to_action[word.lower()] = action

    def parse(self, input_text: str) -> ParsedCommand:
        """Parse raw user input into a structured command."""
        raw_input = input_text
        text = input_text.strip().lower()

        if not text:
            return ParsedCommand(action="empty", raw_input=raw_input)

        if text in self.DIRECTION_ALIASES:
            return ParsedCommand(
                action="go",
                target=self.DIRECTION_ALIASES[text],
                raw_input=raw_input,
            )

        if text in self.ROOM_ALIASES:
            return ParsedCommand(
                action="go",
                target=self.ROOM_ALIASES[text],
                raw_input=raw_input,
            )

        tokens = self._tokenize(text)
        if not tokens:
            return ParsedCommand(action="empty", raw_input=raw_input)

        action, remaining_tokens = self._identify_action(tokens)
        if action == "unknown":
            return ParsedCommand(
                action="unknown",
                target=" ".join(tokens[1:]) if len(tokens) > 1 else None,
                raw_input=raw_input,
                parameters={"verb": tokens[0]},
            )

        target, secondary_target, params = self._parse_targets(remaining_tokens, action)
        return ParsedCommand(
            action=action,
            target=target,
            secondary_target=secondary_target,
            raw_input=raw_input,
            parameters=params,
        )

    def _tokenize(self, text: str) -> List[str]:
        """Split input into tokens."""
        return [token for token in text.split() if token]

    def _identify_action(self, tokens: List[str]) -> Tuple[str, List[str]]:
        """Identify the command verb."""
        if not tokens:
            return "empty", []

        if len(tokens) >= 2:
            two_word = f"{tokens[0]} {tokens[1]}"
            if two_word in self.word_to_action:
                return self.word_to_action[two_word], tokens[2:]

        if tokens[0] in self.word_to_action:
            return self.word_to_action[tokens[0]], tokens[1:]

        if tokens[0] in self.DIRECTION_ALIASES:
            return "go", tokens

        return "unknown", tokens

    def _parse_targets(
        self, tokens: List[str], action: str
    ) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
        """Parse the target objects associated with an action."""
        if not tokens:
            return None, None, {}

        params: Dict[str, Any] = {}

        if action == "go":
            target = " ".join(tokens)
            if target in self.DIRECTION_ALIASES:
                return self.DIRECTION_ALIASES[target], None, {}
            if target in self.ROOM_ALIASES:
                return self.ROOM_ALIASES[target], None, {}
            return target, None, {}

        if action == "enter":
            for token in tokens:
                if token.isdigit():
                    params["password"] = token
                    return None, None, params
            return " ".join(tokens), None, params

        prep_index = -1
        for index, token in enumerate(tokens):
            if token in self.PREPOSITIONS:
                prep_index = index
                break

        if prep_index > 0:
            primary = self._clean_target(" ".join(tokens[:prep_index]))
            secondary = self._clean_target(" ".join(tokens[prep_index + 1 :]))
            return primary, secondary if secondary else None, params

        target = self._clean_target(" ".join(tokens))
        return target if target else None, None, params

    def _clean_target(self, target: str) -> str:
        """Remove simple English articles from a target phrase."""
        articles = ["the", "a", "an", "some", "that", "this"]
        words = target.split()
        cleaned = [word for word in words if word.lower() not in articles]
        return " ".join(cleaned)

    def normalize_direction(self, direction: str) -> Optional[str]:
        """Normalize a direction alias to its canonical value."""
        return self.DIRECTION_ALIASES.get(direction.lower())

    def normalize_room(self, room: str) -> Optional[str]:
        """Normalize a room alias to its canonical room id."""
        return self.ROOM_ALIASES.get(room.lower())
