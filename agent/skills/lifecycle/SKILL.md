---
name: lifecycle
description: Task and session lifecycle control for multi-session QA exploration within one task.
---

# Lifecycle

This skill is activated by default at run start. The harness records `start_task`
and `start_session` automatically when a task begins. Use the tools below when
you need finer-grained control over sessions during the same task.

## System Events (harness-only)

These are recorded in `lifecycle_events` but are **not** planner tools:

- `start_task`: emitted once when the run loop begins.
- `start_session`: emitted when the harness opens the first session.

## Session Management Tools

- `start_session`: Open a new session and make it the active session. Does not
  close any already-open sessions.
- `end_session`: Close one session only. Use `session_id` to close a specific
  open session, or provide a reason alone to close the active session.
- `new_session`: Open a fresh session and make it active, regardless of whether
  other sessions are already open. Does not close existing sessions.
- `refresh_session`: Refresh capability metadata for a specific `session_id`.
  Use after environment resets or UI/tool changes in that session.
- `switch_session`: Change the active session to an already-open `session_id`.
- `list_sessions`: List the current `active_session_id` and all `open_session_ids`.

`start_session` and `new_session` echo the new `session_id` plus the current
open-session list in their observation. Use `list_sessions` whenever you need to
re-check IDs before `switch_session`, `refresh_session`, or a targeted
`end_session`.

## Task Completion

- `end_task`: Finish the current QA task and stop the interaction loop when
  enough evidence has been collected. In targeted GBQA tasks, task exit runs a
  final fixed-format issue-report pass, so the reason should briefly identify
  the reproduced bug and localization evidence.

## Action Formats

- `start_session`: short reason for opening a session
- `end_session`: `session_id` or `session_id reason`, or a reason alone to end
  the active session
- `new_session`: short reason for opening a fresh session
- `refresh_session`: `session_id`
- `switch_session`: `session_id`
- `list_sessions`: any non-empty text (ignored)
- `end_task`: short reason for finishing the task

## Best Practices

1. Prefer `new_session` when you want a clean exploration path without closing
   older sessions you may still inspect later.
2. Use `end_session` when a session is no longer needed and should release its
   resources.
3. Use `list_sessions` before switching, refreshing, or closing a specific
   session when you are unsure of the current IDs.
4. Use `switch_session` to alternate between multiple open sessions instead of
   reopening the environment repeatedly.
5. Use `refresh_session` after in-session resets that change available tools or
   UI state.
6. Call `end_task` only after you have enough reproduction and localization
   evidence for the final issue report.
