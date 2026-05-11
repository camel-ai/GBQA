# Changelog

## 2025-05-12 — Sandbox Security, Memory & Evaluator Improvements

### 🔐 Encrypted Environment Variable Passing
- **New module**: `gbqa/crypto.py` — lightweight symmetric encryption using only Python stdlib (HMAC-SHA256 keystream + XOR, PBKDF2 key derivation).
- **Agent** (`gbqa/harbor/agent.py`): encrypts resolved runtime env (`API_KEY`, `BASE_URL`, `MODEL_NAME`) into `verifier_env.enc` before writing to the sandbox. The decryption key is stored separately in `.verifier_key`.
- **Verifier** (`gbqa/tasks/dark-castle/tests/gbqa_verifier.py`): decrypts the env on startup so the verifier can use LLM-based semantic matching without requiring separate `--ve` flags or leaving secrets in plaintext.

### 🧠 Larger Memory Window
- Increased `memory.max_short_term` from **30 → 100** in the Harbor-rendered runtime config (`gbqa/harbor/config.py`). This gives the agent a longer chat-history context, reducing repetitive exploration and forgotten state.

### ⏱ Extended Timeouts
- **Verifier timeout**: 180s → 600s (`task.toml`)
- **Agent timeout**: 1800s → 7200s (`task.toml`)
- Gives slower models (e.g. GPT-5.x) enough time to complete long exploration runs.

### 🐳 Dockerfile Slimming
- Switched base image from `ubuntu:24.04` to `python:3.13-slim`.
- Removed Node.js / npm / Playwright dependencies (not needed for API-mode runs).
- Added `build-essential`, `tmux`, `asciinema` for debugging convenience.

### 📝 Task Instruction Update
- Added explicit hint: *"After you have found several bugs, you should still try to reach the exit of the castle, instead of terminate."* This guides the agent to treat escape as a secondary objective.

### 🎯 Enhanced Verifier Scoring
- `gbqa/verifier.py` now attempts **LLM semantic matching** first (via `agent.src.evaluator.Evaluator`) when the agent evaluator package and env credentials are available.
- Falls back to the legacy `SequenceMatcher` implementation on any LLM failure, so scoring is never blocked.
- Diagnostics (`_diagnostics`, `_matcher_used`) are included in `reward.json` for transparency.
