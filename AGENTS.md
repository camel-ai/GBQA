# GBQA Architecture Notes For Agents

This `AGENTS.md` file records the current architecture decisions for GBQA and should be read before changing sandbox, task packaging, agent harness, verifier, or environment code.

## Overview

The autonomous discovery of bugs remains a significant challenge in modern software development. Compared to code generation, the complexity of dynamic runtime environments makes bug discovery considerably harder for LLMs. A GBQA task points to a real GitHub software release, defines how that software should run in an isolated sandbox, exposes supported interaction modes, and provides verifier-owned human-baseline bugs plus value criteria for scoring.

## Milestone Planning

### M1

Milestone 1 is complete and remains the validated Daytona-first baseline:

- Harbor owns task packaging, trial execution, verifier execution, and artifact collection.
- Daytona owns remote sandbox lifecycle through Harbor's `daytona` environment provider.
- GBQA owns task metadata, QA agent harness behavior, normalized reports, and
  platform-level bug evaluation. `agent/` must not own benchmark scoring logic.
- Local Docker is not an M1 acceptance path.
- `GBQAHarborAgent` is the default custom Harbor agent wrapper.
- Dark Castle is the first external GitHub software task and is ready in the remote Daytona sandbox.
- Terminal mode and browser mode are the completed interaction paths.
- Computer interaction is present in task metadata and Harbor config as an experimental post-M1 path, but it is not part of the validated M1 smoke baseline.
- Harbor-compatible verifier execution and GBQA artifact export are implemented.
- Parallel evaluation is available through Harbor's concurrent trial runner; in the Daytona path, this means multiple independent Daytona sandboxes can run at the same time.

The validated M1 topology is colocated:

- Harbor runs locally and controls the remote Daytona sandbox.
- The target software environment runs inside the Daytona sandbox.
- The GBQA agent harness is uploaded into the same Daytona sandbox and runs there.
- The verifier runs in the same Daytona sandbox after the agent finishes.

Validated smoke command:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; python -m gbqa.cli.harbor_run run --job-name gbqa-daytona-smoke-terminal-lf-fix -p gbqa/tasks/dark-castle -e daytona --gbqa-task-runner gbqa --ak interaction_mode=terminal --ak max_steps=10
```

Validated result:

- Daytona provisioned the remote sandbox.
- Dark Castle started inside the sandbox.
- `GBQAHarborAgent` interacted with the environment through terminal mode's HTTP API surface for 10 steps.
- Harbor downloaded `/logs/agent/gbqa` artifacts.
- Verifier wrote `/logs/verifier/reward.txt`, `/logs/verifier/reward.json`, and `/logs/verifier/gbqa_result.json`.
- A 10-step smoke run may legitimately receive reward `0.0` if no verified candidate bug earns value; this is not an infrastructure failure.

### M2

- M2: Harbor built-in `codex` and `claude-code` task runners are selectable
  through `gbqa.cli.harbor_run` and can use subscription auth. Add additional
  custom QA harness wrappers such as `CodexHarborAgent` and
  `ClaudeCodeHarborAgent` only if they provide GBQA-specific behavior beyond
  Harbor's built-in CLI agents.
- M2: add more verified benchmark environments and task manifests.
- M2: harden the experimental computer interaction path and extend further toward free interaction mode (mixed interaction mode).
- M2: keep Linux as the validated sandbox baseline while expanding toward Windows and macOS support.

### M3

- M3: run large-scale LLM evaluation experiments and release a leaderboard.

### M4

- M4: collect trajectory data, standardize reward signals, and support RL training workflows.

## Harbor Boundary

Keep GBQA compatible with Harbor instead of replacing Harbor's job/trial system.

Harbor task packages use this structure:

- `task.toml`: Harbor-compatible task metadata, runtime resource requirements, agent/verifier timeout, environment config.
- `instruction.md`: agent-facing instruction.
- `environment/`: environment definition, normally `Dockerfile`.
- `environment-computer-use/`: optional GUI/Cua environment definition used only by GBQA's computer overlay path.
- `tests/`: verifier entrypoint and verifier assets.
- `solution/`: oracle solution assets.
- `bugs/`: GBQA human-baseline bug definitions.
- `gbqa.yaml`: GBQA-specific metadata that Harbor does not own.

Harbor itself consumes `environment/`. When `interaction_mode=computer`,
`gbqa.cli.harbor_run` may create a temporary task overlay that replaces
`environment/` with `environment-computer-use/` before delegating to Harbor.
Direct `harbor run` should not be treated as a stable computer interaction entrypoint.

Harbor's standard in-sandbox paths must remain stable:

- `/logs/agent`: agent logs and trajectories.
- `/logs/verifier`: verifier outputs, including `reward.txt` and `reward.json`.
- `/logs/artifacts`: extra collected artifacts.
- `/tests`: verifier files uploaded by Harbor before verification.
- `/solution`: oracle files uploaded by Harbor when using the oracle agent.

Do not move Harbor reward files or verifier outputs out of `/logs/verifier`.

Harbor 0.7+ compatibility:

- GBQA requires Python 3.12+ because Harbor 0.7 requires Python 3.12+.
- Harbor 0.7 reads `reward.json` before `reward.txt`.
- `reward.json` must contain only numeric reward fields compatible with `dict[str, float | int]`, for example `{"reward": 0.0}`.
- Full GBQA verifier details belong in `/logs/verifier/gbqa_result.json`, not in `reward.json`.

## Daytona Sandbox Layout

Daytona is the remote isolation boundary. Inside that boundary, GBQA uses `/sandbox` as its runtime workspace.

Current GBQA sandbox layout:

```text
/sandbox/
  software/
    <task>/
  agent/
  gbqa/
  runtime/
    config.toml

