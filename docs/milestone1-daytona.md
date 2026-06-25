# Milestone 1: Harbor + Daytona Remote Sandbox Baseline

Milestone 1 runs GBQA as a Harbor-compatible benchmark on a remote Daytona sandbox. Local Docker is not the default acceptance path for this milestone.

## Runtime Model

- Harbor owns task packaging, trial execution, verifier execution, and artifact layout.
- Daytona owns the validated M1 remote sandbox lifecycle through Harbor's `daytona` environment provider. Modal is also supported through Harbor's `modal` provider as a parallel remote sandbox option, but Daytona remains the recorded M1 smoke baseline.
- `GBQAHarborAgent` is a Harbor custom agent wrapper that uploads the current GBQA runtime into `/sandbox`, starts Dark Castle from `/sandbox/software/dark-castle`, runs the QA loop, and exports stable artifacts under Harbor's `/logs` contract.
- The first instances live under `gbqa/tasks/dark-castle-*`; their shared software environment is downloaded from the real GitHub release archive for `Tsumugii24/dark-castle`.

## Configuration Boundaries

- `agent/config.toml` is harness policy only: model sampling, loop budgets, memory, operator retry, and current QA-agent backend defaults.
- Each instance `gbqa.yaml` is the source of truth: software source release, service endpoints, interaction modes, selected target-bug hint, weak/medium/strong hint variants, artifact contract, and agent-facing task profile.
- `gbqa.protocol` defines the stable QA output schema consumed by verifiers, independent of which agent harness produced the artifacts.
- `gbqa.reporting` converts harness-specific outputs into `run.json`, `issue.json`, `bugs.json`, `steps.jsonl`, and artifact files.

Harness config is resolved with explicit precedence: CLI overrides, trial/run
config, task package `gbqa.yaml`, repo harness defaults, then built-in
defaults. The redacted final resolved config and layer provenance are exported
under `run_spec.config` for reproducible runs.

GBQA interaction profiles are harness-side execution presets:

- `terminal`: use only terminal-oriented interaction through task metadata surfaces such as HTTP API, CLI, shell, or Python API.
- `browser`: use only the browser interaction mode.
- `computer`: use only the GUI computer interaction mode.
- `default`: enable every mode declared by the task metadata and use `run.interaction_mode` as the primary mode when configured, otherwise falling back to the task's default interaction mode.

In `default`, the planner sees explicit mode tools such as `terminal_action`, `browser_action`, and `computer_action` so it can choose the interaction path per step.

GBQA harness modes are a separate capability setting:

- `minimal`: keep the smallest targeted-QA harness that can explore a real sandbox software environment, inspect source code for function-level pinpointing, manage lifecycle tools, and export reports/traces/verifier artifacts. This mode keeps log tools, automatic log analysis, and worker subagents disabled.
- `full`: enable heavier diagnostic and augmentation capabilities such as log tools, automatic code/log diagnostic policies, and isolated worker subagents.

Full mode worker subagents keep expensive or context-polluting QA side tasks
outside the main planner context:

- `ExplorerAgent`: state coverage and frontier suggestions.
- `ReproducerAgent`: reproduction plans for new hypotheses.
- `LogAnalystAgent`: compressed evidence from runtime/trajectory logs.
- `CodeLocalizerAgent`: likely source files or symbols from code-search output.

The main planner receives only the short `subagent_summary`; worker prompts and
raw outputs stay out of run metadata unless explicitly enabled by policy.

Hooks are lifecycle callbacks used for stable harness observability. They write
`type="hook"` rows into `trace.jsonl` with labels such as `Explored`, `Ran`,
`Edited`, `Lifecycle`, `Reported`, `Covered`, `Summarized`, and `Diagnosed`.
Minimal mode keeps observability hooks enabled while leaving diagnostic/context
enhancement hooks disabled; full mode enables diagnostic hook categories.

## Software Source

Dark Castle is treated as an external software repository, not as GBQA-local source code:

