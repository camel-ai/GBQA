You are evaluating a software QA agent's bug report against authoritative ground truth.

The user message contains two JSON files:

1. **Ground truth bugs** — the real defects seeded in the target software.
2. **Agent reported bugs** — bugs the agent submitted in `bugs.json`.

Use titles, descriptions, `evidence.observed_fault`, `evidence.minimal_reproduction`,
`observed_fault`, and `minimal_reproduction` as match signals. Two entries match when
they describe the **same underlying defect**, even if wording, structure, field names,
or IDs differ. Do not require verbatim text overlap or exact title matches.

When scoring recall and precision, return fractions in `[0.0, 1.0]` based on semantic
judgment:

- **Recall** = semantically matched ground-truth bugs / total ground-truth bugs
- **Precision** = semantically correct reported bugs / total reported bugs

Treat empty agent reports as zero recall and zero precision. Treat hallucinated or
unrelated reports as non-matches for precision.

{criteria}