/logs/
  agent/
    gbqa/
  verifier/
  artifacts/
```

Meaning:

- `/sandbox/software/<task>` contains the downloaded target GitHub software release.
- `/sandbox/agent` contains the agent harness for QA tasks.
- `/sandbox/gbqa` contains the uploaded GBQA platform package.
- `/sandbox/runtime/config.toml` contains the rendered run config for the current Harbor trial.
- `/logs/agent/gbqa` contains normalized GBQA run artifacts.
- `/logs/verifier` contains Harbor-compatible reward outputs.

Do not reintroduce `/opt/gbqa` as the GBQA runtime root.

## Dark Castle as an example environment and QA Task

Repository:

- `https://github.com/Tsumugii24/dark-castle`

Release policy:

- Latest fixed reference release: `v0.2.0`
- Selected buggy sandbox baseline: `v0.1.0`
- Selection role: `latest_minus_one`
- Archive URL: `https://github.com/Tsumugii24/dark-castle/archive/refs/tags/v0.1.0.tar.gz`

The GitHub software repository must not contain GBQA human-baseline `bugs/` files. Human baseline bugs belong in the GBQA task package:

- `gbqa/tasks/dark-castle/bugs/dark-castle.json`

The task metadata source of truth is:

- `gbqa/tasks/dark-castle/gbqa.yaml`

The Harbor-facing mirror metadata is:

- `gbqa/tasks/dark-castle/task.toml`

If a new Dark Castle release is created, do not automatically float the benchmark baseline. Update the selected release explicitly for reproducibility.

## Agent Harness Boundary

The current default QA agent harness lives under `agent/` and is wrapped for Harbor by:

- `gbqa.harbor.agent.GBQAHarborAgent`

The harness should stay task-generic, but the current Harbor baseline still
contains Dark Castle startup and log-copy glue. Treat that as baseline-specific
integration to extract before adding many unrelated tasks, not as a pattern for
new generic harness code.

- Use task/environment terminology in platform code.
- Avoid introducing new generic code with `game` naming.
- Game-specific naming is acceptable only inside external game software or task-specific metadata where the upstream API uses it, such as Dark Castle's `game_id` response field.

Current planner-visible tool architecture:

- `agent/src/tool_registry.py` owns progressive tool disclosure. The default
  planner surface is `environment_action` plus `use_skill`; optional tools are
  revealed only after the agent activates the corresponding skill.
