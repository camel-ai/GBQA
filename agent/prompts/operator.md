Translate the planner's single semantic action into a short sequence of normalized backend calls.

Rules:
- Do not change the planner's testing goal.
- Use only the supported call kinds and context exposed below.
- Keep the sequence short and directly executable.
- Prefer one call when possible.
- If the planner action is already an environment command and the backend is command-based, pass it through.
- If the operator context includes actionable elements with refs, use those refs for click/type calls.
- Do not invent selectors, coordinates, refs, or tool names that are not justified by the operator context.

## Planner Action:
{planner_action}

## Current Observation Summary:
{current_observation}

## Operator Context:
{operator_context}

Return ONLY a JSON object:
{
  "rationale": "<short translation reason>",
  "calls": [
    {
      "kind": "<normalized call kind>",
      "ref": "<optional element ref from operator context>",
      "target": "<target element or semantic target>",
      "text": "<optional input text>",
      "url": "<optional url>",
      "duration_ms": <optional non-negative integer>
    }
  ]
}
