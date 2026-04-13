"""Quick prompt render test for QA Agent."""

from __future__ import annotations

import os
import sys
from typing import Dict

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.game_clients import DarkCastleGameClient
from src.prompts import PromptLoader, render_prompt


def _build_sample_context() -> Dict[str, str]:
    return {
        "game_profile": (
            "Text adventure in a mysterious castle. "
            "You can use 'new game' to start a new game and 'close game' to end a session."
        ),
        "capability_summary": "You can send one game command per step or ask for describe_capabilities.",
        "memory_summary": "- Found a locked door.\n- Collected a key fragment.",
        "recent_trace": (
            "Step 1: look -> You are in a hall.\n"
            "Step 2: take torch -> You picked up a torch."
        ),
        "current_observation": "A dark corridor lies ahead.",
        "current_artifacts": "",
        "execution_diagnostics": "{}",
        "turn": "2",
        "code_tools_prompt_section": """## White-box Debugging:
You have the ability to perform "White-box Debugging" by modifying the game's source code. This is a powerful method to gather information or verify internal logic:
- Use `code_write_file` to insert `print()` statements into handlers or logic checks.
- Use `code_read_debug_logs` to see the output of your `print()` statements after running a `game_command`.
- Use `code_restore_file` after debugging so the environment returns to its original state.
- Example: If you suspect a "take" condition is wrong, insert `print(f"DEBUG: can_take={result}")` in `actions.py`, run `take item`, and then check logs.
- Only use `code_write_file` with `path:old_text->new_text` or a valid JSON payload.
- Restore any temporary debug edits once you have gathered the needed information.

## Available Tools:
- game_command (default): Send a command to the game.
- code_list_files: List all source code files in the game.
- code_read_file: Read a source file. Format: `path` or `path:start-end`.
- code_search: Search for a pattern in source code.
- code_write_file: Modify a source file. Format: `path:old_text->new_text` (replaces first match) or use a full JSON string if overwriting.
- code_read_debug_logs: Read the captured `stdout/print` logs for the current game session. Put "read" or "clear" in command.
- code_restore_file: Restore a file previously modified with `code_write_file`. Put the file path in `command`.

Use code tools ONLY when you have a concrete hypothesis to verify via source code.
Do not speculatively browse code. Prefer gameplay-based verification first.""",
    }


def _build_live_context() -> Dict[str, str]:
    base_url = os.getenv("DARK_CASTLE_BASE_URL") or os.getenv(
        "CASTLE_BASE_URL", "http://localhost:5000/api/agent"
    )
    client = DarkCastleGameClient(base_url)
    data = client.new_game()
    game_id = data.get("game_id", "")
    intro = data.get("message", "")
    look = client.send_command(game_id, "look")
    message = look.get("message", "")
    turn = str(look.get("turn", 1))
    state_payload = client.get_state(game_id)
    state = state_payload.get("state", {}) if isinstance(state_payload, dict) else {}
    room = state.get("room", {}) if isinstance(state, dict) else {}
    room_name = room.get("name", "")
    exits = room.get("exits", [])
    exit_text = ", ".join(exits) if isinstance(exits, list) else ""
    inventory = state.get("inventory", [])
    inventory_count = len(inventory) if isinstance(inventory, list) else 0
    lit_items = []
    if isinstance(inventory, list):
        for item in inventory:
            if not isinstance(item, dict):
                continue
            item_state = item.get("state", {})
            if isinstance(item_state, dict) and item_state.get("lit") is True:
                lit_items.append(item.get("name", "unknown"))
    light_source_text = "on" if lit_items else "off"
    can_see = state.get("can_see", None)
    visibility_text = (
        "on" if can_see else "off" if can_see is not None else "unknown"
    )
    hud_text = (
        f"current room={room_name or 'unknown'}, "
        f"inventory load={inventory_count}/6, "
        f"current turn={turn}, "
        f"light_source={light_source_text}, "
        f"visibility={visibility_text}, "
        f"exits=[{exit_text}]"
    )
    combined_observation = (
        f"{intro or message}\n\n"
        f"{hud_text}"
    ).strip()
    return {
        "game_profile": (
            "Text adventure in a mysterious castle. "
            "You can use 'new game' to start a new game and 'close game' to end a session."
        ),
        "capability_summary": "You can send one game command per step or ask for describe_capabilities.",
        "memory_summary": "",
        "recent_trace": f"Step 1: look -> {message}",
        "current_observation": combined_observation,
        "current_artifacts": "",
        "execution_diagnostics": "{}",
        "turn": turn,
        "code_tools_prompt_section": _build_sample_context()["code_tools_prompt_section"],
    }


def _load_context() -> Dict[str, str]:
    if os.getenv("RUN_LIVE", "").lower() in {"1", "true", "yes"}:
        try:
            return _build_live_context()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] live context failed: {exc}")
    return _build_sample_context()


def main() -> None:
    prompt_dir = os.path.join("prompts")
    loader = PromptLoader(prompt_dir)
    prompts = loader.load_bundle()

    context = _load_context()

    system_prompt = render_prompt(prompts.system, context)
    planner_prompt = render_prompt(prompts.planner, context)
    reflection_vars = {
        "memory_summary": context["memory_summary"],
        "recent_trace": context["recent_trace"],
        "current_observation": context["current_observation"],
        "execution_diagnostics": context["execution_diagnostics"],
    }
    reflection_prompt = render_prompt(prompts.reflection, reflection_vars)
    summary_prompt = render_prompt(
        prompts.summary,
        {
            "trace": "Step 1: look -> You are in a hall.",
            "memory_summary": context["memory_summary"],
        },
    )

    print("Rendered system prompt:\n")
    print(system_prompt)
    print("\nRendered planner prompt:\n")
    print(planner_prompt)
    print("\nRendered reflection prompt:\n")
    print(reflection_prompt)
    print("\nRendered summary prompt:\n")
    print(summary_prompt)


if __name__ == "__main__":
    main()