- `agent/skills/*/SKILL.md` files are runtime prompt/tool disclosure assets, not
  passive documentation. Harbor uploads `run_agent.py`, `src/`, `prompts/`, and
  `skills/` into `/sandbox/agent`.
- `agent/src/codebase_types.py` owns `UniversalCodebaseAdapter`, which provides
  white-box source inspection and temporary code injection through backend shell
  access rooted at `/sandbox/software`.
- `agent/src/log_sources.py`, `agent/src/log_types.py`, and
  `agent/src/log_analyzer.py` own source-backed log diagnostics for agent
  trajectory logs and task-declared runtime logs.
- Task/session lifecycle is owned by `agent/skills/lifecycle/SKILL.md`.
  A **session** is the harness-level unit of interactive context for one task.
  It is mode-agnostic: terminal, browser, and computer runs all use the same
  session naming and lifecycle tools regardless of which execution backend
  creates the session. Do not label planner-facing lifecycle text as
  "backend session", "browser session", or similar provider-specific variants.
  At run entry the harness records only `start_task` and the initial
  `start_session` as system events. Those are not planner tools.
  The lifecycle skill is activated by default and provides planner-visible
  session management:
  - `start_session`: open a session and make it active
  - `end_session`: close one session only
  - `new_session`: open a fresh active session without closing other open
    sessions
  - `refresh_session`: refresh capability metadata for a specific `session_id`
  - `switch_session`: change the active session among open sessions
  - `list_sessions`: list `active_session_id` and `open_session_ids` on demand
  - `end_task`: finish the task loop
  `start_session` and `new_session` echo session IDs in their step
  observations. Use `list_sessions` when the agent needs to re-check IDs; do not
  inject session state into every planner step.
  The orchestrator keeps an `open_sessions` pool plus one `active_session`.
  Task end closes every still-open session before recording `end_task`.
  Do not add task-family names such as `close_game` to generic orchestrator or
  tool code.
- Every run should record lifecycle events in reports/logs. `end_task` must
  distinguish `trigger=agent` for an active planner request from
  `trigger=max_steps` when the loop is force-ended by the step budget.

The rendered Harbor run config is produced by:

- `gbqa.harbor.config.render_agent_config(...)`

This config should contain harness policy only: model, reasoning, loop budgets,
memory, interaction adapter config, log source wiring, and reporting. Task
endpoints, supported interaction modes, internal log sources, and software
source belong in task metadata.

## Interaction Modes

Current interaction modes:

- `terminal`
- `browser`
- `computer`

These modes are tool-use paths, while concrete task-specific surfaces are
metadata. For example, terminal mode may expose an HTTP API, CLI, shell command,
Python API, or other code-facing contract through `metadata.interaction_surfaces`.
The public mode names must stay coarse and stable:

- Terminal mode calls or drives the target's code-facing surface.
- Browser mode drives the frontend through Playwright MCP/runtime.
- Computer mode drives a GUI/Cua environment and currently depends on
  `gbqa.cli.harbor_run` selecting `environment-computer-use/` through a temporary
  overlay when that directory exists.

Validated baseline status:

- Terminal and browser are the completed M1 paths.
- Computer is wired through task metadata, config rendering, and the Harbor
  wrapper, but remains experimental until GUI/Cua environment selection becomes
  a first-class task mechanism.

Planned post-M1 modes:

- free interaction mode (mixed interaction mode)

The harness uses `interaction_profile` to select interaction exposure:

- `terminal`, `browser`, and `computer` constrain the run to one interaction mode.
- `default` enables every mode declared by task metadata and uses
  `run.interaction_mode` as the primary mode when configured; otherwise it falls
  back to the task's default interaction mode.
- In multi-mode/default runs, planner-facing mode tools should stay explicit
  (`terminal_action`, `browser_action`, `computer_action`) rather than relying on
  natural-language mode selection inside a single action string.

The harness uses `harness_mode` to select the capability surface:

- `minimal` is the smallest closed-loop QA harness: interact with the sandbox
  software environment, manage sessions, keep run instrumentation, and report
  bugs. Do not expose diagnostic code/log skills or automatic code/log analysis
  in this mode. Isolated worker subagents are disabled by default.
