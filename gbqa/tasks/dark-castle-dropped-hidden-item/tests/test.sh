#!/usr/bin/env bash
set -euo pipefail

AGENT_DIR="/logs/agent/gbqa"
VERIFIER_DIR="/logs/verifier"
GROUND_TRUTH="/tests/bugs/dark-castle.json"
RUNTIME_DIR="/tests/_gbqa_runtime"

mkdir -p "${VERIFIER_DIR}"
PYTHONPATH_ENTRIES=()
if [ -d "${RUNTIME_DIR}/gbqa" ]; then
  PYTHONPATH_ENTRIES+=("${RUNTIME_DIR}")
fi
if [ -d "/sandbox/gbqa" ]; then
  PYTHONPATH_ENTRIES+=("/sandbox")
fi
if [ -d "/solution/gbqa" ]; then
  PYTHONPATH_ENTRIES+=("/solution")
fi
PYTHONPATH_ENTRIES+=("/sandbox")
PYTHONPATH_PREFIX=""
for entry in "${PYTHONPATH_ENTRIES[@]}"; do
  if [ -z "${PYTHONPATH_PREFIX}" ]; then
    PYTHONPATH_PREFIX="${entry}"
  else
    PYTHONPATH_PREFIX="${PYTHONPATH_PREFIX}:${entry}"
  fi
done
export PYTHONPATH="${PYTHONPATH_PREFIX}:${PYTHONPATH:-}"
export GBQA_GROUND_TRUTH="${GROUND_TRUTH}"
export GBQA_EVAL_METHOD="${GBQA_EVAL_METHOD:-targeted_bug}"
export GBQA_TRAJECTORY_PATH="${GBQA_TRAJECTORY_PATH:-/logs/agent/gbqa/trace.jsonl}"
export GBQA_STEPS_PATH="${GBQA_STEPS_PATH:-/logs/agent/gbqa/steps.jsonl}"
export GBQA_ATIF_TRAJECTORY_PATH="${GBQA_ATIF_TRAJECTORY_PATH:-/logs/agent/trajectory.json}"

if [ -f "${AGENT_DIR}/issue.json" ]; then
  export GBQA_ISSUE_PATH="${AGENT_DIR}/issue.json"
  export GBQA_BUGS_PATH="${AGENT_DIR}/issue.json"
elif [ -f "${AGENT_DIR}/bugs.json" ]; then
  export GBQA_BUGS_PATH="${AGENT_DIR}/bugs.json"
else
  export GBQA_BUGS_PATH="/tests/empty_bugs.json"
fi

PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"
"${PYTHON_BIN}" -m gbqa.rewards.runner \
  --tests-dir /tests \
  --workspace /sandbox \
  --out-dir "${VERIFIER_DIR}" \
  --eval-method "${GBQA_EVAL_METHOD}"
