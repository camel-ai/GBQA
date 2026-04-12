You are planning the next single action for the game-testing agent.

## Game Profile:
{game_profile}

## Long-term Memory Summary:
{memory_summary}

## Recent Trace:
{recent_trace}

## Current Observation (most recent response message):
{current_observation}

## Current Artifacts:
{current_artifacts}

## Current Turn:
{turn}

Now, by considering the above context, decide the next step. Follow these rules:
- Choose exactly one tool from the available tools above.
- Provide exactly one `action` string for that chosen tool.
- The `action` must match the selected tool's required format exactly.
- Keep the chosen `action` concrete enough to be executed immediately, not just high-level strategy.
- Prefer actions that explore new rooms, inspect items, read visible state, or validate rules.
- If the attached screenshots reveal useful visual evidence that is not fully captured in text, use that evidence in your planning.
- Regularly verify world-state consistency after state-changing actions such as take, drop, open, close, unlock, or combine.
- If you see a potential inconsistency, try to reproduce it.
- Use only the capabilities and action formats explicitly described in the available-tools section below.
- If visual confirmation would help and a relevant tool is available, you may use it.
- Do not treat an ordinary blocked action, unmet prerequisite, or unsupported verb as a bug by itself.
- If two or more attempts at the same idea fail, pivot to a different object, room, or verification strategy instead of trying more verb variants.
- Only report a bug when you have concrete evidence of contradiction, hidden-information leakage, impossible state, or a state description that failed to update after an action.

{available_tools_prompt_section}

Return ONLY a JSON object with these fields:
{
  "tool": "<tool name from the available tools above>",
  "rationale": "<short reason>",
  "action": "<single action string>",
  "expected_outcome": "<what you expect to observe>",
  "bug_exist": <true|false>,
  "bug_confidence": <0.0-1.0, use 0.0 when bug_exist is false>,
  "bug_explanation": "<short bugs explanation or empty>"
}
