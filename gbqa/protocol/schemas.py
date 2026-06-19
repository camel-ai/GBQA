"""Canonical GBQA QA artifact schemas and normalizers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.1"


def normalize_bug_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize bug evidence fields into the GBQA protocol shape."""

    raw_evidence = payload.get("evidence", {})
    evidence: dict[str, Any] = {}
    if isinstance(raw_evidence, dict):
        evidence.update(raw_evidence)
    elif raw_evidence not in (None, ""):
        evidence["raw"] = raw_evidence

    for key in (
        "expected_behavior",
        "observed_fault",
        "minimal_reproduction",
        "reproduction_steps",
    ):
        value = payload.get(key)
        if value not in (None, "", []):
            evidence.setdefault(key, value)

    expected = str(evidence.get("expected_behavior", "")).strip()
    if not expected:
        for alias in ("expected_outcome", "expected", "correct_behavior"):
            value = evidence.get(alias) or payload.get(alias)
            if value:
                expected = str(value).strip()
                break
    if expected:
        evidence["expected_behavior"] = expected

    observed = str(evidence.get("observed_fault", "")).strip()
    if not observed:
        for alias in ("actual_behavior", "failure", "assertion"):
            value = evidence.get(alias) or payload.get(alias)
            if value:
                observed = str(value).strip()
                break
    if observed:
        evidence["observed_fault"] = observed

    for alias in ("expected_outcome", "expected", "correct_behavior", "actual_behavior", "failure", "assertion"):
        evidence.pop(alias, None)

    return evidence


def normalize_bug_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a harness-specific bug candidate into the GBQA protocol shape."""

    tags = payload.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return {
        "id": str(payload.get("id", "")).strip(),
        "title": str(payload.get("title", "")).strip(),
        "description": str(payload.get("description", "")).strip(),
        "severity": str(payload.get("severity", "")).strip(),
        "evidence": normalize_bug_evidence(payload),
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
