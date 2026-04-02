You are planning the next single command to send to the game.

## Game Profile:
{game_profile}

## Long-term Memory Summary:
{memory_summary}

## Recent Trace:
{recent_trace}

## Current Observation (most recent response message):
{current_observation}

## Current Turn:
{turn}

Now, by considering the above context, decide the next command to send. Follow these rules:
- Use only one command per step.
- Prefer commands that explore new rooms, inspect items, or validate rules.
- Regularly verify world-state consistency after state-changing actions such as take, drop, open, close, unlock, or combine.
- If you see a potential inconsistency, try to reproduce it.
- If you don't know the Available Actions, always use 'help' command.
- Do not treat an ordinary blocked action, unmet prerequisite, or unsupported verb as a bug by itself.
- If two or more attempts at the same idea fail, pivot to a different object, room, or verification strategy instead of trying more verb variants.
- Only report a bug when you have concrete evidence of contradiction, hidden-information leakage, impossible state, or a state description that failed to update after an action.

## White-box Debugging:
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
- code_read_debug_logs: Read the captured `stdout/print` logs. Put "read" or "clear" in command.
- code_restore_file: Restore a file previously modified with `code_write_file`. Put the file path in `command`.

Use code tools ONLY when you have a concrete hypothesis to verify via source code.
Do not speculatively browse code. Prefer gameplay-based verification first.

Return ONLY a JSON object with these fields:
{
  "tool": "<game_command|code_list_files|code_read_file|code_search|code_write_file|code_read_debug_logs|code_restore_file>",
  "rationale": "<short reason>",
  "command": "<string>",
  "expected_outcome": "<what you expect to observe>",
  "bug_exist": <true|false>,
  "bug_confidence": <0.0-1.0, use 0.0 when bug_exist is false>,
  "bug_explanation": "<short bugs explanation or empty>"
}
