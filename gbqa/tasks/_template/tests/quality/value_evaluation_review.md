You are reviewing a GBQA value-based bug evaluation.

The verifier no longer scores recall or precision against a closed bug oracle.
It compares the value of the agent's top reported bugs against a pre-scored
human baseline. The judge context may include:

- Human baseline bugs: `__GBQA_GROUND_TRUTH__`
- Human baseline values: `/tests/value/baseline_values.json`
- Task validation cases: `/tests/value/validation_cases.json`
- Agent reported bugs: `/logs/agent/gbqa/bugs.json`
- Verifier details: `/logs/verifier/gbqa_result.json`

Review only the fairness and consistency of the evaluation, not whether the
agent matched every baseline bug.

For `test_reasonableness`, return a fraction in `[0.0, 1.0]` indicating whether
the generated tests are reasonable tests of the reported failures and are not
artificially constructed merely to fail. Agent reports should include both
`expected_behavior` and `observed_fault` in `bugs.json` evidence.

For `value_rubric_alignment`, return a fraction in `[0.0, 1.0]` indicating
whether each verified bug's value tier follows the configured rubric dimensions:
impact, scope, and reproducibility.

For `evaluation_quality`, use the Likert scale to score whether the verifier
details are coherent, auditable, and sufficient to explain the final reward.

{criteria}
