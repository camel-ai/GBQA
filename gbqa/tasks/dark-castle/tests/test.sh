#!/usr/bin/env bash
set -euo pipefail

AGENT_DIR="/logs/agent/gbqa"
VERIFIER_DIR="/logs/verifier"
GROUND_TRUTH="/tests/bugs/dark-castle.json"

mkdir -p "${VERIFIER_DIR}"
export PYTHONPATH="/sandbox:${PYTHONPATH:-}"
export GBQA_GROUND_TRUTH="${GROUND_TRUTH}"
export GBQA_MATCH_THRESHOLD="${GBQA_MATCH_THRESHOLD:-0.65}"

if [ -f "${AGENT_DIR}/bugs.json" ]; then
  export GBQA_BUGS_PATH="${AGENT_DIR}/bugs.json"
else
  export GBQA_BUGS_PATH="/tests/empty_bugs.json"
fi

PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"
"${PYTHON_BIN}" -m gbqa.rewards.runner \
  --tests-dir /tests \
  --workspace /sandbox \
  --out-dir "${VERIFIER_DIR}"
