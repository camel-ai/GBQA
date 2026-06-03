---
name: code
description: Codebase reading and white-box debugging capabilities.
---

# Codebase Debugging Skill

This skill grants the agent the ability to inspect the target software's source code and perform white-box debugging via temporary code injection.

## 🛠 Tools
- `code_list_files`: Discover the structure of the hub codebase.
- `code_read_file`: Read source code to understand logic or identify bugs.
- `code_search`: Search for keywords or patterns across the entire codebase.
- `code_write_file`: Inject `print()` statements or temporary fixes to diagnose complex issues.
- `code_restore_file`: Revert any modifications made during debugging.

## 📖 Best Practices
1. **Explore First**: Always start with `code_list_files` or `code_search` to find relevant handlers.
2. **Safe Debugging**: Before using `code_write_file`, ensure you have a plan to use `code_restore_file`.
3. **White-box Inspection**: When an environment error is ambiguous, search for the error message in the codebase to find where it's raised.
4. **Injection**: Use `print()` to trace variable states in the sandbox. Logs can be read via `log_analyze`.

## ⚠️ Safety
- Never modify files permanently. Always restore files before concluding the session.
- Only use these tools within the `/sandbox/software` directory (handled automatically).
