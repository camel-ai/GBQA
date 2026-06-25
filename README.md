<div align="center">
  <h1>GBQA: Towards Industrial-Level Quality Assurance Evaluation for Agents</h1>
  <h3>Automated bug discovery in real-world software environments</h3>
  <p><em>An open-source benchmark framework for running agents against real GitHub software releases, letting agents explore the live environment, discover latent bugs, and receive verifier-backed QA scores.</em></p>
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/Framework-CAMEL-purple" alt="CAMEL"/>
  <img src="https://img.shields.io/github/stars/camel-ai/GBQA?style=social" alt="Stars"/>
  <img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"/>
</div>

## 📖 Overview

The autonomous discovery of bugs remains a significant challenge in modern software development. Compared to code generation, the complexity of dynamic runtime environments makes bug discovery considerably harder for LLMs. A GBQA instance points to a real GitHub software release, gives one targeted bug hint, defines how that software should run in an isolated sandbox, exposes supported interaction modes, and evaluates one issue report with rule-based function-level validation.

## 🚀 Quick Start

### 1. Install

GBQA requires Python 3.12 or newer.

```bash
pip install -e .
```

### 2. Configure Credentials

Create a root `.env` file from the template:

```bash
cp .env.example .env
```

Fill in the required runtime fields:

```env
DAYTONA_API_KEY=
# Required only for `-e modal` when ~/.modal.toml is not configured.
MODAL_TOKEN_ID=
MODAL_TOKEN_SECRET=
API_KEY=
BASE_URL=https://zenmux.ai/api/v1
MODEL_NAME=
GITHUB_TOKEN=
```

### 3. Start Evaluation With One Command

Run the default GBQA Harbor agent against a task package in a remote Daytona sandbox:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/<task-id> \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal \
  --ak max_steps=10
```

Modal can be used as the Harbor sandbox provider with the same GBQA task
package and agent harness. Authenticate Modal first with `modal token new` or
set `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` in `.env`, then switch only the
environment flag:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/<task-id> \
  -e modal \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal \
  --ak max_steps=10
```

`pip install -e .` installs Modal's API proxy support. This matters on machines
with `HTTP_PROXY` / `HTTPS_PROXY` or similar proxy variables set; without it the
Modal SDK can fail before sandbox creation with a missing `python-socks`
dependency.

Use `--ak max_steps=10` as a fast infrastructure smoke. Use a larger budget such
as `--ak max_steps=50` when checking whether the agent can reproduce the hinted
target bug and produce a function-level pinpoint. The default `minimal` harness
includes source-code tools because targeted GBQA rewards require pinpoint
evidence. Use `--ak harness_mode=full` only when the run should also exercise
logs, automatic diagnostics, and worker subagents.

Use browser interaction by switching the interaction mode:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/<task-id> \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=browser \
  --ak max_steps=10
```

> [!WARNING]
> Warning for  `computer`: computer interaction (experimental) needs a separate GUI/Cua environment image, so we recommend to use `python -m gbqa.cli.harbor_run run` for stable execution, `harbor run` cannot handle environment image selection and may raise errors.

### 3a. Optional Runner Selection

GBQA supports two task-running paths:

- `GBQAHarborAgent`, the custom QA harness. It uses provider-neutral `API_KEY`,
  `BASE_URL`, and `MODEL_NAME`.
- Harbor built-in CLI agents such as `codex` and `claude-code`. These can use
  Codex / Claude Code subscription auth.

Use the GBQA launcher selectors to choose the path:

```bash
# Custom GBQA QA harness
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal \
  --ak max_steps=10
```

```bash
# Harbor built-in Claude Code with subscription auth
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN="claude_oauth_..."
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  --gbqa-task-runner claude-code \
  --gbqa-agent-model anthropic/claude-sonnet-4-6 \
  --gbqa-agent-auth subscription
```

```bash
# Harbor built-in Codex with subscription auth
codex login
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle-key-fragment-combine \
  -e daytona \
  --gbqa-task-runner codex \
  --gbqa-agent-model gpt-5 \
  --gbqa-agent-auth subscription \
  --gbqa-codex-auth-file "$HOME/.codex/auth.json"
```

The task instruction tells generic CLI agents to start Dark Castle and write
`/logs/agent/gbqa/issue.json`, which is the verifier's preferred input. The GBQA
harness writes the same artifact through its final issue-report pass before
exit. A single-element legacy `bugs.json` is still accepted for compatibility.

See `docs/subscription-auth.md` for the Harbor task-runner subscription
authentication reference.

### 4. Run Batch Evaluations In Parallel

GBQA's `gbqa.cli.harbor_run` wrapper loads the root `.env` and forwards all arguments to Harbor. When a local path or registered dataset contains many task packages, Harbor can launch multiple remote sandboxes at the same time and run one evaluation per task environment. Daytona and Modal are selected with the native Harbor `-e daytona` or `-e modal` flag.

For example, once `gbqa/tasks` contains many verified task packages, run up to 100 task evaluations concurrently:

```bash
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks \
  -e daytona \
  --gbqa-task-runner gbqa \
  --ak interaction_mode=terminal \
  --ak max_steps=10 \
  --n-tasks 100 \
  --n-concurrent 100
