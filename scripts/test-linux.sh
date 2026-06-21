#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python -m unittest discover -s environment/tests -p "test_*.py" -v
python -m compileall -q environment gbqa agent/src agent/run_agent.py

python -m pytest \
  agent/test/test_prompt_render.py \
  agent/test/test_log_sources.py \
  agent/test/test_log_analysis_tool.py \
  agent/test/test_code_tool_loop.py \
  agent/test/test_run_agent_endpoints.py \
  agent/test/test_gbqa_harbor.py

if [[ "${GBQA_RUN_AGENT_SCRIPT_SMOKES:-0}" == "1" ]]; then
  script_timeout_seconds="${GBQA_AGENT_SCRIPT_TIMEOUT_SECONDS:-120}"
  failed=()
  for test_file in $(find agent/test -maxdepth 1 -name 'test_*.py' | sort); do
    if [[ "$(basename "$test_file")" == "test_api_call.py" && "${GBQA_RUN_NETWORK_SMOKES:-0}" != "1" ]]; then
      echo "skipping $(basename "$test_file") (set GBQA_RUN_NETWORK_SMOKES=1 to include)"
      continue
    fi
    timeout "$script_timeout_seconds" python "$test_file" >/dev/null || failed+=("$(basename "$test_file")")
  done
  if [[ "${#failed[@]}" -gt 0 ]]; then
    printf 'FAILED: %s\n' "${failed[*]}"
    exit 1
  fi
  echo "all enabled agent test scripts passed"
fi

if [[ "${GBQA_CHECK_SANDBOX_PATHS:-0}" == "1" ]]; then
  rg -n "/opt/gbqa|/workspace" gbqa agent docs README.md pyproject.toml
fi