- `full` enables the allowed diagnostic and augmentation skills/tools, including
  code and log tools when available, and activates their skill instructions so
  they are loaded into planner context. Full mode also enables isolated worker
  subagents.

Worker subagents are harness-owned isolated contexts, not planner-visible
environment tools:

- `ExplorerAgent` reviews coverage summaries and proposes state-frontier targets.
- `ReproducerAgent` turns a new hypothesis into a reproduction plan.
- `LogAnalystAgent` reads log-tool output and compresses log evidence.
- `CodeLocalizerAgent` reads code-search output and suggests likely files or
  symbols.

Each worker must use a separate LLM agent id (`subagent.<name>.<call>`) and
must not share main planner memory or full trace context. The orchestrator only
feeds short worker summaries back into planner context through
`subagent_summary`; full worker prompts/outputs are excluded from run metadata
unless `subagents.record_prompts=true`.

Harness hooks are lifecycle callbacks that emit explicit trajectory events.
Hook events must be written as `type="hook"` rows in `trace.jsonl` and included
in reports. Stable hook event labels include:

- `RunStarted` / `RunEnded`
- `Planning` / `Planned` / `PlanFailed`
- `Explored` for environment/terminal/browser/computer actions
- `Ran` for non-editing tool calls
- `Edited` for code write/restore tools
- `Lifecycle` for session/task lifecycle events
- `Covered` for coverage-state updates
- `Reported` for bug report events
- `Summarized` for memory summary events
- `Diagnosed` for automatic code/log diagnostics
- `Ran` with `hook=on_subagent_result` for isolated worker subagent results

Harness configuration is resolved through explicit layers. Precedence, from
highest to lowest, is:

- CLI overrides, including direct `run_agent.py` flags and Harbor `--ak` values
  that have been materialized into the rendered trial config.
- Trial/run config, normally `/sandbox/runtime/config.toml`.
- Task package metadata from `gbqa.yaml`.
- Repo harness default config, normally `agent/config.toml.example`.
- Built-in defaults.

The final resolved, redacted config plus layer provenance must be written into
`run_spec.config`. Task metadata and harness-mode application are normalizers
recorded alongside the layer stack; they should not be hidden as implicit
side effects.

The agent planner/operator should target normalized capabilities, not
provider-specific implementation details. Session lifecycle vocabulary should
stay generic (`session`, `session_id`, `active_session`, `open_session_ids`).

Logs are source-backed diagnostics exposed through the `logs` skill. They are
not the same as memory:

- Memory is agent-side context compression and retrieval.
- Logs are environment/runtime-side diagnostics and harness-owned trajectory
  diagnostics exposed as optional tool capabilities.
- `agent_trajectory` is provided by the harness; task metadata can declare
  runtime sources such as stdout/stderr files or software-owned session log
  directories through `runtime.internal_log_sources`.
- `log_analyze` can combine trajectory and runtime sources to summarize
  failures, repeated actions, suspicious state transitions, and runtime errors.

## Environment And Model Configuration

There is one root `.env.example`. Do not reintroduce per-subproject env templates.

Required model request variables are provider-neutral:

- `API_KEY`
- `BASE_URL`
- `MODEL_NAME`

Daytona requires:

- `DAYTONA_API_KEY`

Default `BASE_URL` is:

- `https://zenmux.ai/api/v1`

Reasoning settings belong in the LLM config. The harness supports reasoning mode and effort where the target model/provider accepts OpenAI-compatible reasoning parameters.

Harbor's built-in CLI agents can use account subscription credentials instead
of API keys when running a task directly. GBQA exposes this through
`gbqa.cli.harbor_run` selectors:

- Task runner: `--gbqa-task-runner gbqa|codex|claude-code`.
- Agent model: `--gbqa-agent-model <model>`.
- Agent auth: `--gbqa-agent-auth auto|api_key|subscription`.
- Claude Code: provide `CLAUDE_CODE_OAUTH_TOKEN` generated by
  `claude setup-token`; subscription mode passes `CLAUDE_FORCE_OAUTH=1`.
