# GBQA QA Agent Harness Architecture

This document describes the current GBQA QA Agent Harness implementation under
`agent/` and its Harbor integration under `gbqa/harbor/`. It is written as an
engineering reference for maintainers who need to change the harness loop,
configuration model, tools, skills, subagents, reports, or sandbox integration.

## 1. Purpose

GBQA evaluates whether autonomous agents can discover real bugs in real software
running inside an isolated sandbox. The QA Agent Harness is the default GBQA
agent implementation. It is designed for real-world long-horizon bug discovery.

The harness should:

- Explore a live software environment through supported interaction modes.
- Maintain task/session lifecycle state over many steps.
- Track state coverage and bug hypotheses.
- Reproduce and promote suspected bugs into normalized bug reports.
- Use optional diagnostics such as logs and source inspection without making
  those capabilities mandatory in the minimal setting.
- Export stable run artifacts for verifier and benchmark analysis.
- Stay task-generic and keep task facts in task metadata.

## 2. System Context

GBQA is intentionally layered on top of Harbor instead of replacing Harbor's
task, trial, environment, and verifier lifecycle.

```mermaid
flowchart TB
  User[User or evaluator] --> HarborCLI[GBQA Harbor CLI wrapper]
  HarborCLI --> Harbor[Harbor trial runner]
  Harbor --> Daytona[Daytona sandbox provider]
  Daytona --> Sandbox[Remote sandbox]

  subgraph Sandbox["/sandbox and /logs"]
    Software["/sandbox/software/<task><br/>target software"]
    Agent["/sandbox/agent<br/>QA Agent Harness"]
    GBQA["/sandbox/gbqa<br/>GBQA platform package"]
    Runtime["/sandbox/runtime/config.toml<br/>trial run config"]
    Logs["/logs/agent/gbqa<br/>agent artifacts"]
    VerifierLogs["/logs/verifier<br/>reward outputs"]
  end

  Agent --> Software
  Agent --> Logs
  GBQA --> VerifierLogs
  Harbor --> VerifierLogs
```

Runtime ownership:

- Harbor owns task packaging, trial execution, verifier execution, and artifact
  collection.
- Daytona owns the remote sandbox isolation boundary.
- GBQA owns task metadata, the QA harness behavior, normalized agent artifacts,
  and platform-level verifier-side bug evaluation.
- `agent/` owns harness execution only. It emits reports and trajectories, but
  does not read verifier human-baseline bugs or compute benchmark scores.
- `GBQAHarborAgent` uploads the harness and GBQA package into the sandbox,
  renders `/sandbox/runtime/config.toml`, starts the target software service,
  runs `agent/run_agent.py`, and exports normalized GBQA artifacts.
- Harbor built-in `codex` and `claude-code` agents are supported as alternative
  task runners through `gbqa.cli.harbor_run` selectors. They do not run the GBQA
  QA Agent Harness; they run Harbor's CLI-agent path and must follow the task
  instruction artifact contract.
- RewardKit agent judges are supported independently in the verifier phase by
  selecting `REWARDKIT_JUDGE=codex` or `REWARDKIT_JUDGE=claude-code`, either
  directly or through `--gbqa-judge`.

## 3. Repository Boundaries

Primary implementation paths:

- `agent/run_agent.py`: harness entrypoint and dependency wiring.
- `agent/src/orchestrator.py`: main QA loop and task/session lifecycle.
- `agent/src/execution_backends.py`: terminal, browser, computer, and multi-mode
  interaction routing over the concrete backend implementations.
- `agent/src/tool_registry.py`: planner-visible tool registry and progressive
  skill disclosure.
- `agent/src/qa_state.py`: coverage state and hypothesis manager.
- `agent/src/subagents.py`: isolated worker subagents.
- `agent/src/hooks.py`: hook policy and hook event emission.
- `agent/src/run_spec.py`: versioned run specification exported with reports.
- `agent/src/config_layers.py`: layered TOML configuration resolution.
- `agent/src/reporter.py`: raw report and trajectory export.
- `gbqa/harbor/agent.py`: Harbor custom agent wrapper.
- `gbqa/harbor/config.py`: rendered sandbox trial config.
- `gbqa/spec.py`: GBQA task metadata loading and schema.
- `gbqa/reporting/`: conversion from harness reports to normalized artifacts.
- `gbqa/rewards/`: verifier and Rewardkit integration.

