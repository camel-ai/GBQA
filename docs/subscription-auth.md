# Harbor Codex And Claude Code Integration

GBQA has two independent integration surfaces:

1. Task-running agents, selected in the Harbor agent phase.
2. Evaluation judges, selected in the verifier / RewardKit phase.

These surfaces are intentionally separate. The default `GBQAHarborAgent` runs
the custom QA harness and still uses provider-neutral `API_KEY`, `BASE_URL`, and
`MODEL_NAME`. Codex and Claude Code subscription auth is available when the run
uses Harbor's built-in `codex` or `claude-code` agents, or when RewardKit uses
those names as agent judges.

Harbor documents built-in agent selection through `--agent` / `-a`. Current
Harbor releases register `codex` and `claude-code` as built-in agents.

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
| Verifier judge | `--gbqa-judge <judge>` | `--ve REWARDKIT_JUDGE=<judge>` |
| Verifier judge model | `--gbqa-judge-model <model>` | `--ve REWARDKIT_MODEL=<model>` |
| Verifier judge auth mode | `--gbqa-judge-auth auto|api_key|subscription` | `--ve KEY=VALUE` where needed |
| Codex auth file | `--gbqa-codex-auth-file <path>` | Agent: `CODEX_AUTH_JSON_PATH`; verifier: `CODEX_AUTH_JSON_B64` |

Native Harbor flags still work. For example, `-a codex`, `-a claude-code`,
`--agent-import-path`, `--ae`, and `--ve` can be passed directly.

## Task-Running With Subscription Agents

### GBQA Custom Harness

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal \
  --ak max_steps=10
```

This path runs `GBQAHarborAgent` and the GBQA QA loop. It does not use Codex or
Claude Code subscription auth.

### Claude Code Task Runner

Generate an OAuth token on a machine where browser login can complete:

```bash
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN="claude_oauth_..."
```

Run the task with Harbor's built-in Claude Code agent:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner claude-code \
  --gbqa-agent-model anthropic/claude-sonnet-4-6 \
  --gbqa-agent-auth subscription
```

The wrapper emits `--ae CLAUDE_CODE_OAUTH_TOKEN=...` and
`--ae CLAUDE_FORCE_OAUTH=1` when subscription auth is selected.

### Codex Task Runner

Log in locally first:

```bash
codex login
```

Run the task with Harbor's built-in Codex agent:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
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

## Verifier / Evaluation With Subscription Judges

RewardKit reads `REWARDKIT_JUDGE` at runtime. If the value is a known agent
judge such as `claude-code` or `codex`, RewardKit shells out to that CLI instead
of using a standard API LLM judge.

GBQA's default reward is value-based and is computed by programmatic verifier
criteria. Subscription-backed judges are used for optional value-evaluation
review dimensions, such as generated-test reasonableness and value-rubric
alignment, rather than closed-oracle recall/precision matching.

### API-Key Judge

```bash
export REWARDKIT_JUDGE=openai/gpt-4o
export OPENAI_API_KEY="..."
export OPENAI_API_BASE="https://zenmux.ai/api/v1"
```

### Claude Code Judge

```bash
export CLAUDE_CODE_OAUTH_TOKEN="claude_oauth_..."
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --gbqa-judge claude-code \
  --gbqa-judge-model claude-opus-4-7 \
  --gbqa-judge-auth subscription
```

### Codex Judge

For remote verifier containers, pass Codex auth as base64 or let the wrapper
encode a local auth file. If `CODEX_ACCESS_TOKEN` is set, the wrapper passes
that token instead and enables `REWARDKIT_FORCE_OAUTH=1`.

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --gbqa-judge codex \
  --gbqa-judge-model gpt-5.5 \
  --gbqa-judge-auth subscription \
  --gbqa-codex-auth-file "$HOME/.codex/auth.json"
```

Equivalent manual env form:

```bash
export REWARDKIT_JUDGE=codex
export REWARDKIT_MODEL=gpt-5.5
export CODEX_AUTH_JSON_B64="$(base64 -w0 ~/.codex/auth.json)"
```

To force API-key judging with Codex, set:

```bash
export CODEX_FORCE_API_KEY=1
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://zenmux.ai/api/v1"
```

For PowerShell:

```powershell
$env:REWARDKIT_JUDGE = "codex"
$env:REWARDKIT_MODEL = "gpt-5.5"
$bytes = [System.IO.File]::ReadAllBytes("$HOME\.codex\auth.json")
$env:CODEX_AUTH_JSON_B64 = [Convert]::ToBase64String($bytes)
```

## Cowork-Compatible Aliases

GBQA supports the Cowork-style judge aliases in verifier scripts:

```bash
export JUDGE_AGENT=claude-code
export JUDGE_MODEL=claude-opus-4-7
```

```bash
export JUDGE_AGENT=codex
export JUDGE_CODEX_MODEL=gpt-5.5
```

`REWARDKIT_JUDGE` and `REWARDKIT_MODEL` remain the canonical GBQA / RewardKit
names. If both canonical and alias values are explicitly set, the canonical
values should be treated as the source of truth.

## Current Caveats

- `GBQAHarborAgent` is not a Codex or Claude Code wrapper. It is the custom QA
  harness and uses provider-neutral API settings.
- GBQA does not currently rotate refreshed Codex auth files back from remote
  Daytona verifier containers after a run.
- Generic Harbor CLI agents must follow the task instruction and write
  `/logs/agent/gbqa/bugs.json`; otherwise the verifier falls back to an empty
  bug list. Each reported bug should include `evidence.expected_behavior`,
  `evidence.observed_fault`, and `evidence.minimal_reproduction`.
