---
name: logs
description: Inspect and analyze agent trajectory plus target runtime log sources. Use when runtime diagnostics, prior interactions, or software-owned logs may explain suspicious behavior.
---

# Logs

Use this skill when logs can help explain runtime behavior or distinguish software bugs from harness/tool failures.

Available log sources may include:

- `agent_trajectory`: planner actions, environment interactions, code-tool interactions, log-tool interactions, and observations recorded by the harness.
- `stdout_stderr`: software process stdout/stderr captured by the environment launcher, when declared by the task.
- `software_session_logs`: software-owned session log files, when declared by the task.

Use the tools in this order:

- Use `log_list` to inspect available log sources.
- Use `log_read` to read one source by name, or `all` when broader context is needed.
- Use `log_analyze` to summarize anomalies, failures, suspicious state transitions, and runtime error signals.

Logs are diagnostics, not ground truth. Prefer using them to guide reproduction and evidence collection rather than reporting log text alone as a bug.