The current first-party task package is:

- `gbqa/tasks/dark-castle/`

Task metadata belongs in `gbqa.yaml`; the target software repository must not
contain GBQA human-baseline bug definitions.

## 4. Layered Architecture

The harness has five main layers:

```mermaid
flowchart TB
  Config["Configuration and Task Metadata<br/>config_layers.py, gbqa.yaml, config.toml"]
  Planner["Planner and Strategy State<br/>planner.py, qa_state.py, memory.py"]
  Orchestrator["Orchestrator Loop<br/>orchestrator.py"]
  Tools["Tools, Skills, and Workers<br/>tool_registry.py, skills/, subagents.py"]
  Backends["Execution Backends<br/>terminal/API, browser, computer, multi_mode"]
  Reports["Reports and Artifacts<br/>reporter.py, run_spec.py, gbqa/reporting"]

  Config --> Orchestrator
  Planner --> Orchestrator
  Orchestrator --> Tools
  Tools --> Backends
  Backends --> Orchestrator
  Orchestrator --> Reports
```

Design principles:

- Keep the benchmark environment real. The agent interacts with a live target
  software environment, not a mocked problem statement.
- Keep the harness task-generic. Platform code should use task, environment,
  session, and interaction terminology.
- Use explicit policies instead of hidden behavior. Loop budgets, hooks,
  subagents, tool policy, memory, and interaction modes are configured and
  exported in `run_spec`.
- Minimize planner surface by default. Optional diagnostics are progressively
  disclosed through skills or enabled by full harness mode.
- Prefer normalized capabilities over backend-specific implementation details.
- Record enough trajectory data to make bug reports auditable.

## 5. Sandbox Layout

Inside Daytona, GBQA uses `/sandbox` as the runtime workspace:

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

Important paths:

- `/sandbox/software/<task>`: target GitHub software release.
- `/sandbox/agent`: uploaded QA Agent Harness.
- `/sandbox/gbqa`: uploaded GBQA platform package.
- `/sandbox/runtime/config.toml`: rendered trial config.
- `/logs/agent/gbqa`: normalized agent artifacts.
- `/logs/verifier`: Harbor-compatible reward outputs.

Do not reintroduce the old opt-based GBQA runtime root.

## 6. Configuration Model

The harness uses TOML for run configuration. YAML remains only for GBQA task
metadata such as `gbqa/tasks/<task>/gbqa.yaml`.

Configuration is resolved through explicit layers:

```mermaid
flowchart BT
  Defaults["built_in_defaults<br/>agent/src/config_layers.py"]
  RepoDefault["repo_harness_default_config<br/>agent/config.toml.example"]
  TaskMetadata["task_package_gbqa_yaml<br/>gbqa.yaml-derived layer"]
  TrialRun["trial_run_config<br/>/sandbox/runtime/config.toml"]
  CLI["cli_overrides<br/>run_agent.py flags"]
  Final["final resolved config<br/>redacted into run_spec.config"]

  Defaults --> RepoDefault --> TaskMetadata --> TrialRun --> CLI --> Final
```

Precedence from highest to lowest:

1. CLI overrides, such as direct `run_agent.py` flags.
2. Trial/run config, normally `/sandbox/runtime/config.toml`.
3. Task package metadata from `gbqa.yaml`.
4. Repo harness default config, normally `agent/config.toml.example`.
5. Built-in defaults.

Harbor `--ak` values are applied before the sandbox run by rendering them into
the trial/run config. Inside the sandbox they are therefore visible through the
`trial_run_config` layer, not as direct `run_agent.py` CLI flags.

The final redacted configuration and layer provenance are exported under:

```text
run_spec.config
```

Sensitive values such as API keys, tokens, secrets, and passwords are redacted.

## 7. Interaction Profiles

The harness separates interaction exposure from backend implementation.

Supported public interaction profiles:

- `terminal`: use terminal-oriented execution through the task's declared surfaces, such as HTTP API, CLI, Python API, or shell commands.
- `browser`: use only browser interaction mode through Playwright MCP/runtime.
- `computer`: use screenshot-based GUI computer interaction mode.
- `default`: enable every interaction mode declared by task metadata.

