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

The autonomous discovery of bugs remains a significant challenge in modern software development. Compared to code generation, the complexity of dynamic runtime environments makes bug discovery considerably harder for LLMs. A GBQA task points to a real GitHub software release, defines how that software should run in an isolated sandbox, exposes supported interaction modes, and provides verifier-owned human-baseline bugs plus value criteria for scoring.

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
API_KEY=
BASE_URL=https://zenmux.ai/api/v1
MODEL_NAME=
REWARDKIT_JUDGE=openai/gpt-4o
OPENAI_API_KEY=
OPENAI_API_BASE=https://zenmux.ai/api/v1
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

### 3a. Optional Runner And Judge Selection

GBQA supports two task-running paths:

- `GBQAHarborAgent`, the custom QA harness. It uses provider-neutral `API_KEY`,
  `BASE_URL`, and `MODEL_NAME`.
- Harbor built-in CLI agents such as `codex` and `claude-code`. These can use
  Codex / Claude Code subscription auth.

Use the GBQA launcher selectors to choose the path:

```bash
# Custom GBQA QA harness
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
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
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner claude-code \
  --gbqa-agent-model anthropic/claude-sonnet-4-6 \
  --gbqa-agent-auth subscription
```

```bash
# Harbor built-in Codex with subscription auth
codex login
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner codex \
  --gbqa-agent-model gpt-5 \
  --gbqa-agent-auth subscription \
  --gbqa-codex-auth-file "$HOME/.codex/auth.json"
```

The task instruction tells generic CLI agents to start Dark Castle and write
`/logs/agent/gbqa/bugs.json`, which is the verifier input.

The verifier judge is independently selectable. API-key scoring remains
supported with `REWARDKIT_JUDGE=openai/<model>` plus `OPENAI_API_KEY` and
`OPENAI_API_BASE`. Subscription-backed judges use RewardKit agent judges:

```bash
# Claude Code judge for optional value-evaluation review
export CLAUDE_CODE_OAUTH_TOKEN="claude_oauth_..."
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --gbqa-judge claude-code \
  --gbqa-judge-model claude-opus-4-7 \
  --gbqa-judge-auth subscription
```

```bash
# Codex judge for optional value-evaluation review inside the verifier container
python -m gbqa.cli.harbor_run run \
  -p gbqa/tasks/dark-castle \
  -e daytona \
  --gbqa-task-runner gbqa \
  --gbqa-judge codex \
  --gbqa-judge-model gpt-5.5 \
  --gbqa-judge-auth subscription \
  --gbqa-codex-auth-file "$HOME/.codex/auth.json"
```

See `docs/subscription-auth.md` for the full Harbor/Rewardkit subscription
authentication reference.

### 4. Run Batch Evaluations In Parallel

GBQA's `gbqa.cli.harbor_run` wrapper loads the root `.env` and forwards all arguments to Harbor. When a local path or registered dataset contains many task packages, Harbor can launch multiple Daytona sandboxes at the same time and run one evaluation per task environment.

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

Here `--n-concurrent` controls how many Harbor trials can run at once. In the Daytona path, that means many independent remote sandboxes can be active in parallel. It is not intended to create multiple concurrent agents inside the same task sandbox.

### 5. Outputs

In Harbor benchmark runs, evaluation is performed automatically by the verifier
phase after the agent writes normalized artifacts. The `agent/` harness does not
read human-baseline verifier assets or compute benchmark scores.

GBQA's default verifier reward is value-based. The task human baseline is treated
as a pre-scored human baseline, not as the only bug oracle. The verifier
evaluates the top `n` reported candidate bugs, where `n` is the number of human
baseline bugs, verifies reasonable failing test cases, assigns impact/scope/
reproducibility value tiers, and returns `min(1.0, agent_value / human_value)`.

- Agent artifacts: `/logs/agent/gbqa/run.json`, `/logs/agent/gbqa/bugs.json`, `/logs/agent/gbqa/steps.jsonl`
- Each bug report should include `evidence.expected_behavior`, `evidence.observed_fault`, and `evidence.minimal_reproduction`
- Harbor reward outputs: `/logs/verifier/reward.txt`, `/logs/verifier/reward.json`
- Full GBQA evaluation payload: `/logs/verifier/gbqa_result.json`

## Task Packages

Each benchmark task is a Harbor-compatible package under `gbqa/tasks/<task-id>`. The task package defines the GitHub software release, sandbox runtime assets, interaction modes, verifier entrypoint, human-baseline bug file, precomputed baseline value file, validation cases, and artifact contract.

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
- Scale parallel evaluation in Daytona sandboxes.

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
