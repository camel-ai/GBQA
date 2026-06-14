#!/usr/bin/env bash
set -euo pipefail

AGENT_DIR="/logs/agent/gbqa"
VERIFIER_DIR="/logs/verifier"
GROUND_TRUTH="/tests/bugs/dark-castle.json"

mkdir -p "${VERIFIER_DIR}"
export PYTHONPATH="/sandbox:${PYTHONPATH:-}"
export GBQA_GROUND_TRUTH="${GROUND_TRUTH}"
export GBQA_MATCH_THRESHOLD="${GBQA_MATCH_THRESHOLD:-0.65}"
export GBQA_TRAJECTORY_PATH="${GBQA_TRAJECTORY_PATH:-/logs/agent/gbqa/trace.jsonl}"
export GBQA_STEPS_PATH="${GBQA_STEPS_PATH:-/logs/agent/gbqa/steps.jsonl}"

if { [ -z "${REWARDKIT_JUDGE:-}" ] || [ "${REWARDKIT_JUDGE:-}" = "openai/gpt-4o" ]; } && [ -n "${JUDGE_AGENT:-}" ]; then
  export REWARDKIT_JUDGE="${JUDGE_AGENT}"
fi

if [ -z "${REWARDKIT_MODEL:-}" ]; then
  if [ "${REWARDKIT_JUDGE:-}" = "codex" ] && [ -n "${JUDGE_CODEX_MODEL:-}" ]; then
    export REWARDKIT_MODEL="${JUDGE_CODEX_MODEL}"
  elif [ -n "${JUDGE_MODEL:-}" ]; then
    export REWARDKIT_MODEL="${JUDGE_MODEL}"
  fi
fi

case "${CLAUDE_FORCE_OAUTH:-${REWARDKIT_FORCE_OAUTH:-}}" in
  1|true|TRUE|yes|YES|on|ON)
    unset ANTHROPIC_API_KEY
    unset ANTHROPIC_AUTH_TOKEN
    ;;
esac

if [ "${REWARDKIT_JUDGE:-}" = "codex" ]; then
  case "${REWARDKIT_FORCE_OAUTH:-}" in
    1|true|TRUE|yes|YES|on|ON)
      unset OPENAI_API_KEY
      unset OPENAI_API_BASE
      unset OPENAI_BASE_URL
      ;;
  esac
fi

if [ -f "${AGENT_DIR}/bugs.json" ]; then
  export GBQA_BUGS_PATH="${AGENT_DIR}/bugs.json"
else
  export GBQA_BUGS_PATH="/tests/empty_bugs.json"
fi

if [ -n "${CODEX_AUTH_JSON_B64:-}" ]; then
  export CODEX_HOME="${CODEX_HOME:-/tmp/gbqa-codex-home}"
  mkdir -p "${CODEX_HOME}"
  printf '%s' "${CODEX_AUTH_JSON_B64}" | base64 -d > "${CODEX_HOME}/auth.json"
  chmod 600 "${CODEX_HOME}/auth.json"
elif [ -n "${CODEX_AUTH_JSON_PATH:-}" ] && [ -f "${CODEX_AUTH_JSON_PATH}" ]; then
  export CODEX_HOME="${CODEX_HOME:-/tmp/gbqa-codex-home}"
  mkdir -p "${CODEX_HOME}"
  cp "${CODEX_AUTH_JSON_PATH}" "${CODEX_HOME}/auth.json"
  chmod 600 "${CODEX_HOME}/auth.json"
fi

PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"
"${PYTHON_BIN}" -m gbqa.rewards.runner \
  --tests-dir /tests \
  --workspace /sandbox \
  --out-dir "${VERIFIER_DIR}"
