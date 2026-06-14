# Milestone 1: Harbor + Daytona Remote Sandbox Baseline

Milestone 1 runs GBQA as a Harbor-compatible benchmark on a remote Daytona sandbox. Local Docker is not the default acceptance path for this milestone.

## Runtime Model

- Harbor owns task packaging, trial execution, verifier execution, and artifact layout.
- Daytona owns the remote sandbox lifecycle through Harbor's `daytona` environment provider.
- `GBQAHarborAgent` is a Harbor custom agent wrapper that uploads the current GBQA runtime into `/sandbox`, starts Dark Castle from `/sandbox/software/dark-castle`, runs the QA loop, and exports stable artifacts under Harbor's `/logs` contract.
- The first task is `gbqa/tasks/dark-castle`; its software environment is downloaded from the real GitHub release archive for `Tsumugii24/dark-castle`.

## Configuration Boundaries

- `agent/config.toml` is harness policy only: model sampling, loop budgets, memory, operator retry, and current QA-agent backend defaults.
- `gbqa/tasks/dark-castle/gbqa.yaml` is the task source of truth: software source release, service endpoints, interaction modes, human baseline, artifact contract, and agent-facing task profile.
- `gbqa.protocol` defines the stable QA output schema consumed by verifiers, independent of which agent harness produced the artifacts.
- `gbqa.reporting` converts harness-specific outputs into `run.json`, `bugs.json`, `steps.jsonl`, and artifact files.

Harness config is resolved with explicit precedence: CLI overrides, trial/run
config, task package `gbqa.yaml`, repo harness defaults, then built-in
defaults. The redacted final resolved config and layer provenance are exported
under `run_spec.config` for reproducible runs.

GBQA interaction profiles are harness-side execution presets:

- `api`: use only the backend API interaction mode.
- `browser`: use only the browser interaction mode.
- `computer_use`: use only the GUI computer-use interaction mode.
- `default`: enable every mode declared by the task metadata and use `run.interaction_mode` as the primary mode when configured, otherwise falling back to the task's default interaction mode.

In `default`, the planner sees explicit mode tools such as `api_action`, `browser_action`, and `computer_action` so it can choose the interaction path per step.

GBQA harness modes are a separate capability setting:

- `minimal`: keep the smallest closed-loop QA harness that can explore a real sandbox software environment over many steps and report bugs. This keeps interaction actions, lifecycle tools, run reports, traces, and verifier artifacts, but does not expose diagnostic code/log skills or automatic code/log analysis to the agent.
- `full`: enable available diagnostic and augmentation skills/tools such as code and log tools, activate their skill instructions, allow automatic code/log diagnostic policies, and run isolated worker subagents.

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

Fill in `DAYTONA_API_KEY`, `API_KEY`, and `MODEL_NAME`. `BASE_URL` defaults to ZenMux's OpenAI-compatible endpoint, `https://zenmux.ai/api/v1`, and can be overridden when needed. The model request configuration is intentionally provider-neutral and does not use `OPENAI_*` env names.

Use `python -m gbqa.cli.harbor_run ...` or the installed `gbqa-harbor ...` command so Harbor, Daytona, and the GBQA agent all inherit the repository-root `.env`. Direct `harbor run ...` still works only if those variables are already exported in the shell.

## Commands

Oracle verifier pass:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  -a oracle
```

API mode:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=api
```

Browser mode:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=browser
```

Harbor built-in Codex and Claude Code task runners can also be selected through
the same wrapper:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner codex \
  --gbqa-agent-model gpt-5 \
  --gbqa-agent-auth subscription \
  --gbqa-codex-auth-file "$HOME/.codex/auth.json"
```

Verifier judges are independently selectable with `--gbqa-judge`, including
subscription-backed RewardKit agent judges. See `docs/subscription-auth.md` for
the full Codex / Claude Code task-runner and verifier-judge matrix.

## Expected Artifacts

The agent writes stable GBQA artifacts under `/logs/agent/gbqa`:

- `run.json`
- `bugs.json`
- `steps.jsonl`
- `trace.jsonl` when available
- `report.md` when available
- `artifacts/` for screenshots and other interaction files

The verifier writes Harbor-compatible outputs under `/logs/verifier`:

- `reward.txt`
- `reward.json`

## Non-Goals

- Local Docker is not the M1 default or acceptance path.
- Cua is not integrated in M1.
- Windows and macOS computer-use are not part of M1.
- GBQA does not implement its own Harbor replacement for jobs, trials, datasets, or providers in M1.
