# Claude Code And Codex Subscription Auth

GBQA supports two distinct execution paths:

- The default `GBQAHarborAgent`, which runs the GBQA QA harness and uses
  provider-neutral `API_KEY`, `BASE_URL`, and `MODEL_NAME`.
- Harbor's built-in CLI agents (`claude-code` and `codex`), which can use the
  official Claude Code and Codex subscription authentication flows.

Harbor's public examples show the built-in agent shape:

```bash
harbor run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  -a claude-code \
  -m anthropic/claude-sonnet-4-6
```

See Harbor's docs:

- https://www.harborframework.com/docs/agents
- https://www.harborframework.com/docs/rewardkit

## Running The Task With Claude Code Subscription

Generate an OAuth token on a machine where the browser login can complete:

```bash
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN="claude_oauth_..."
```

Pass it to Harbor's built-in Claude Code agent:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  -a claude-code \
  -m anthropic/claude-sonnet-4-6 \
  --ae CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN
```

Claude Code authentication reference:

- https://code.claude.com/docs/en/authentication

## Running The Task With Codex Subscription

Log in locally first:

```bash
codex login
```

Then let Harbor's built-in Codex agent upload the local `auth.json`:

```bash
export CODEX_FORCE_AUTH_JSON=1
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  -a codex \
  -m gpt-5 \
  --ae CODEX_FORCE_AUTH_JSON=1
```

You can also pass an explicit file path:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  -a codex \
  -m gpt-5 \
  --ae CODEX_AUTH_JSON_PATH=$HOME/.codex/auth.json
```

Codex authentication reference:

- https://developers.openai.com/codex/auth

## Evaluating With Subscription-Backed Rewardkit Judges

`gbqa/tasks/dark-castle/tests/quality/quality.toml` can run as a standard LLM
judge or as a Rewardkit agent judge. To use Claude Code as the semantic matcher:

```bash
export REWARDKIT_JUDGE=claude-code
export CLAUDE_CODE_OAUTH_TOKEN="claude_oauth_..."
```

To use Codex as the semantic matcher inside the verifier container, pass a
portable base64-encoded `auth.json`. `tests/test.sh` writes this to
`CODEX_HOME/auth.json` before invoking Rewardkit.

```bash
export REWARDKIT_JUDGE=codex
export CODEX_AUTH_JSON_B64="$(base64 -w0 ~/.codex/auth.json)"
```

For PowerShell:

```powershell
$env:REWARDKIT_JUDGE = "codex"
$bytes = [System.IO.File]::ReadAllBytes("$HOME\.codex\auth.json")
$env:CODEX_AUTH_JSON_B64 = [Convert]::ToBase64String($bytes)
```

API-key based judge scoring remains supported:

```bash
export REWARDKIT_JUDGE=openai/gpt-4o
export OPENAI_API_KEY="..."
export OPENAI_API_BASE="https://zenmux.ai/api/v1"
```

## Artifact Contract For Generic CLI Agents

When using Harbor's generic CLI agents instead of `GBQAHarborAgent`, the task
instruction tells the agent to start the target service and write:

```text
/logs/agent/gbqa/bugs.json
```

The verifier reads that file and compares it with the ground truth. If the file
is missing, `tests/test.sh` falls back to `/tests/empty_bugs.json`, resulting in
zero recall.
