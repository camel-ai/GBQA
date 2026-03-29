Reflect on the latest action and observation. Identify:
- Any suspicious behavior or potential bugs.
- What evidence you have.
- The next verification step, if needed.
- A failed command alone is not enough evidence.
- Treat unmet prerequisites, parser limitations, and ordinary refusals as expected unless they contradict prior game text or state.
- Prefer next checks that reproduce a contradiction or verify a state-description mismatch.
- After repeated failures for the same hypothesis, suggest a substantively different next check rather than another synonym.

## Long-term Memory Summary:
{memory_summary}

## Recent Trace:
{recent_trace}

## Current Observation (most recent response message):
{current_observation}

Return ONLY a JSON object:
{
  "bug_exist": <true|false>,
  "bug_confidence": <0.0-1.0, use 0.0 when bug_exist is false>,
  "bug_evidence": "<short evidence summary or empty>",
  "next_check": "<next command suggestion>"
}
