# Dark Castle QA Task

Explore Dark Castle: Night of Awakening as a QA agent. Your goal is to discover real gameplay or state-consistency bugs and report each bug with enough evidence for reproduction.

Focus on:

- invalid state transitions
- descriptions that reveal hidden information too early
- inventory and room-state inconsistencies
- mismatches between text feedback and backend state

Write bug findings through the GBQA agent report artifacts. The verifier will compare your reported bugs against the task ground truth.

If you are running as a generic Harbor CLI agent such as `claude-code` or
`codex`, the target source is available at `/sandbox/software/dark-castle`.
Start the backend yourself before interacting with it:

```bash
mkdir -p /logs/agent/gbqa /logs/runtime
cd /sandbox/software/dark-castle/backend
PORT=5000 /opt/venv/bin/python app.py > /logs/runtime/dark-castle-server.log 2>&1 &
```

Then use the API at `http://127.0.0.1:5000/api/agent`. Before finishing, write
your findings to `/logs/agent/gbqa/bugs.json` using this shape:

```json
{
  "bugs": [
    {
      "title": "Short descriptive title",
      "description": "What goes wrong and why it is a bug.",
      "evidence": {
        "observed_fault": "The incorrect behavior you observed.",
        "minimal_reproduction": ["step 1", "step 2"]
      }
    }
  ]
}
```

After you have found several bugs, you should still try to reach the exit of the castle, instead of terminate.
