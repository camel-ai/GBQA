# Dark Castle QA Task

Investigate one known Dark Castle: Night of Awakening bug. Your goal is to use the hint below to reproduce and localize the issue, then write exactly one open-source-style issue report.

Hint:

Focus on item visibility after taking something from a hidden or contained state. Verify whether dropping that item into the room makes it visible again.

Write bug findings through the GBQA agent report artifacts. The verifier will
score the report as binary found/not found by checking whether your function-level
pinpoint aligns with the golden patch for the targeted bug.

If you are running as a generic Harbor CLI agent such as `claude-code` or
`codex`, the target source is available at `/sandbox/software/dark-castle`.
Start the backend yourself before interacting with it:

```bash
mkdir -p /logs/agent/gbqa /logs/runtime
cd /sandbox/software/dark-castle/backend
PORT=5000 /opt/venv/bin/python app.py > /logs/runtime/dark-castle-server.log 2>&1 &
```

Then use the terminal interaction surface exposed as the HTTP API at
`http://127.0.0.1:5000/api/agent`. Before finishing, write your findings to
`/logs/agent/gbqa/issue.json` using this shape:

```json
{
  "issue": {
    "title": "Short descriptive title",
    "description": "What goes wrong and why it is a bug.",
    "expected_behavior": "What correct behavior should look like.",
    "observed_fault": "The incorrect behavior you observed.",
    "reproduction": ["step 1", "step 2"],
    "pinpoint": {
      "file": "relative/path.py",
      "class": "ClassName if applicable",
      "function": "function_or_method_name",
      "line": 123
    },
    "root_cause": "Function-level explanation of the implementation defect."
  }
}
```

For backward compatibility, GBQA also accepts a single-element
`/logs/agent/gbqa/bugs.json`, but `issue.json` is preferred for this task.
The required semantic fields are:

- `observed_fault`
- `expected_behavior`
- `reproduction`
- `pinpoint` or `root_cause` with function-level localization

Do not report unrelated bugs. This task measures whether the hinted target bug
was found and localized.