In `default`, the task's `default_interaction_mode` is used unless
`run.interaction_mode` configures a different primary mode. When multiple modes
are enabled, the planner sees explicit mode tools:

- `terminal_action`
- `browser_action`
- `computer_action`

`terminal_action` remains the public planner-facing tool name even when the
concrete terminal surface is an HTTP API. Task metadata records whether terminal
means HTTP API, CLI, Python API, shell command, or another code-facing contract.

This avoids ambiguous natural-language mode selection inside a single generic
action string.

## 8. Harness Modes

The harness has two capability surfaces:

### Minimal Harness Mode

Minimal mode is the smallest closed-loop setting that can explore a real
sandbox software environment and report bugs.

It enables:

- Main planner/operator loop.
- Environment interaction.
- Task and session lifecycle tools.
- Coverage state.
- Hypothesis tracking.
- Reflection and summary policies when configured.
- Reports, traces, hooks, and verifier artifacts.

It disables by default:

- Code diagnostic tools.
- Log diagnostic tools.
- Automatic code/log diagnostics.
- Isolated worker subagents.
- Persistent memory carryover.

### Full Harness Mode

Full mode enables diagnostic and augmentation capabilities:

- Code tools and code skill instructions.
- Log tools and log skill instructions.
- Automatic code/log diagnostic policy.
- Isolated worker subagents.
- Diagnostic hook categories.

Full mode is intended for richer QA harness experiments and ablations, not as
the minimal baseline.

## 9. Main Loop

The main loop lives in `agent/src/orchestrator.py`.

```mermaid
sequenceDiagram
  participant Runner as run_agent.py
  participant Orch as Orchestrator
  participant Planner as ActionPlanner
  participant Tools as ToolRegistry
  participant Backend as ExecutionBackend
  participant State as QA State
  participant Report as Reporter

  Runner->>Orch: run(task_profile)
  Orch->>Backend: start_session()
  Orch->>Report: lifecycle start_task/start_session

  loop step 1..max_steps
    Orch->>Planner: plan(context)
    Planner-->>Orch: Action
    alt lifecycle tool
      Orch->>Tools: handle lifecycle
    else registry tool
      Orch->>Tools: invoke tool
    else environment action
      Orch->>Backend: execute normalized request
    end
    Orch->>State: record coverage and hypotheses
    Orch->>Report: write step, hooks, summaries
  end

  Orch->>Backend: close open sessions
  Orch->>Report: end_task, run metadata, artifacts
```

Core loop responsibilities:

- Start the initial harness session.
- Render tool and skill capability prompt sections.
- Call the planner for one action per step.
- Execute the action through lifecycle handling, tool registry, or execution
  backend.
- Record step data, lifecycle events, hook events, coverage, hypotheses, and
  summaries.
- Trigger reflection, failure-budget handling, auto diagnostics, and subagents.
- Stop on `end_task`, terminal policy, failure budget, or max steps.
- Close every open session before recording `end_task`.

## 10. Planner, Operator, and Reflection

The harness uses separate role agents for different responsibilities:

- `ActionPlanner`: chooses exactly one next action and one tool.
- `Operator`: translates one semantic planner action into normalized backend
  calls when a backend needs lower-level execution.
- `ReflectionAnalyzer`: reviews recent behavior and can promote high-confidence
  bug evidence.
- `MemoryManager`: maintains short-term trace and long-term summary context.

The planner receives:

- Task profile.
- Long-term memory summary.
- Recent trace.
- Coverage summary.
- Hypothesis summary.
- Short subagent summary.
- Current observation.
- Available tool and activated skill section.

The planner should not assume source access, log access, browser access, or GUI
access unless those tools are explicitly visible.

## 11. Execution Backends

Execution backends implement a normalized contract:

- `start_session(run_context) -> SessionHandle`
- `describe_capabilities(session, refresh=False) -> CapabilityDescriptor`
- `execute(session, request) -> BackendExecutionResult`
- `close_session(session)`

Current backend paths:

- API backend: calls the target backend API contract directly.
- Browser backend: drives the frontend through Playwright MCP/runtime.
- Computer-use backend: drives a GUI/Cua environment through screenshot-based
  control.
- Multi-mode backend: lazily creates child sessions for each enabled mode and
  routes explicit mode tools to the correct backend.

Terminal and browser modes are the completed M1 paths. Computer interaction is wired through
metadata and config but remains experimental until GUI/Cua environment selection
is fully first-class across entrypoints.

