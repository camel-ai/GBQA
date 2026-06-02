## Reintegrating Codebase Debugging v3 for Sandbox Environments

This PR is a modern replacement for PR #1, integrating codebase reading and white-box debugging capabilities into the new Harbor/Daytona architecture.

### 1. Summary of Changes
- **Universal Codebase Access:** Introduced `UniversalCodebaseAdapter` which abstracts codebase operations. 
    - In **API mode**, it uses standard HTTP endpoints.
    - In **Sandbox mode (CUA/Daytona)**, it interacts directly with the container's filesystem using `find`, `cat`, and `grep` via the execution backend.
- **Automated Root-Cause Analysis:** Orchestrator now auto-triggers `_auto_code_lookup` when `BugDetector` reports a high-confidence environment issue. It searches for relevant handlers in the source code to provide context to the Agent.
- **White-box Debugging 2.0:** Re-enabled the ability to inject diagnostic `print()` statements. Includes a robust **backup and restore** mechanism that ensures source files are reverted after the debugging session.

### 2. Testing & Verification
We moved beyond unit tests to real-world cloud sandbox validation.

**Unit Tests (PASSED):**
- Verified path normalization inside sandboxes.
- Verified file backup logic and multi-line Heredoc writing.
```text
agent/test/test_codebase_debugging_v3.py::test_universal_adapter_shell_list PASSED
agent/test/test_codebase_debugging_v3.py::test_universal_adapter_shell_read PASSED
agent/test/test_codebase_debugging_v3.py::test_universal_adapter_shell_write_with_backup PASSED
```

**Real Daytona Run:**
- Executed `gbqa-harbor run -e daytona` with `dark-castle`.
- Confirmed that the `code_read_file` and `code_search` tools are correctly registered and visible to the LLM agent during the live session.

### 3. Usage Guide
**Configuration:**
Code tools are **automatically enabled** when running in CUA or Daytona sandboxes. No extra config is required. For API-only environments, enable via `config.yaml`:
```yaml
interaction:
  adapters:
    code:
      enabled: true
      base_url: "http://your-backend/api"
```

**Manual Tools:**
- `code_read_file`: View source code.
- `code_search`: Regex search across the hub codebase.
- `code_write_file`: Temporarily modify code for debugging.
- `code_restore_file`: Revert changes.

Ready for review!
