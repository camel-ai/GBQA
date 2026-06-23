# Harbor Codex And Claude Code Task Runners

GBQA has one subscription-auth integration surface: task-running agents selected
in the Harbor agent phase. The verifier is rule-based and does not use an LLM
judge.

The default `GBQAHarborAgent` runs the custom QA harness and uses
provider-neutral `API_KEY`, `BASE_URL`, and `MODEL_NAME`. Codex and Claude Code
subscription auth is available when the run uses Harbor's built-in `codex` or
`claude-code` agents.

## Control Surfaces

GBQA's wrapper accepts native Harbor flags and GBQA convenience selectors. The
selectors compile to Harbor flags before `harbor run` is executed.

| Surface | GBQA selector | Harbor-native result |
|---|---|---|
| Custom QA harness | `--gbqa-task-runner gbqa` | `--agent-import-path gbqa.harbor.agent:GBQAHarborAgent` |
| Codex task runner | `--gbqa-task-runner codex` | `-a codex` |
| Claude Code task runner | `--gbqa-task-runner claude-code` | `-a claude-code` |
| Task runner model | `--gbqa-agent-model <model>` | `-m <model>` |
| Task runner auth mode | `--gbqa-agent-auth auto|api_key|subscription` | `--ae KEY=VALUE` where needed |
| Codex auth file | `--gbqa-codex-auth-file <path>` | `--ae CODEX_AUTH_JSON_PATH=<path>` |

Native Harbor flags still work. For example, `-a codex`, `-a claude-code`,
`--agent-import-path`, and `--ae` can be passed directly.

## GBQA Custom Harness

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal \
  --ak max_steps=10
```

This path runs `GBQAHarborAgent` and the GBQA QA loop. It does not use Codex or
Claude Code subscription auth.

## Claude Code Task Runner

Generate an OAuth token on a machine where browser login can complete:

```bash
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN="claude_oauth_..."
```

Run the instance with Harbor's built-in Claude Code agent:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  --gbqa-task-runner claude-code \
  --gbqa-agent-model anthropic/claude-sonnet-4-6 \
  --gbqa-agent-auth subscription
```

The wrapper emits `--ae CLAUDE_CODE_OAUTH_TOKEN=...` and
`--ae CLAUDE_FORCE_OAUTH=1` when subscription auth is selected.

## Codex Task Runner

Log in locally first:

```bash
codex login
```

Run the instance with Harbor's built-in Codex agent:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  --gbqa-task-runner codex \
  --gbqa-agent-model gpt-5 \
  --gbqa-agent-auth subscription \
  --gbqa-codex-auth-file "$HOME/.codex/auth.json"
```

The wrapper emits `--ae CODEX_AUTH_JSON_PATH=...`; Harbor uploads that file into
the agent sandbox. If no explicit path is provided and subscription auth is
requested, GBQA first checks the default host `~/.codex/auth.json`; if no file
is readable, it emits `--ae CODEX_FORCE_AUTH_JSON=1`, allowing Harbor's Codex
agent to resolve the auth file. Set `CODEX_FORCE_API_KEY=1` or
`--gbqa-agent-auth api_key` to force API-key mode instead.

## Current Caveats

- `GBQAHarborAgent` is not a Codex or Claude Code wrapper. It is the custom QA
  harness and uses provider-neutral API settings.
- Generic Harbor CLI agents must follow the instance instruction and write
  `/logs/agent/gbqa/issue.json`; otherwise the verifier falls back to a legacy
  `bugs.json` or an empty report.