```

Here `--n-concurrent` controls how many Harbor trials can run at once. With Daytona or Modal, that means many independent remote sandboxes can be active in parallel. It is not intended to create multiple concurrent agents inside the same task sandbox.

### 5. Outputs

For local Linux verification, run:

```bash
bash scripts/test-linux.sh
```

Set `GBQA_RUN_AGENT_SCRIPT_SMOKES=1` to also run the standalone
`agent/test/test_*.py` smoke scripts. Set `GBQA_RUN_NETWORK_SMOKES=1` only when
you intentionally want to include model/API network smoke tests.

In Harbor benchmark runs, evaluation is performed automatically by the verifier
phase after the agent writes normalized artifacts. The `agent/` harness does not
read target-bug verifier assets or compute benchmark scores.

GBQA's default verifier reward is targeted and binary. Each benchmark instance
has one known target bug and one selected agent-facing hint; official instance
data can store weak, medium, and strong hint variants for calibration. The
verifier reads the submitted issue report, checks required issue fields, and
gives reward `1.0` only when `report_status=complete` and the reported
pinpoint aligns with the target golden patch. Pinpoint can be a source location
or a SWE-style minimal patch/diff hunk.

- Agent artifacts: `/logs/agent/gbqa/run.json`, `/logs/agent/gbqa/issue.json`, `/logs/agent/gbqa/bugs.json`, `/logs/agent/gbqa/steps.jsonl`
- Each `issue.json` includes top-level `report_status`, `exit_status`, and `missing_fields`; the nested issue should include `expected_behavior`, `observed_fault`, `reproduction`, and source-level `pinpoint` via `locations[]` or `patch/diff`
- Harbor reward outputs: `/logs/verifier/reward.txt`, `/logs/verifier/reward.json`
- Full GBQA evaluation payload: `/logs/verifier/gbqa_result.json`

## Task Packages

Each benchmark instance is a Harbor-compatible package under `gbqa/tasks/<instance-id>`. Multiple instances may share the same upstream software release, but each instance has its own `instruction.md`, `gbqa.yaml`, target bug file, verifier entrypoint, and artifact contract. Running multiple instances launches multiple independent Harbor trials and remote sandboxes.

## Environment Preparation

Environment discovery and preparation live outside the runtime package in `environment/`. This offline toolchain searches GitHub repositories, detects deployable sub-environments, filters and ranks candidates, runs optional Daytona deployment verification, supports human review, and exports approved task packages into `gbqa/tasks`.

```bash
python -m environment.sourcing.cli run \
  --provider github \
  --query "archived:false fork:false stars:>=10 mirror:false" \
  --limit 500 \
  --top-k 100 \
  --output-dir environment/catalog/runs/dev
```

```bash
python -m environment.export.cli generate \
  --input environment/catalog/runs/dev/approved_task_seeds.jsonl \
  --output gbqa/tasks
```

## 🗺️Roadmap

### M1: Harbor + Daytona Remote Sandbox Baseline

- `GBQAHarborAgent` as the default custom QA agent wrapper.
- Example real GitHub software environment: Dark Castle in a remote Daytona sandbox.
- Terminal and browser interaction modes for the example task.
- Harbor-compatible verifier and reward outputs.

### M2: More Harnesses And More Environments

- Keep Harbor built-in `codex` and `claude-code` task runners selectable through
  `gbqa.cli.harbor_run`, including subscription auth.
- Add optional custom QA-harness wrappers such as `CodexHarborAgent` and
  `ClaudeCodeHarborAgent` if they provide GBQA-specific behavior beyond
  Harbor's built-in CLI agents.
- Support local sandbox + colocated agent.
- Support local agent + remote sandbox.
- Add more verified benchmark environments and task manifests.
- Keep Daytona and Modal selectable as Harbor-managed remote sandbox providers.
- Scale parallel evaluation across remote sandboxes.

### M3: Richer Interaction And Cross-Platform Sandboxes

- Support terminal, browser, computer, and mixed interaction methods, with task
  metadata recording concrete terminal surfaces such as API, CLI, or Python API.
- Extend sandbox support from Linux toward Windows and macOS.
- Run broader LLM evaluation experiments and release a leaderboard.

### M4: Training Data And RL

- Collect trajectory data.
- Standardize reward signals.
- Support RL training and optimization workflows.

## ✨ Contributing

Contributions are welcome. The highest-priority areas are new Harbor-compatible task packages, additional agent harness adapters, verifier improvements, and sandbox/runtime robustness.
