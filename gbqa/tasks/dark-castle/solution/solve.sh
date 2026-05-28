#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="/logs/agent/gbqa"
mkdir -p "${OUT_DIR}/artifacts"

cp /solution/oracle_bugs.json "${OUT_DIR}/bugs.json"

cat > "${OUT_DIR}/run.json" <<'JSON'
{
  "schema_version": "0.1",
  "game_id": "dark-castle",
  "source": "oracle",
  "summary": "Oracle report containing all known Dark Castle benchmark bugs.",
  "metadata": {
    "agent": "oracle"
  }
}
JSON

: > "${OUT_DIR}/steps.jsonl"
