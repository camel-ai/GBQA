"""Canonical GBQA QA artifact schemas and normalizers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.2"

ISSUE_REQUIRED_FIELDS = (
    "title",
    "description",
    "expected_behavior",
    "observed_fault",
    "reproduction",
    "pinpoint",
)


def normalize_bug_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize bug evidence fields into the GBQA issue-report shape."""

    raw_evidence = payload.get("evidence", {})
    evidence: dict[str, Any] = {}
    if isinstance(raw_evidence, dict):
        evidence.update(raw_evidence)
    elif raw_evidence not in (None, ""):
        evidence["raw"] = raw_evidence

    for key in (
        "expected_behavior",
        "observed_fault",
        "obeserved_fault",
        "reproduction",
        "minimal_reproduction",
        "reproduction_steps",
        "pinpoint",
        "root_cause",
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

    observed = str(
        evidence.get("observed_fault") or evidence.get("obeserved_fault") or ""
    ).strip()
    if not observed:
        for alias in ("actual_behavior", "failure", "assertion", "obeserved_fault"):
            value = evidence.get(alias) or payload.get(alias)
            if value:
                observed = str(value).strip()
                break
    if observed:
        evidence["observed_fault"] = observed

    reproduction = evidence.get("reproduction")
    if reproduction in (None, "", []):
        for alias in ("minimal_reproduction", "reproduction_steps"):
            value = evidence.get(alias) or payload.get(alias)
            if value not in (None, "", []):
                reproduction = value
                break
    if reproduction not in (None, "", []):
        evidence["reproduction"] = _string_list(reproduction)

    pinpoint = evidence.get("pinpoint")
    if pinpoint in (None, "", {}, []):
        pinpoint = evidence.get("root_cause") or payload.get("root_cause")
    if pinpoint not in (None, "", {}, []):
        evidence["pinpoint"] = pinpoint

    for alias in (
        "expected_outcome",
        "expected",
        "correct_behavior",
        "actual_behavior",
        "failure",
        "assertion",
        "obeserved_fault",
    ):
        evidence.pop(alias, None)

    return evidence


def normalize_issue_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one reported open-source-style issue for GBQA targeted eval."""

    evidence = normalize_bug_evidence(payload)
    expected = str(evidence.get("expected_behavior", "")).strip()
    observed = str(evidence.get("observed_fault", "")).strip()
    reproduction = _string_list(evidence.get("reproduction"))
    pinpoint = evidence.get("pinpoint") or payload.get("pinpoint") or {}
    root_cause = payload.get("root_cause")
    if root_cause in (None, "") and isinstance(pinpoint, str):
        root_cause = pinpoint
    normalized = {
        "id": str(payload.get("id", "")).strip(),
        "title": str(payload.get("title", "")).strip(),
        "description": str(payload.get("description", "")).strip(),
        "expected_behavior": expected,
        "observed_fault": observed,
        "reproduction": reproduction,
        "pinpoint": pinpoint,
        "root_cause": root_cause if root_cause not in (None, "") else "",
        "evidence": evidence,
        "status": str(payload.get("status", "candidate")).strip() or "candidate",
        "tags": _string_list(payload.get("tags")),
    }
    if not normalized["description"]:
        normalized["description"] = normalized["observed_fault"]
    return normalized


def normalize_bug_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a harness-specific bug candidate into the GBQA protocol shape."""

    normalized = normalize_issue_report(payload)
    normalized["severity"] = str(payload.get("severity", "")).strip()
    normalized["reproduction_hints"] = payload.get("reproduction_hints", [])
    return normalized


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


def load_issue_reports(path: str | Path) -> list[dict[str, Any]]:
    """Load one or more targeted issue reports from issue.json or bugs.json."""

    issue_path = Path(path)
    if issue_path.is_dir():
        explicit_issue = issue_path / "issue.json"
        issue_path = explicit_issue if explicit_issue.is_file() else issue_path / "bugs.json"
    with issue_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and isinstance(payload.get("issue"), dict):
        raw_issues = [payload["issue"]]
    elif isinstance(payload, dict) and isinstance(payload.get("issues"), list):
        raw_issues = payload["issues"]
    elif isinstance(payload, dict) and isinstance(payload.get("bugs"), list):
        raw_issues = payload["bugs"]
    elif isinstance(payload, dict):
        raw_issues = [payload]
    elif isinstance(payload, list):
        raw_issues = payload
    else:
        raw_issues = []
    return [
        normalize_issue_report(issue)
        for issue in raw_issues
        if isinstance(issue, dict)
    ]


def issue_report_completeness(issue: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic completeness details for targeted issue reports."""

    missing = []
    for field in ISSUE_REQUIRED_FIELDS:
        value = issue.get(field)
        if value in (None, "", [], {}):
            missing.append(field)
    return {
        "complete": not missing,
        "missing_fields": missing,
    }


def _extract_artifacts(payload: dict[str, Any]) -> dict[str, Any]:
    environment = payload.get("environment", {})
    if isinstance(environment, dict):
        artifacts = environment.get("artifacts", {})
        if isinstance(artifacts, dict):
            return artifacts
    artifacts = payload.get("artifacts", {})
    return artifacts if isinstance(artifacts, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
