---
name: code
description: Inspect, search, and optionally modify target software source code for white-box debugging. Use when source inspection or controlled code edits may help explain or reproduce behavior.
---

# Code

Use this skill when white-box source-code inspection is useful for QA debugging.

Prefer read-only actions first:

- Use `code_list_files` to discover available source files.
- Use `code_search` to locate relevant symbols, routes, handlers, or state logic.
- Use `code_read_file` to inspect focused file ranges.

Only use mutation tools when explicitly needed for a controlled debugging experiment:

- Use `code_write_file` for temporary source edits.
- Use `code_restore_file` to undo files changed by `code_write_file`.

Do not treat source-code access as a substitute for runtime evidence. When reporting a bug, connect code observations to reproduced behavior or a concrete runtime contradiction.