- Codex: pass `--gbqa-codex-auth-file <path>` or set
  `CODEX_AUTH_JSON_PATH`; Harbor's codex agent uploads the host `auth.json`.
  Set `CODEX_FORCE_API_KEY=1` or `--gbqa-agent-auth api_key` to force API-key
  mode instead.

This subscription path applies to Harbor's `-a claude-code` / `-a codex`
agents. The default `GBQAHarborAgent` still uses `API_KEY`, `BASE_URL`, and
`MODEL_NAME` because it runs the GBQA QA harness directly.

Rewardkit value-evaluation review can also use subscription-backed agent judges by
setting `REWARDKIT_JUDGE=claude-code` or `REWARDKIT_JUDGE=codex`, or through
`--gbqa-judge claude-code|codex` and
`--gbqa-judge-auth api_key|subscription`. For Codex inside the verifier
container, prefer `CODEX_AUTH_JSON_B64` containing a base64-encoded
`~/.codex/auth.json`; the GBQA wrapper can derive this from
`--gbqa-codex-auth-file`, and `tests/test.sh` writes it into
`CODEX_HOME/auth.json` before running Rewardkit. RewardKit-style
`CODEX_ACCESS_TOKEN` and `REWARDKIT_FORCE_OAUTH` are also passed through when
configured. Cowork-style aliases
`JUDGE_AGENT`, `JUDGE_MODEL`, and `JUDGE_CODEX_MODEL` are accepted by verifier
scripts, but `REWARDKIT_JUDGE` and `REWARDKIT_MODEL` remain canonical.

## Report And Verifier Contract

Every GBQA run should export normalized artifacts under `/logs/agent/gbqa`:

- `run.json`
- `bugs.json`
- `steps.jsonl`
- `trace.jsonl` when available
- `report.md` when available
- `artifacts/` for screenshots, traces, DOM dumps, or other interaction files

Each entry in `bugs.json` should use this evidence shape:

```json
{
  "bugs": [
    {
      "title": "Short descriptive title",
      "description": "What goes wrong and why it is a bug.",
      "evidence": {
        "expected_behavior": "What correct behavior should look like.",
        "observed_fault": "The incorrect behavior you observed.",
        "minimal_reproduction": ["step 1", "step 2"]
      }
    }
  ]
}
```

Human-baseline bug files may keep the same three fields at the top level;
`gbqa.protocol.schemas.normalize_bug_evidence(...)` lifts them into `evidence`
during export and verifier loading.