## 12. Tools and Skills

`agent/src/tool_registry.py` owns planner-visible tools and progressive skill
disclosure.

Default planner-visible tools:

- `environment_action`
- lifecycle tools from the lifecycle skill
- `use_skill` when optional skills exist

Lifecycle tools:

- `start_session`
- `end_session`
- `new_session`
- `refresh_session`
- `switch_session`
- `list_sessions`
- `end_task`

Optional skills:

- `code`: source inspection and temporary white-box debugging tools.
- `logs`: trajectory and runtime log inspection tools.

Skills are runtime prompt and tool disclosure assets under `agent/skills/*`.
They are not passive documentation. A skill is activated when the planner uses
`use_skill`, or automatically in full mode for selected diagnostics.

## 13. QA State: Coverage and Hypotheses

QA-specific strategy state lives in `agent/src/qa_state.py`.

### Coverage State

`CoverageState` records:

- Observed state keys.
- Actions attempted per state.
- Recent failed actions.
- State/action frontier summaries.

This helps the planner avoid repeated shallow exploration and makes exploration
coverage visible in reports.

### Hypothesis Manager

`HypothesisManager` tracks suspected bugs:

- Deduplicates similar findings.
- Stores confidence and status.
- Records evidence and reproduction steps.
- Promotes high-confidence findings to reproduced status.

Sources can include:

- Planner signal.
- Bug detector.
- Reflection.
- Reproducer subagent output as supporting evidence.

## 14. Isolated Worker Subagents

Worker subagents live in `agent/src/subagents.py`. They follow the same design
idea as modern coding harness subagents: tasks that would pollute the main
planner context run in isolated worker contexts and return concise structured
summaries.

Current workers:

- `ExplorerAgent`: reviews coverage summaries and proposes state-frontier
  targets.
- `ReproducerAgent`: converts a new bug hypothesis into a reproduction plan.
- `LogAnalystAgent`: reads log-tool output and compresses log evidence.
- `CodeLocalizerAgent`: reads code-search output and suggests likely files or
  symbols.

Isolation rules:

- Each worker invocation creates a fresh LLM agent id:
  `subagent.<name>.<call>`.
- Workers do not share main planner memory.
- Workers do not receive the full trace by default.
- The main planner receives only `subagent_summary`.
- Full worker prompts and raw outputs are excluded from run metadata unless
  `subagents.record_prompts=true`.

Subagent events are recorded as hook events:

```text
hook=on_subagent_result
event_type=Ran
```

Subagents are disabled in minimal mode and enabled in full mode by default.

## 15. Logs and White-Box Diagnostics

Logs and memory are separate concepts:

- Memory is agent-side context compression and retrieval.
- Logs are source-backed diagnostics from trajectory and runtime sources.

Log diagnostics:

- `agent/src/log_sources.py`: source declarations and readers.
- `agent/src/log_types.py`: normalized log/session types.
- `agent/src/log_analyzer.py`: anomaly analysis.
- `logs` skill: planner-visible log tools.

Code diagnostics:

- `agent/src/codebase_types.py`: `UniversalCodebaseAdapter`.
- `code` skill: source inspection, search, temporary write, and restore tools.
- Rooted under `/sandbox/software` by default.

Full mode can enable automatic log analysis and code localization. When
subagents are enabled, `LogAnalystAgent` and `CodeLocalizerAgent` compress those
tool outputs before the main planner sees them.

## 16. Hooks and Trajectory Events

Hooks provide stable observability labels for harness behavior. Hook events are
written to reports and `trace.jsonl` as `type="hook"` rows.

Stable event labels include:

- `RunStarted`
- `RunEnded`
- `Planning`
- `Planned`
- `PlanFailed`
- `Explored`
- `Ran`
- `Edited`
- `Lifecycle`
- `Covered`
- `Reported`
- `Summarized`
- `Diagnosed`

Important hook names:

- `on_run_start`
- `on_run_end`
- `before_plan`
- `after_plan`
- `before_tool_call`
- `after_tool_call`
- `after_step`
- `on_lifecycle_event`
- `on_bug_reported`
- `on_coverage_recorded`
- `on_subagent_result`
- `on_auto_log_analysis`
- `on_auto_code_lookup`

