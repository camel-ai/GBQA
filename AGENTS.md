# GBQA Architecture Notes For Agents

This `AGENTS.md` file records the current architecture decisions for GBQA and should be read before changing sandbox, task packaging, agent harness, verifier, or environment code.

## Overview

The autonomous discovery of bugs remains a significant challenge in modern software development. Compared to code generation, the complexity of dynamic runtime environments makes bug discovery considerably harder for LLMs. A GBQA task points to a real GitHub software release, defines how that software should run in an isolated sandbox, exposes supported interaction modes, and provides verifier-owned ground truth for scoring.

## Milestone Planning

### M1

Milestone 1 is complete and remains the validated Daytona-first baseline:

- Harbor owns task packaging, trial execution, verifier execution, and artifact collection.
- Daytona owns remote sandbox lifecycle through Harbor's `daytona` environment provider.
- GBQA owns task metadata, QA agent harness behavior, normalized reports, and bug evaluation.
- Local Docker is not an M1 acceptance path.
- `GBQAHarborAgent` is the default custom Harbor agent wrapper.
- Dark Castle is the first external GitHub software task and is ready in the remote Daytona sandbox.
- API mode and browser mode are the completed interaction paths.
- Harbor-compatible verifier execution and GBQA artifact export are implemented.
- Parallel evaluation is available through Harbor's concurrent trial runner; in the Daytona path, this means multiple independent Daytona sandboxes can run at the same time.

The validated M1 topology is colocated:

- Harbor runs locally and controls the remote Daytona sandbox.
- The target software environment runs inside the Daytona sandbox.
- The GBQA agent harness is uploaded into the same Daytona sandbox and runs there.
- The verifier runs in the same Daytona sandbox after the agent finishes.

