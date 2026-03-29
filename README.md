<div align="center">
  <h1>GBQA: A Game Benchmark for Evaluating LLMs as Quality Assurance Engineers</h1>
  <h3>Automated game bug discovery and benchmark evaluation</h3>
  <p><em>A research-oriented framework for running agents against interactive games, discovering gameplay bugs, and evaluating the ability of autonomous bug discovery.</em></p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/Framework-CAMEL-purple" alt="CAMEL"/>
  <img src="https://img.shields.io/badge/Status-Research%20Prototype-success" alt="Status"/>
</div>



## 📖 Overview

The autonomous discovery of bugs remains a significant challenge in modern software development. Compared to code generation, the complexity of dynamic runtime environments makes bug discovery considerably harder for LLMs. So we take game development as a representative domain and introduce **GBQA**, a benchmark containing game environments and implanted bugs across difficulty levels, to evaluate whether LLMs can autonomously detect software bugs. The benchmark is constructed using a multi-agent system that develops games and injects bugs in a scalable manner, with human experts in the loop to ensure correctness. Moreover, we provide a baseline interactive agent equipped with a multi-round ReAct loop and a memory mechanism, enabling long-horizon exploration of game environments for bug detection across different LLMs. We believe this benchmark provides an adequate testbed and evaluation criterion, and that further progress on it will help close the gap in autonomous software engineering.

**The shift from standard code generation to active quality assurance testing marks a highly significant contribution to the field.**



## 🚀 Quick Start

### 1. Environment Setup

```bash
cd agent
pip install -r requirements.txt
```

### 2. API Key Configuration

Run `cp .env.example .env ` , then open the `.env` file and provide your own model credentials:

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
```

### 3. Start the Game Server

```bash
cd hub/dark-castle/backend
pip install -r requirements.txt
python app.py
```

The game server will start on `http://localhost:5000`, and the browser frontend is available at the same host.

### 4. Run Agent Interaction

#### Configuration

Run `cp config.yaml.example config.yaml` 

Most runtime settings live in `agent/config.yaml`, including:

- LLM credentials and sampling parameters
- agent loop limits and reflection thresholds
- memory settings for summarization and cross-session retrieval
- registered game targets and their API endpoints
- evaluation and bug-detection thresholds

The default bundled target is `dark-castle`, but the config is structured so additional games can be added through the same API contract.

Back in the `agent/` directory:

```bash
python run_agent.py --game dark-castle --config config.yaml --max-steps 50
```

#### Output Artifacts

Each run produces a timestamped directory under `agent/reports/<game_id>/`:

- `report.json`: structured JSON report
- `report.md`: concise human-readable report
- `trace.jsonl`: step-by-step trace, bug events, and summaries

Session memory is stored under `agent/memory/<game_id>/`, including chat history and summary logs for later inspection.

### 5. Evaluation

If the target game has a ground-truth bug file configured, the agent run will automatically attach evaluation results to the report metadata.

You can also evaluate a report explicitly:

```bash
cd agent
python run_eval.py --game dark-castle --report reports/dark-castle/<run_id>/report.md
```



## ✨ Contribution

Upcoming Features & Contributions

> We welcome community contributions! Join us in building these exciting features.



## 🗺️Roadmap

- [ ] Action Space to Computer Use
- [ ] Game Environment Automatic Scaling
- [ ] More Functions for QA Agent

