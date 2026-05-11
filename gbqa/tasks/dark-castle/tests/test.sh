#!/usr/bin/env bash
set -euo pipefail

AGENT_DIR="/logs/agent/gbqa"
VERIFIER_DIR="/logs/verifier"
GROUND_TRUTH="/tests/bugs/dark-castle.json"

mkdir -p "${VERIFIER_DIR}"

PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"
export PYTHONPATH="${PYTHONPATH:-}:/sandbox"

if [ -f "${AGENT_DIR}/bugs.json" ]; then
  "${PYTHON_BIN}" /tests/gbqa_verifier.py \
    --bugs "${AGENT_DIR}/bugs.json" \
    --ground-truth "${GROUND_TRUTH}" \
    --out-dir "${VERIFIER_DIR}"
else
  "${PYTHON_BIN}" /tests/gbqa_verifier.py \
    --bugs /tests/empty_bugs.json \
    --ground-truth "${GROUND_TRUTH}" \
    --out-dir "${VERIFIER_DIR}"
fi