Minimal mode keeps observability hooks enabled while disabling diagnostic and
context-injection hook categories. Full mode enables diagnostic hook categories.

## 17. RunSpec and Reproducibility

Every run should export a `run_spec` in report metadata. It records:

- Task id, slug, and environment id.
- Interaction profile, primary mode, enabled modes, and backend type.
- Harness mode.
- Model role configuration.
- Agent loop policy.
- Operator policy.
- Memory policy.
- Tool policy.
- Hook policy.
- Subagent policy.
- Tool and skill registry policy.
- Redacted final resolved config and configuration layer provenance.

`run_spec` is the primary surface for controlled experiments and ablations
across interaction profiles, harness modes, models, and tool policies.

## 18. Artifacts and Reports

The raw harness reporter writes per-run reports under the configured report
directory. Harbor export then normalizes those into `/logs/agent/gbqa`.

Canonical agent artifacts:

- `run.json`
- `bugs.json` — normalized bug candidates with `evidence.expected_behavior`, `evidence.observed_fault`, and `evidence.minimal_reproduction`
- `steps.jsonl`
- `trace.jsonl`
- `report.md`
- `artifacts/`

Human-baseline bug files may store the same three fields at the top level. Export
and verifier code lift them into `evidence` through
`gbqa.protocol.schemas.normalize_bug_evidence(...)`.

Verifier outputs remain under `/logs/verifier`:

- `reward.json`
- `reward-details.json`
- `reward.txt`
- `gbqa_result.json`

The default verifier reward is value-based. It evaluates the top `n` reported
bugs, where `n` is the human-baseline bug count, verifies candidate bugs through
reasonable failing test cases, assigns impact/scope/reproducibility value tiers,
and scores `min(1.0, agent_value / human_value)`.

Do not move Harbor reward files or verifier outputs out of `/logs/verifier`.

## 19. Current Feature Matrix

| Feature | Minimal | Full |
| --- | --- | --- |
| Main planner/operator loop | yes | yes |
| Lifecycle tools | yes | yes |
| API interaction | yes, if profile enables it | yes, if profile enables it |
| Browser interaction | yes, if profile enables it | yes, if profile enables it |
| Computer-use interaction | experimental | experimental |
| Coverage state | yes | yes |
| Hypothesis manager | yes | yes |
| Reflection | policy controlled | policy controlled |
| Summary/memory compression | policy controlled | policy controlled |
| Code tools | no | yes |
| Log tools | no | yes |
| Auto log analysis | no | yes |
| Auto code lookup | no | yes |
| Worker subagents | no | yes |
| Hook observability | yes | yes |
| Diagnostic hooks | no | yes |
| Persistent memory carryover | no by default | policy controlled |

## 20. Extension Guidelines

When adding new harness capabilities:

- Add explicit config policy and include it in `run_spec`.
- Keep task-specific facts in `gbqa.yaml`, not harness code.
- Keep planner-visible tools generic and backend-agnostic.
- Prefer progressive skill disclosure for optional capabilities.
- Keep worker subagent outputs structured and concise.
- Do not feed full worker prompts or raw outputs back into the main planner by
  default.
- Preserve Harbor paths under `/logs/agent`, `/logs/verifier`, and `/sandbox`.
- Add focused tests for loop policy, run config rendering, and artifact output.

## 21. Common Execution Paths

Custom QA harness, terminal mode:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal
```

Default multi-mode profile:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=default
```

Full harness mode:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal \
  --ak harness_mode=full
```

Harbor built-in Claude Code task runner:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner claude-code \
  --gbqa-agent-model anthropic/claude-sonnet-4-6 \
  --gbqa-agent-auth subscription
```

Harbor built-in Codex task runner:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner codex \
  --gbqa-agent-model gpt-5 \
  --gbqa-agent-auth subscription \
  --gbqa-codex-auth-file "$HOME/.codex/auth.json"
```

Subscription-backed verifier judge with the custom QA harness:

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

## 22. Non-Goals

The current QA Agent Harness does not:

- Replace Harbor's trial runner or verifier system.
- Treat direct `harbor run` as the stable computer interaction entrypoint.
- Assume source-code access in minimal mode.
- Assume logs are memory.
- Float benchmark baselines automatically when upstream releases change.
- Store GBQA human-baseline bugs in the external target software repository.
