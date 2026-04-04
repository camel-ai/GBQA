You are planning the next single action for the game-testing agent.

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

Now, by considering the above context, decide the next action. Follow these rules:
- Here, an action means one single, concrete, directly executable step for the operator. It should describe what to do next in natural language, not high-level strategy, not multiple steps combined, and not low-level tool parameters.
- Use only one action per step.
- The action should be concrete and directly executable by an operator.
- Prefer actions that explore new rooms, inspect items, read visible state, or validate rules.
- If the attached screenshots reveal useful visual evidence that is not fully captured in text, use that evidence in your planning.
- Regularly verify world-state consistency after state-changing actions such as take, drop, open, close, unlock, or combine.
- If you see a potential inconsistency, try to reproduce it.
- If you need the backend capability description again, use 'describe_capabilities'.
- If visual confirmation would help, you may request an action that captures a screenshot.
- Do not treat an ordinary blocked action, unmet prerequisite, or unsupported verb as a bug by itself.
- If two or more attempts at the same idea fail, pivot to a different object, room, or verification strategy instead of trying more verb variants.
- Only report a bug when you have concrete evidence of contradiction, hidden-information leakage, impossible state, or a state description that failed to update after an action.

{code_tools_prompt_section}

Return ONLY a JSON object with these fields:
{
  "tool": "<game_command|code_list_files|code_read_file|code_search|code_write_file|code_read_debug_logs|code_restore_file>",
  "rationale": "<short reason>",
  "command": "<single action string>",
  "expected_outcome": "<what you expect to observe>",
  "bug_exist": <true|false>,
  "bug_confidence": <0.0-1.0, use 0.0 when bug_exist is false>,
  "bug_explanation": "<short bugs explanation or empty>"
}