GBQA verifiers must use Harbor Rewardkit. `harbor-rewardkit` is a required
platform dependency; if it is missing, `gbqa.rewards.runner` fails fast with
an install hint. Rewardkit discovers criteria from `tests/`, writes numeric
scores to `/logs/verifier/reward.json`, and writes per-criterion detail to
`/logs/verifier/reward-details.json`. See
[Harbor Rewardkit](https://www.harborframework.com/docs/rewardkit) and
[LLM-as-a-Judge](https://www.harborframework.com/docs/tutorials/llm-as-a-judge).

Canonical task template:

```text
gbqa/tasks/_template/tests/
  test.sh
  criteria.py
  reward/check.py
  agent_value/check.py
  human_value/check.py
  verified_bug_count/check.py
  evaluated_bug_count/check.py
  trajectory/check.py
  value/baseline_values.json
  value/validation_cases.json
  quality/quality.toml
  quality/value_evaluation_review.md
  judge/evidence_quality.toml.example
```

Install the template into a task with
`gbqa.rewards.template.install_task_verifier_tests(...)`. Each subdirectory
maps to one Rewardkit reward name in `reward.json`.

Extension points:

- Value-based bug evaluation: shared criteria in `gbqa.rewards.criteria`
  call `gbqa.rewards.value_based.evaluate_value_based_report(...)`.
  Ground-truth bugs are a pre-scored human baseline, not the only bug oracle.
  The default reward is `min(1.0, agent_value / human_value)`.
- Candidate verification: `/tests/value/validation_cases.json` provides
  deterministic task validation cases. A validation case may include a
  `command`; nonzero exit in the buggy environment is treated as the rule-based
  failing-test signal. Optional verifier-side commands
  `GBQA_BUG_TEST_GENERATOR_CMD`, `GBQA_BUG_TEST_REASONABLENESS_CMD`, and
  `GBQA_BUG_TEST_EXECUTOR_CMD` can dynamically construct, review, and execute
  hidden-bug tests.
- Value scoring: verified bugs are scored on impact, scope, and
  reproducibility, then mapped to stable tier points. `GBQA_VALUE_AGENT_CMD`
  can replace the deterministic fallback scorer.
- Trajectory checks: `trajectory_exported` for GBQA `trace.jsonl` /
  `steps.jsonl`, plus optional `atif_trajectory_tool_used` for ATIF JSON
- Value-evaluation review (LLM-as-a-Judge): `quality/quality.toml` loads the
  human baseline, baseline values, validation cases, reported bugs, and
  `/logs/verifier/gbqa_result.json` into the same judge context. Configure the
  judge model and credentials through `task.toml` `[verifier.env]`
  (`REWARDKIT_JUDGE`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` / `OPENAI_API_BASE`,
  `CLAUDE_CODE_OAUTH_TOKEN`, or Codex `auth.json` variables).
- Optional rubric extensions: copy `judge/evidence_quality.toml.example` to
  `judge/evidence_quality.toml` for evidence-quality scoring.

`tests/test.sh` should call `python -m gbqa.rewards.runner` with
`PYTHONPATH=/sandbox`. The runner always executes Rewardkit, then writes
GBQA post-processing artifacts without rewriting Rewardkit scores.

Verifier outputs:

- `/logs/verifier/reward.json` — Rewardkit-owned numeric rewards
- `/logs/verifier/reward-details.json` — Rewardkit criterion details plus a
  `gbqa` evidence section
- `/logs/verifier/reward.txt` — primary scalar reward derived from
  `reward.json`
- `/logs/verifier/gbqa_result.json` — full value-evaluation payload for debugging

Core platform entrypoints:

- `gbqa.rewards.run_task_verifier(...)`
- `gbqa.rewards.value_based.evaluate_value_based_report(...)`
- `gbqa.rewards.criteria.*` shared Rewardkit criteria
- `gbqa.rewards.template.install_task_verifier_tests(...)`

Do not add standalone legacy verifier CLIs or fallback paths that bypass
Rewardkit.

Shell verifier scripts must use LF line endings. Windows CRLF checkouts can break Linux Daytona execution with `/usr/bin/env: 'bash\r': No such file or directory`. Keep `.gitattributes` enforcing:

```text
*.sh text eol=lf
```

## Current Package Boundaries

Use these directories for new platform code:

- `gbqa/spec/` or `gbqa/spec.py`: task metadata and schema loading.
- `gbqa/harbor/`: Harbor wrappers and integration glue.
- `gbqa/reporting/`: conversion from harness-specific reports to GBQA normalized artifacts.
- `gbqa/protocol/`: lightweight stable run/report/bug schemas and normalizers.
- `gbqa/rewards/`: Harbor Rewardkit bridge, value evaluation, and verifier outputs.
- `gbqa/tasks/`: first-party Harbor-compatible task packages.
- `agent/`: current QA agent harness implementation.
- `agent/skills/`: runtime skill instructions used for progressive tool
  disclosure.
- `agent/src/tool_registry.py`: planner-visible tool registry and skill-gated
  disclosure.
- `agent/src/codebase_types.py`: universal sandbox codebase adapter for
  white-box debugging under `/sandbox/software`.
- `agent/src/log_sources.py`, `agent/src/log_types.py`, and
  `agent/src/log_analyzer.py`: log source declarations, trajectory/runtime log
  reading, and log analysis.
- `environment/`: offline environment discovery, filtering, Daytona verification,
  human review, and task package generation. This directory is not part of the
  GBQA runtime package and must not be uploaded into Daytona during Harbor runs.
- `environment/export/`: draft task package generation. Generated packages are
  not production-ready until human baseline, verifier behavior, and reward output
  contracts are reviewed.

Environment export currently generates package files from Python code in
`environment/export/generator.py`; do not assume templates under
`environment/export/templates/` are the active rendering source without checking
the generator.

Environment sourcing keeps a persistent local resume ledger under
`environment/catalog/state/`. The default CLI behavior is resume-on:

- `python -m environment.sourcing.cli run ...` defaults to `--resume`.
- `python -m environment.sourcing.cli verify ...` defaults to `--resume`.
- Use `--no-resume` only when intentionally reprocessing already-seen GitHub
  repositories or verification probes.
- Use `--state-dir <path>` for an isolated experiment ledger.

Current resume keys:

- Repository key: `github:<owner>/<repo>`.
- Release-pair key: `github:<owner>/<repo>::<baseline>::<fixed>`.
- Sub-environment key: `github:<owner>/<repo>::<baseline>::<fixed>::<sub_path>`.
- Verification key: `<sub_environment_key>::<provider>::<probe_version>`.

Discovery resume is currently repository-level: once a GitHub repo is recorded
in `repositories.jsonl`, default sourcing skips it and keeps paging for new
repos. To refresh a repo for new releases, use `--no-resume`, a separate
`--state-dir`, or remove the relevant local state rows. `environment/catalog/state/`
is local generated state and must stay gitignored.

Do not reintroduce `hub/`. The old hub sourcing prototype has been replaced by
the root-level `environment/` preparation system.

## Verification Commands

`agent/` owns only the QA harness runtime and must not own benchmark scoring or
verifier value-evaluation logic. The benchmark verifier path is `tests/test.sh`
-> `python -m gbqa.rewards.runner`; keep task-local criteria aligned with
`gbqa/tasks/_template/tests`. Do not reintroduce local agent-side evaluator CLIs.

Before claiming architecture or path changes are complete, run the commands for your operating system.

### Windows PowerShell

For environment-preparation changes, run:

```powershell
python -m unittest discover -s environment/tests -p "test_*.py" -v
```

```powershell
python -m compileall -q environment gbqa agent/src agent/run_agent.py
```

```powershell
$failed = @(); Get-ChildItem -Path agent/test -Filter 'test_*.py' | Sort-Object Name | ForEach-Object { python $_.FullName | Out-Null; if ($LASTEXITCODE -ne 0) { $failed += $_.Name } }; if ($failed.Count -gt 0) { Write-Host "FAILED:" ($failed -join ', '); exit 1 } else { Write-Host "all agent test scripts passed" }
```

For skill-gated tool, log-source, or white-box debugging changes, also run the
targeted pytest coverage:

```powershell
python -m pytest agent/test/test_prompt_render.py agent/test/test_log_sources.py agent/test/test_log_analysis_tool.py agent/test/test_code_tool_loop.py agent/test/test_run_agent_endpoints.py agent/test/test_gbqa_harbor.py
```

For sandbox path changes, also run:

```powershell
rg -n "/opt/gbqa|/workspace" gbqa agent docs README.md pyproject.toml
```

Expected result for the path scan is no matches.

For Daytona smoke validation on Windows, keep UTF-8 output enabled so Rich/Harbor summary output does not fail under a GBK console:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; python -m gbqa.cli.harbor_run run --job-name gbqa-daytona-smoke-terminal-lf-fix -p gbqa/tasks/dark-castle -e daytona --gbqa-task-runner gbqa --ak interaction_mode=terminal --ak max_steps=10
```

The preferred GBQA command form is `python -m gbqa.cli.harbor_run ...` because
the wrapper loads the repository-root `.env`, expands GBQA-only selector flags
such as `--gbqa-task-runner`, and then forwards native arguments to Harbor.
Direct `harbor run ...` is valid for completed terminal/browser paths only when the
required environment variables are already present in the shell and native Harbor
agent flags are used:

```powershell
$env:DAYTONA_API_KEY='...'
$env:API_KEY='...'
$env:BASE_URL='https://zenmux.ai/api/v1'
$env:MODEL_NAME='...'
harbor run -p gbqa/tasks/dark-castle -e daytona --agent-import-path gbqa.harbor.agent:GBQAHarborAgent --ak interaction_mode=terminal --ak max_steps=10
```

For completed terminal/browser modes, `python -m gbqa.cli.harbor_run run ...` and
`harbor run ...` should be behaviorally equivalent after environment variables
are loaded and equivalent native Harbor agent flags are used. Do not assume this
equivalence for post-M1 `computer`: computer needs a GUI/Cua environment
image, and any temporary task overlay or backend-specific environment selection
must be explicit and documented before direct `harbor run` is considered
supported.

For parallel Daytona evaluation, use Harbor's concurrent trial runner. For example, five independent task environments can run in five independent Daytona sandboxes:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; python -m gbqa.cli.harbor_run run -p gbqa/tasks -e daytona --gbqa-task-runner gbqa --ak interaction_mode=terminal --ak max_steps=10 --n-tasks 5 --n-concurrent 5
```

`--n-concurrent` controls concurrent Harbor trials. In the Daytona path, concurrent trials mean multiple remote Daytona sandboxes, not multiple agents inside one sandbox.

### macOS / Linux Shell

```bash
python -m unittest discover -s environment/tests -p "test_*.py" -v
```

```bash
python -m compileall -q environment gbqa agent/src agent/run_agent.py
```

```bash
failed=()
for test_file in $(find agent/test -maxdepth 1 -name 'test_*.py' | sort); do
  python "$test_file" >/dev/null || failed+=("$(basename "$test_file")")
done
if [ "${#failed[@]}" -gt 0 ]; then
  printf 'FAILED: %s\n' "${failed[*]}"
  exit 1
else
  echo "all agent test scripts passed"
fi
```

For skill-gated tool, log-source, or white-box debugging changes, also run:

```bash
python -m pytest agent/test/test_prompt_render.py agent/test/test_log_sources.py agent/test/test_log_analysis_tool.py agent/test/test_code_tool_loop.py agent/test/test_run_agent_endpoints.py agent/test/test_gbqa_harbor.py
```

For sandbox path changes, also run:

```bash
rg -n "/opt/gbqa|/workspace" gbqa agent docs README.md pyproject.toml
```

Expected result for the path scan is no matches.

For Daytona smoke validation:

```bash
python -m gbqa.cli.harbor_run run --job-name gbqa-daytona-smoke-terminal -p gbqa/tasks/dark-castle -e daytona --gbqa-task-runner gbqa --ak interaction_mode=terminal --ak max_steps=10
```

The preferred GBQA command form is `python -m gbqa.cli.harbor_run run` because
the wrapper loads the repository-root `.env`, expands GBQA-only selector flags
such as `--gbqa-task-runner`, and then forwards native arguments to Harbor.
Direct `harbor run` is valid for completed terminal/browser paths only when the
required environment variables are already exported and native Harbor agent
flags are used:

```bash
export DAYTONA_API_KEY='...'
export API_KEY='...'
export BASE_URL='https://zenmux.ai/api/v1'
export MODEL_NAME='...'
harbor run -p gbqa/tasks/dark-castle -e daytona --agent-import-path gbqa.harbor.agent:GBQAHarborAgent --ak interaction_mode=terminal --ak max_steps=10
```

For completed terminal/browser modes, `python -m gbqa.cli.harbor_run run ...` and
`harbor run ...` should be behaviorally equivalent after environment variables
are loaded and equivalent native Harbor agent flags are used.

> [!WARNING]
> Warning for  `computer`: computer interaction (experimental) needs a separate GUI/Cua environment image, so we recommend to use `python -m gbqa.cli.harbor_run run` for stable execution, `harbor run` cannot handle environment image selection and may raise errors.

For parallel Daytona evaluation:

```bash
python -m gbqa.cli.harbor_run run -p gbqa/tasks -e daytona --gbqa-task-runner gbqa --ak interaction_mode=terminal --ak max_steps=10 --n-tasks 5 --n-concurrent 5
```

`--n-concurrent` controls concurrent Harbor trials. In the Daytona path, concurrent trials mean multiple remote Daytona sandboxes, not multiple agents inside one sandbox.
