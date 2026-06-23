#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="/logs/agent/gbqa"
mkdir -p "${OUT_DIR}/artifacts"

cp /solution/oracle_issue.json "${OUT_DIR}/issue.json"
cp /solution/oracle_issue.json "${OUT_DIR}/bugs.json"

cat > "${OUT_DIR}/run.json" <<'JSON'
{
  "schema_version": "0.2",
  "task_id": "gbqa/dark-castle-key-fragment-combine",
  "source": "oracle",
  "summary": "Oracle issue report for the targeted Dark Castle instance.",
  "metadata": {
    "agent": "oracle"
  }
}
JSON

: > "${OUT_DIR}/steps.jsonl"
