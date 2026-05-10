"""Canonical GBQA QA artifact schemas and normalizers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.1"


def normalize_bug_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a harness-specific bug candidate into the GBQA protocol shape."""

    evidence = payload.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {"raw": evidence}
    tags = payload.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return {
        "id": str(payload.get("id", "")).strip(),
        "title": str(payload.get("title", "")).strip(),
        "description": str(payload.get("description", "")).strip(),
        "confidence": float(payload.get("confidence", 0.0) or 0.0),
        "severity": str(payload.get("severity", "")).strip(),
        "evidence": evidence,
        "reproduction_hints": payload.get("reproduction_hints", []),
        "status": str(payload.get("status", "candidate")).strip() or "candidate",
        "tags": [str(tag) for tag in tags if str(tag).strip()],
    }


def normalize_step_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one harness step record for `steps.jsonl`."""

    return {
        "step": payload.get("step"),
        "action": payload.get("action", {}),
        "observation": payload.get("observation", payload.get("environment", {})),
        "artifacts": _extract_artifacts(payload),
        "raw": payload,
    }


def load_bug_candidates(path: str | Path) -> list[dict[str, Any]]:
    """Load GBQA protocol bug candidates from a file or artifact directory."""

    bug_path = Path(path)
    if bug_path.is_dir():
        bug_path = bug_path / "bugs.json"
    with bug_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        raw_bugs = payload.get("bugs", [])
    elif isinstance(payload, list):
        raw_bugs = payload
    else:
        raw_bugs = []
    return [
        normalize_bug_candidate(bug)
        for bug in raw_bugs
        if isinstance(bug, dict)
    ]


def _extract_artifacts(payload: dict[str, Any]) -> dict[str, Any]:
    environment = payload.get("environment", {})
    if isinstance(environment, dict):
        artifacts = environment.get("artifacts", {})
        if isinstance(artifacts, dict):
            return artifacts
    artifacts = payload.get("artifacts", {})
    return artifacts if isinstance(artifacts, dict) else {}