Validated smoke command:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; python -m gbqa.cli.harbor_run run --job-name gbqa-daytona-smoke-api-lf-fix -p gbqa/tasks/dark-castle -e daytona --agent-import-path gbqa.harbor.agent:GBQAHarborAgent --ak interaction_mode=api --ak max_steps=10
```

Validated result:

- Daytona provisioned the remote sandbox.
- Dark Castle started inside the sandbox.
- `GBQAHarborAgent` interacted with the environment through API mode for 10 steps.
- Harbor downloaded `/logs/agent/gbqa` artifacts.
- Verifier wrote `/logs/verifier/reward.txt`, `/logs/verifier/reward.json`, and `/logs/verifier/gbqa_result.json`.
- A 10-step smoke run may legitimately receive reward `0.0` if no ground-truth bug is found; this is not an infrastructure failure.

### M2

- M2: add additional QA harnesses such as `CodexHarborAgent` and `ClaudeCodeHarborAgent`.
- M2: add more verified benchmark environments and task manifests.
- M2: extend interaction beyond completed API/browser paths toward computer-use, and further free interaction mode (mixed interaction mode).
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

## Dark Castle as an example environment and QA Task

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

The current default QA agent harness lives under `agent/` and is wrapped for Harbor by:

- `gbqa.harbor.agent.GBQAHarborAgent`

The harness should stay task-generic:

- Use task/environment terminology in platform code.
- Avoid introducing new generic code with `game` naming.
- Game-specific naming is acceptable only inside external game software or task-specific metadata where the upstream API uses it, such as Dark Castle's `game_id` response field.

The rendered Harbor run config is produced by:

- `gbqa.harbor.config.render_agent_config(...)`

This config should contain harness policy only: model, reasoning, loop budgets, memory, interaction adapter config, and reporting. Task endpoints and software source belong in task metadata.

## Interaction Modes

Completed interaction modes:

- `api`
- `browser`

Both completed modes are tool-use paths, but they operate at different abstraction levels:

- API mode calls the target backend contract directly.
- Browser mode drives the frontend through Playwright MCP/runtime.

Planned post-M1 modes:

- `computer_use`
- free interaction mode (mixed interaction mode)

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
- `/logs/verifier/gbqa_result.json`

Core verifier entrypoints:

- `gbqa.verifier.evaluate_bug_report(...)`
- `gbqa.verifier.write_harbor_reward(...)`

Shell verifier scripts must use LF line endings. Windows CRLF checkouts can break Linux Daytona execution with `/usr/bin/env: 'bash\r': No such file or directory`. Keep `.gitattributes` enforcing:

```text
*.sh text eol=lf
```

## Current Package Boundaries

Use these directories for new platform code:

- `gbqa/spec/` or `gbqa/spec.py`: task metadata and schema loading.
- `gbqa/harbor/`: Harbor wrappers and integration glue.
- `gbqa/reporting/`: conversion from harness-specific reports to GBQA normalized artifacts.
- `gbqa/protocol/`: stable run/report/bug schemas.
- `gbqa/verifier.py`: verifier scoring and reward output.
- `gbqa/tasks/`: first-party Harbor-compatible task packages.
- `agent/`: current QA agent harness implementation.
- `environment/`: offline environment discovery, filtering, Daytona verification,
  human review, and task package generation. This directory is not part of the
  GBQA runtime package and must not be uploaded into Daytona during Harbor runs.

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

`agent/run_eval.py` is a legacy local helper and is not part of the M1 Harbor verifier contract. Do not include it in the standard M1 verification command. The benchmark verifier path is `tests/test.sh` -> task verifier -> `gbqa.verifier`.

Before claiming architecture or path changes are complete, run the commands for your operating system.

### Windows PowerShell

For environment-preparation changes, run:

```powershell
python -m unittest discover -s environment\tests -p "test_*.py" -v
```

```powershell
python -m compileall -q environment gbqa agent\src agent\run_agent.py
```

```powershell
$failed = @(); Get-ChildItem -Path agent\test -Filter 'test_*.py' | Sort-Object Name | ForEach-Object { python $_.FullName | Out-Null; if ($LASTEXITCODE -ne 0) { $failed += $_.Name } }; if ($failed.Count -gt 0) { Write-Host "FAILED:" ($failed -join ', '); exit 1 } else { Write-Host "all agent test scripts passed" }
```

For sandbox path changes, also run:

```powershell
rg -n "/opt/gbqa|/workspace" gbqa agent docs README.md pyproject.toml
```

Expected result for the path scan is no matches.

For Daytona smoke validation on Windows, keep UTF-8 output enabled so Rich/Harbor summary output does not fail under a GBK console:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; python -m gbqa.cli.harbor_run run --job-name gbqa-daytona-smoke-api-lf-fix -p gbqa/tasks/dark-castle -e daytona --agent-import-path gbqa.harbor.agent:GBQAHarborAgent --ak interaction_mode=api --ak max_steps=10
```

For parallel Daytona evaluation, use Harbor's concurrent trial runner. For example, five independent task environments can run in five independent Daytona sandboxes:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; python -m gbqa.cli.harbor_run run -p gbqa/tasks -e daytona --agent-import-path gbqa.harbor.agent:GBQAHarborAgent --ak interaction_mode=api --ak max_steps=10 --n-tasks 5 --n-concurrent 5
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

For sandbox path changes, also run:

```bash
rg -n "/opt/gbqa|/workspace" gbqa agent docs README.md pyproject.toml
```

Expected result for the path scan is no matches.

For Daytona smoke validation:

```bash
python -m gbqa.cli.harbor_run run --job-name gbqa-daytona-smoke-api -p gbqa/tasks/dark-castle -e daytona --agent-import-path gbqa.harbor.agent:GBQAHarborAgent --ak interaction_mode=api --ak max_steps=10
```

For parallel Daytona evaluation:

```bash
python -m gbqa.cli.harbor_run run -p gbqa/tasks -e daytona --agent-import-path gbqa.harbor.agent:GBQAHarborAgent --ak interaction_mode=api --ak max_steps=10 --n-tasks 5 --n-concurrent 5
```

`--n-concurrent` controls concurrent Harbor trials. In the Daytona path, concurrent trials mean multiple remote Daytona sandboxes, not multiple agents inside one sandbox.
