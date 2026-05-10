# GBQA Architecture Notes For Agents

This file records the current architecture decisions for GBQA and should be read before changing sandbox, task packaging, agent harness, verifier, or environment code.

## Current Direction

GBQA is being refactored from a game-specific prototype into a Harbor-compatible software QA benchmark platform.

Milestone 1 is Daytona-first:

- Harbor owns task packaging, trial execution, verifier execution, and artifact collection.
- Daytona owns remote sandbox lifecycle through Harbor's `daytona` environment provider.
- GBQA owns task metadata, QA agent harness behavior, normalized reports, and bug evaluation.
- Local Docker is not an M1 acceptance path.
- Cua and computer-use integration are future work, not part of M1.

The default M1 topology is colocated:

- Harbor runs locally and controls the remote Daytona sandbox.
- The target software environment runs inside the Daytona sandbox.
- The GBQA agent harness is uploaded into the same Daytona sandbox and runs there.
- The verifier runs in the same Daytona sandbox after the agent finishes.

Long term, GBQA may support external-agent topology, but M1 prioritizes a reliable remote sandbox loop.

## Harbor Boundary

Keep GBQA compatible with Harbor instead of replacing Harbor's job/trial system.

Harbor task packages use this structure:

- `task.toml`: Harbor-compatible task metadata, runtime resource requirements, agent/verifier timeout, environment config.
- `instruction.md`: agent-facing instruction.
- `environment/`: environment definition, normally `Dockerfile`.
- `tests/`: verifier entrypoint and verifier assets.
- `solution/`: oracle solution assets.
- `bugs/`: GBQA ground-truth bug definitions.
- `gbqa.yaml`: GBQA-specific metadata that Harbor does not own.

Harbor's standard in-sandbox paths must remain stable:

- `/logs/agent`: agent logs and trajectories.
- `/logs/verifier`: verifier outputs, including `reward.txt` and `reward.json`.
- `/logs/artifacts`: extra collected artifacts.
- `/tests`: verifier files uploaded by Harbor before verification.
- `/solution`: oracle files uploaded by Harbor when using the oracle agent.

Do not move Harbor reward files or verifier outputs out of `/logs/verifier`.

## Daytona Sandbox Layout

Daytona is the remote isolation boundary. Inside that boundary, GBQA uses `/sandbox` as its runtime workspace.

Current GBQA sandbox layout:

```text
/sandbox/
  software/
    dark-castle/
  agent/
  gbqa/
  runtime/
    config.yaml

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
- `/sandbox/runtime/config.yaml` contains the rendered run config for the current Harbor trial.
- `/logs/agent/gbqa` contains normalized GBQA run artifacts.
- `/logs/verifier` contains Harbor-compatible reward outputs.

Do not reintroduce `/opt/gbqa` as the GBQA runtime root.

## Dark Castle M1 Task

Dark Castle is now treated as a real external GitHub software repository, not as benchmark-local source code.

Repository:

- `https://github.com/Tsumugii24/dark-castle`

Release policy:

- Latest fixed reference release: `v0.2.0`
- Selected buggy sandbox baseline: `v0.1.0`
- Selection role: `latest_minus_one`
- Archive URL: `https://github.com/Tsumugii24/dark-castle/archive/refs/tags/v0.1.0.tar.gz`

The GitHub software repository must not contain GBQA ground-truth `bugs/` files. Ground truth belongs in the GBQA task package:

- `gbqa/tasks/dark-castle/bugs/dark-castle.json`

The task metadata source of truth is:

- `gbqa/tasks/dark-castle/gbqa.yaml`

The Harbor-facing mirror metadata is:

- `gbqa/tasks/dark-castle/task.toml`

If a new Dark Castle release is created, do not automatically float the benchmark baseline. Update the selected release explicitly for reproducibility.

## Agent Harness Boundary

The current QA agent harness lives under `agent/` and is wrapped for Harbor by:

- `gbqa.harbor.agent.GBQAHarborAgent`

The harness should stay task-generic:

- Use task/environment terminology in platform code.
- Avoid introducing new generic code with `game` naming.
- Game-specific naming is acceptable only inside external game software or task-specific metadata where the upstream API uses it, such as Dark Castle's `game_id` response field.

The rendered Harbor run config is produced by:

- `gbqa.harbor.config.render_agent_config(...)`

This config should contain harness policy only: model, reasoning, loop budgets, memory, interaction adapter config, and reporting. Task endpoints and software source belong in task metadata.

## Interaction Modes

M1 supports:

- `api`
- `browser`

API mode targets:

- `http://127.0.0.1:5000/api/agent`

Browser mode targets:

- `http://127.0.0.1:5000/`

Both are tool-use paths, but they operate at different abstraction levels:

- API mode calls the target backend contract directly.
- Browser mode drives the frontend through Playwright MCP/runtime.

The agent planner/operator should target normalized capabilities, not provider-specific implementation details.

Logs are optional environment diagnostics. They are not the same as memory:

- Memory is agent-side context compression and retrieval.
- Logs are environment/runtime-side diagnostics exposed as an optional tool capability.

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

## Report And Verifier Contract

Every GBQA run should export normalized artifacts under `/logs/agent/gbqa`:

- `run.json`
- `bugs.json`
- `steps.jsonl`
- `trace.jsonl` when available
- `report.md` when available
- `artifacts/` for screenshots, traces, DOM dumps, or other interaction files

The verifier reads GBQA artifacts and ground truth, then writes Harbor-compatible outputs:

- `/logs/verifier/reward.txt`
- `/logs/verifier/reward.json`

Core verifier entrypoints:

- `gbqa.verifier.evaluate_bug_report(...)`
- `gbqa.verifier.write_harbor_reward(...)`

## Current Package Boundaries

Use these directories for new platform code:

- `gbqa/spec/` or `gbqa/spec.py`: task metadata and schema loading.
- `gbqa/harbor/`: Harbor wrappers and integration glue.
- `gbqa/reporting/`: conversion from harness-specific reports to GBQA normalized artifacts.
- `gbqa/protocol/`: stable run/report/bug schemas.
- `gbqa/verifier.py`: verifier scoring and reward output.
- `gbqa/tasks/`: first-party Harbor-compatible task packages.
- `agent/`: current QA agent harness implementation.

Avoid adding new platform concepts under `hub/`. `hub/dark-castle` is no longer the M1 software source.

## Verification Commands

Before claiming architecture or path changes are complete, run:

```powershell
python -m compileall -q gbqa agent\src agent\run_agent.py agent\run_eval.py
```

```powershell
$failed = @(); Get-ChildItem -Path agent\test -Filter 'test_*.py' | Sort-Object Name | ForEach-Object { python $_.FullName | Out-Null; if ($LASTEXITCODE -ne 0) { $failed += $_.Name } }; if ($failed.Count -gt 0) { Write-Host "FAILED:" ($failed -join ', '); exit 1 } else { Write-Host "all agent test scripts passed" }
```

For sandbox path changes, also run:

```powershell
rg -n "/opt/gbqa|/workspace" gbqa agent docs README.md pyproject.toml
```

Expected result for the path scan is no matches.

## Non-Goals For M1

- No local Docker acceptance path.
- No Cua integration.
- No Windows/macOS computer-use baseline.
- No custom GBQA replacement for Harbor jobs/trials/providers.
- No automatic floating to the latest GitHub release.
- No ground-truth bug files inside the external software repository.