- Repository: `https://github.com/Tsumugii24/dark-castle`
- Latest fixed reference release: `v0.2.0`
- Sandbox baseline selected by policy `latest_minus_one`: `v0.1.0`
- Download archive: `https://github.com/Tsumugii24/dark-castle/archive/refs/tags/v0.1.0.tar.gz`

The Daytona environment Dockerfile downloads this archive into `/sandbox/software/dark-castle`. `GBQAHarborAgent.setup()` also validates that location and downloads the same release archive if the image was not prebuilt with it.

## Sandbox Layout

Inside the remote Daytona sandbox, GBQA uses `/sandbox` as its runtime workspace:

- `/sandbox/software/dark-castle`: downloaded target software environment
- `/sandbox/agent`: uploaded GBQA QA agent harness
- `/sandbox/gbqa`: uploaded GBQA platform package
- `/sandbox/runtime/config.toml`: rendered run config for the current trial

Harbor's standard artifact paths stay unchanged:

- `/logs/agent/gbqa`: normalized GBQA agent outputs
- `/logs/verifier`: Harbor reward outputs
- `/logs/artifacts`: additional collected artifacts when configured

## Required Environment

Create a root `.env` from the single template:

```bash
cp .env.example .env
```

Fill in `DAYTONA_API_KEY`, `API_KEY`, and `MODEL_NAME` for the Daytona path. For Modal runs, authenticate once with `modal token new` or set `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`. `BASE_URL` defaults to ZenMux's OpenAI-compatible endpoint, `https://zenmux.ai/api/v1`, and can be overridden when needed. The model request configuration is intentionally provider-neutral and does not use `OPENAI_*` env names.

GBQA declares `modal[api-proxy-support]` in its Python dependencies. Keep that
extra installed on machines with host proxy variables such as `HTTP_PROXY` or
`HTTPS_PROXY`; Modal's API client needs `python-socks` before it can create the
remote sandbox through a proxy.

Use `python -m gbqa.cli.harbor_run ...` or the installed `gbqa-harbor ...` command so Harbor, Daytona, and the GBQA agent all inherit the repository-root `.env`. Direct `harbor run ...` still works only if those variables are already exported in the shell.

## Commands

Oracle verifier pass:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  -a oracle
```

Use the GBQA wrapper for oracle runs. The wrapper creates a temporary task
overlay that packages the current GBQA verifier code into `solution/gbqa`, so
Harbor's built-in oracle agent can upload it with `/solution`. Direct
`harbor run -a oracle` does not perform this GBQA packaging step.

Terminal mode:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal
```

Modal terminal mode uses the same task package and GBQA harness; only the Harbor
environment provider changes:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e modal \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal
```

Use `--ak max_steps=10` for a fast infrastructure smoke. Use a larger budget
such as `--ak max_steps=50` when checking whether the agent can reach the hinted
target bug and produce an issue report with function-level pinpointing. The
default `minimal` harness includes source inspection tools for this targeted
reward; use `--ak harness_mode=full` only when the smoke should also exercise
logs, automatic diagnostics, and worker subagents.

Browser mode:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=browser
```

Harbor built-in Codex and Claude Code task runners can also be selected through
the same wrapper:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  --gbqa-task-runner codex \
  --gbqa-agent-model gpt-5 \
  --gbqa-agent-auth subscription \
  --gbqa-codex-auth-file "$HOME/.codex/auth.json"
```

## Expected Artifacts

The agent writes stable GBQA artifacts under `/logs/agent/gbqa`:

- `run.json`
- `issue.json` — preferred single issue report for the hinted target bug, with
  `report_status`, `exit_status`, and `missing_fields`
- `bugs.json` — legacy single-element compatibility report
- `steps.jsonl`
- `trace.jsonl` when available
- `report.md` when available
- `artifacts/` for screenshots and other interaction files

The verifier writes Harbor-compatible outputs under `/logs/verifier`:

- `reward.txt`
- `reward.json`
- `gbqa_result.json`

## Non-Goals

- Local Docker is not the M1 default or acceptance path.
- Cua is not integrated in M1.
- Windows and macOS computer-use are not part of M1.
- GBQA does not implement its own Harbor replacement for jobs, trials, datasets, or providers in M1.
