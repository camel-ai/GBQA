<div align="center">
  <h1>GBQA: A Game Benchmark for Evaluating LLMs as Quality Assurance Engineers</h1>
  <h3>Automated game bug discovery and benchmark evaluation</h3>
  <p><em>A research-oriented framework for running agents against interactive games, discovering gameplay bugs, and evaluating the ability of autonomous bug discovery.</em></p>
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/Framework-CAMEL-purple" alt="CAMEL"/>
  <img src="https://img.shields.io/badge/Status-Research%20Prototype-success" alt="Status"/>
</div>



## 📖 Overview

The autonomous discovery of bugs remains a significant challenge in modern software development. Compared to code generation, the complexity of dynamic runtime environments makes bug discovery considerably harder for LLMs. So we take game development as a representative domain and introduce **GBQA**, a benchmark containing game environments and implanted bugs across difficulty levels, to evaluate whether LLMs can autonomously detect software bugs. The benchmark is constructed using a multi-agent system that develops games and injects bugs in a scalable manner, with human experts in the loop to ensure correctness. Moreover, we provide a baseline interactive agent equipped with a multi-round ReAct loop and a memory mechanism, enabling long-horizon exploration of game environments for bug detection across different LLMs. We believe this benchmark provides an adequate testbed and evaluation criterion, and that further progress on it will help close the gap in autonomous software engineering.

**The shift from standard code generation to active quality assurance testing marks a highly significant contribution to the field.**



## 🚀 Quick Start

### 1. Environment Setup

GBQA requires Python 3.12 or newer because the Harbor runtime dependency requires Python 3.12+.

```bash
pip install -e .
```

### 2. API Key Configuration

Run `cp .env.example .env` from the repository root, then open the root `.env` file and provide your own runtime credentials. This is the only env template used by the legacy agent, Harbor wrapper, Daytona sandbox setup, and sourcing tools.

```env
DAYTONA_API_KEY=
API_KEY=
BASE_URL=https://zenmux.ai/api/v1
MODEL_NAME=
GITHUB_TOKEN=
```

### 3. Start the Target Software

Milestone 1 treats Dark Castle as a real external GitHub software repository instead of local benchmark source. The Harbor task metadata records the selected baseline release:

- Repository: `https://github.com/Tsumugii24/dark-castle`
- Version policy: `latest_minus_one`
- Selected sandbox version: `v0.1.0`
- Current fixed reference release: `v0.2.0`

In the Daytona path, `gbqa/tasks/dark-castle/environment/Dockerfile` downloads the `v0.1.0` release archive into `/sandbox/software/dark-castle`. The Harbor agent uploads the GBQA runtime to `/sandbox/agent` and `/sandbox/gbqa`, then writes run artifacts through Harbor's `/logs` contract.

### 4. Run Agent Interaction

#### Configuration

Run `cp config.yaml.example config.yaml` 

Most runtime settings live in `agent/config.yaml`, including:

- LLM credentials and sampling parameters
- agent loop limits and reflection thresholds
- memory settings for summarization and cross-session retrieval
- execution backend policy for the current QA agent harness

Task and environment metadata live with each Harbor-compatible task package. For the bundled target, the source of truth is `gbqa/tasks/dark-castle/gbqa.yaml`, which defines the GitHub software release, service endpoints, interaction modes, ground truth, and artifact contract.

Back in the `agent/` directory:

```bash
python run_agent.py \
  --task dark-castle \
  --config config.yaml \
  --task-metadata ../gbqa/tasks/dark-castle/gbqa.yaml \
  --max-steps 50
```

`run_agent.py` always reads credentials from the repository-root `.env`, even when launched from `agent/`.

#### Output Artifacts

Each run produces a timestamped directory under `agent/reports/<task_slug>/`:

- `report.json`: structured JSON report
- `report.md`: concise human-readable report
- `trace.jsonl`: step-by-step trace, bug events, and summaries

Session memory is stored under `agent/memory/<task_slug>/`, including chat history and summary logs for later inspection.

### 5. Evaluation

In Harbor benchmark runs, evaluation is performed automatically by the verifier phase after the agent writes normalized artifacts. The verifier reads the configured ground-truth bug file, writes Harbor-facing reward outputs to `/logs/verifier/reward.txt` and `/logs/verifier/reward.json`, and preserves the full GBQA evaluation payload in `/logs/verifier/gbqa_result.json`.

You can also evaluate a report explicitly:

```bash
cd agent
python run_eval.py --task dark-castle --report reports/dark-castle/<run_id>/report.md
```



## ✨ Contribution

Upcoming Features & Contributions

> We welcome community contributions! Join us in building these exciting features.



## 🗺️Roadmap

- [ ] Action Space to Computer Use
- [ ] Game Environment Automatic Scaling
- [ ] More Functions for QA Agent

