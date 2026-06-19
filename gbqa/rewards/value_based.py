"""Value-based GBQA bug-report evaluation.

The default verifier treats task ground truth as a human baseline, not as the
only possible oracle. Reported candidates are first verified as reasonable
testable bugs, then assigned stable tier points through a rubric.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from gbqa.protocol.schemas import load_bug_candidates


RUBRIC_VERSION = "impact_scope_repro_v1"

TIER_POINTS: dict[str, int] = {
    "none": 0,
    "low": 1,
    "medium": 3,
    "high": 6,
    "critical": 10,
}

DEFAULT_RUBRIC: dict[str, Any] = {
    "version": RUBRIC_VERSION,
    "dimensions": {
        "impact": {
            "min": 0,
            "max": 4,
            "rubric": "How severe the user-visible failure is if the bug is real.",
            "scores": {
                "0": "No demonstrated user impact.",
                "1": "Cosmetic issue, wording issue, or low-risk confusion.",
                "2": "Incorrect behavior in a localized workflow.",
                "3": "Breaks or bypasses an important feature path.",
                "4": "Causes data loss, security failure, crash, or total task failure.",
            },
        },
        "scope": {
            "min": 0,
            "max": 4,
            "rubric": "How broadly the bug can affect users or product behavior.",
            "scores": {
                "0": "No affected product behavior identified.",
                "1": "Single narrow screen, command, or edge case.",
                "2": "One feature or task-critical path.",
                "3": "Multiple related features, roles, or states.",
                "4": "System-wide, cross-session, security, or data-integrity scope.",
            },
        },
        "reproducibility": {
            "min": 0,
            "max": 4,
            "rubric": "How directly and reliably the report supports reproduction.",
            "scores": {
                "0": "No usable reproduction evidence.",
                "1": "Vague evidence with missing steps.",
                "2": "Partially reproducible with assumptions.",
                "3": "Clear reproducible path with expected/actual behavior.",
                "4": "Minimal deterministic reproduction and strong supporting evidence.",
            },
        },
    },
    "tier_mapping": [
        {"min_total": 0, "max_total": 1, "tier": "none", "points": 0},
        {"min_total": 2, "max_total": 4, "tier": "low", "points": 1},
        {"min_total": 5, "max_total": 7, "tier": "medium", "points": 3},
        {"min_total": 8, "max_total": 10, "tier": "high", "points": 6},
        {"min_total": 11, "max_total": 12, "tier": "critical", "points": 10},
    ],
}


@dataclass
class GeneratedTestCase:
    """Verifier-side test case derived from a candidate report."""

    title: str
    steps: list[str]
    expected_failure: str
    source: str = "report"
    validation_case_id: str = ""
    command: list[str] = field(default_factory=list)


@dataclass
class TestReasonableness:
    """Whether the generated test is a fair test for the candidate."""

    reasonable: bool
    source: str
    rationale: str


@dataclass
class TestExecution:
    """Rule-based execution result for a generated test case."""

    status: str
    verified: bool
    source: str
    rationale: str
    buggy_result: str = ""
    fixed_result: str = ""


@dataclass
class ValueScore:
    """Dimension scores mapped to stable tier points."""

    rubric_version: str
    dimensions: dict[str, int]
    total_dimension_score: int
    tier: str
    points: int
    source: str
    rationale: str


def evaluate_value_based_report(
    *,
    bugs_path: str | Path,
    ground_truth_path: str | Path,
    baseline_values_path: str | Path | None = None,
    validation_cases_path: str | Path | None = None,
    max_reported_bugs: int | None = None,
) -> dict[str, Any]:
    """Evaluate reported bugs against a pre-scored human value baseline."""

    try:
        candidates = load_bug_candidates(bugs_path)
        baseline_values = _load_baseline_values(
            Path(baseline_values_path) if baseline_values_path is not None else None
        )
        ground_truth = _load_ground_truth(Path(ground_truth_path))
        validation_cases = _load_validation_cases(
            Path(validation_cases_path) if validation_cases_path is not None else None
        )
    except Exception as exc:  # noqa: BLE001
        return _error_result(f"{type(exc).__name__}: {exc}")

    human_bug_count = len(ground_truth) or len(baseline_values)
    if ground_truth and not baseline_values:
        return _error_result("No precomputed human baseline bug values were loaded.")
    report_limit = int(max_reported_bugs or human_bug_count)
    if report_limit < 0:
        report_limit = 0
    evaluated_candidates = candidates[:report_limit]
    ignored_candidates = candidates[report_limit:]
    human_value = sum(int(item.get("points", 0) or 0) for item in baseline_values)

    details: list[dict[str, Any]] = []
    agent_value = 0
    verified_count = 0
    for index, candidate in enumerate(evaluated_candidates):
        detail = _evaluate_candidate(
            candidate=candidate,
            candidate_index=index,
            validation_cases=validation_cases,
        )
        details.append(detail)
        if detail["verified"]:
            verified_count += 1
            agent_value += int(detail["value"]["points"])

    reward = _reward_from_values(agent_value=agent_value, human_value=human_value)
    return {
        "evaluation_method": "value_based",
        "rubric_version": RUBRIC_VERSION,
        "reward": reward,
        "agent_value": float(agent_value),
        "human_value": float(human_value),
        "verified_bug_count": verified_count,
        "evaluated_bug_count": len(evaluated_candidates),
        "ignored_bug_count": len(ignored_candidates),
        "total_reported": len(candidates),
        "total_ground_truth": human_bug_count,
        "max_reported_bugs": report_limit,
        "details": details,
        "ignored_candidates": [
            {
                "candidate_index": report_limit + index,
                "title": str(candidate.get("title", "")),
                "reason": "outside_top_n_report_budget",
            }
            for index, candidate in enumerate(ignored_candidates)
        ],
        "baseline": {
            "path": str(baseline_values_path or ""),
            "bug_count": len(baseline_values),
            "human_value": float(human_value),
            "bugs": baseline_values,
        },
    }


def _evaluate_candidate(
    *,
    candidate: dict[str, Any],
    candidate_index: int,
    validation_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    generated_test = _generate_test_case(candidate)
    reasonableness = _judge_test_reasonableness(candidate, generated_test)
    execution = (
        _execute_test_case(candidate, generated_test, validation_cases)
        if reasonableness.reasonable
        else TestExecution(
            status="not_run",
            verified=False,
            source="reasonableness_gate",
            rationale="Generated test was not judged reasonable.",
        )
    )
    verified = reasonableness.reasonable and execution.verified
    value = (
        _score_bug_value(candidate)
        if verified
        else ValueScore(
            rubric_version=RUBRIC_VERSION,
            dimensions={"impact": 0, "scope": 0, "reproducibility": 0},
            total_dimension_score=0,
            tier="none",
            points=0,
            source="verification_gate",
            rationale="Candidate was not verified as a real bug.",
        )
    )
    return {
        "candidate_index": candidate_index,
        "title": str(candidate.get("title", "")),
        "description": str(candidate.get("description", "")),
        "verified": verified,
        "generated_test": asdict(generated_test),
        "reasonableness": asdict(reasonableness),
        "execution": asdict(execution),
        "value": asdict(value),
    }


def _generate_test_case(candidate: dict[str, Any]) -> GeneratedTestCase:
    payload = _run_json_command(
        os.environ.get("GBQA_BUG_TEST_GENERATOR_CMD", ""),
        {"candidate": candidate},
    )
    if payload:
        return GeneratedTestCase(
            title=str(payload.get("title") or candidate.get("title", "")),
            steps=_string_list(payload.get("steps")),
            expected_failure=str(
                payload.get("expected_failure")
                or payload.get("assertion")
                or _expected_failure_assertion(candidate)
            ),
            source=str(payload.get("source") or "external_generator"),
            validation_case_id=str(payload.get("validation_case_id", "")),
            command=_string_list(payload.get("command")),
        )

    return GeneratedTestCase(
        title=str(candidate.get("title", "")),
        steps=_reproduction_steps(candidate),
        expected_failure=_expected_failure_assertion(candidate),
    )


def _judge_test_reasonableness(
    candidate: dict[str, Any],
    generated_test: GeneratedTestCase,
) -> TestReasonableness:
    payload = _run_json_command(
        os.environ.get("GBQA_BUG_TEST_REASONABLENESS_CMD", ""),
        {"candidate": candidate, "generated_test": asdict(generated_test)},
    )
    if payload:
        return TestReasonableness(
            reasonable=bool(payload.get("reasonable", False)),
            source=str(payload.get("source") or "external_judge"),
            rationale=str(payload.get("rationale", "")),
        )

    missing: list[str] = []
    if not str(candidate.get("title", "")).strip():
        missing.append("title")
    if not str(candidate.get("description", "")).strip():
        missing.append("description")
    if not generated_test.steps:
        missing.append("reproduction_steps")
    if not _expected_behavior(candidate):
        missing.append("expected_behavior")
    if not _observed_fault(candidate):
        missing.append("observed_fault")
    if not generated_test.expected_failure:
        missing.append("expected_failure")
    if missing:
        return TestReasonableness(
            reasonable=False,
            source="heuristic_judge",
            rationale="Missing required report evidence: " + ", ".join(missing),
        )
    return TestReasonableness(
        reasonable=True,
        source="heuristic_judge",
        rationale=(
            "Report contains a title, description, expected behavior, observed "
            "fault, reproduction steps, and an expected failure assertion."
        ),
    )


def _execute_test_case(
    candidate: dict[str, Any],
    generated_test: GeneratedTestCase,
    validation_cases: list[dict[str, Any]],
) -> TestExecution:
    payload = _run_json_command(
        os.environ.get("GBQA_BUG_TEST_EXECUTOR_CMD", ""),
        {"candidate": candidate, "generated_test": asdict(generated_test)},
    )
    if payload:
        status = str(payload.get("status") or "")
        verified = bool(payload.get("verified", status == "failed"))
        return TestExecution(
            status=status or ("failed" if verified else "passed"),
            verified=verified,
            source=str(payload.get("source") or "external_executor"),
            rationale=str(payload.get("rationale", "")),
            buggy_result=str(payload.get("buggy_result", "")),
            fixed_result=str(payload.get("fixed_result", "")),
        )

    matched_case = _match_validation_case(candidate, generated_test, validation_cases)
    if matched_case is None:
        return TestExecution(
            status="not_executed",
            verified=False,
            source="validation_cases",
            rationale=(
                "No task validation case matched this candidate. Configure "
                "GBQA_BUG_TEST_EXECUTOR_CMD to verify hidden bugs dynamically."
            ),
        )
    generated_test.validation_case_id = str(matched_case.get("id", ""))
    command = _command_list(matched_case.get("command"))
    if command:
        timeout = float(matched_case.get("timeout_sec", 120) or 120)
        cwd = Path(str(matched_case.get("cwd") or "/sandbox"))
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd.is_dir() else None,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return TestExecution(
                status="error",
                verified=False,
                source="validation_case_command",
                rationale=f"Validation command failed to run: {type(exc).__name__}: {exc}",
            )
        verified = completed.returncode != 0
        return TestExecution(
            status="failed" if verified else "passed",
            verified=verified,
            source="validation_case_command",
            rationale=str(
                matched_case.get("rationale")
                or "Validation command failed in the buggy environment."
            ),
            buggy_result=(completed.stderr or completed.stdout).strip(),
            fixed_result=str(matched_case.get("fixed_result", "pass")),
        )
    return TestExecution(
        status="failed",
        verified=True,
        source="validation_cases",
        rationale=str(matched_case.get("rationale") or "Matched task validation case."),
        buggy_result=str(matched_case.get("buggy_result", "fail")),
        fixed_result=str(matched_case.get("fixed_result", "pass")),
    )


def _score_bug_value(candidate: dict[str, Any]) -> ValueScore:
    payload = _run_json_command(
        os.environ.get("GBQA_VALUE_AGENT_CMD", ""),
        {"candidate": candidate, "rubric": DEFAULT_RUBRIC},
    )
    if payload:
        dimensions = _normalize_dimensions(payload.get("dimensions", {}))
        total = sum(dimensions.values())
        tier = str(payload.get("tier") or _tier_for_total(total))
        points = int(payload.get("points", TIER_POINTS.get(tier, 0)) or 0)
        return ValueScore(
            rubric_version=str(payload.get("rubric_version") or RUBRIC_VERSION),
            dimensions=dimensions,
            total_dimension_score=total,
            tier=tier,
            points=points,
            source=str(payload.get("source") or "external_value_agent"),
            rationale=str(payload.get("rationale", "")),
        )

    dimensions = _heuristic_dimensions(candidate)
    total = sum(dimensions.values())
    tier = _tier_for_total(total)
    return ValueScore(
        rubric_version=RUBRIC_VERSION,
        dimensions=dimensions,
        total_dimension_score=total,
        tier=tier,
        points=TIER_POINTS[tier],
        source="heuristic_value_agent",
        rationale="Deterministic fallback rubric based on report severity and evidence.",
    )


def _heuristic_dimensions(candidate: dict[str, Any]) -> dict[str, int]:
    text = _candidate_text(candidate).lower()
    severity = str(candidate.get("severity", "")).strip().lower()
    if severity in {"critical", "blocker"}:
        impact = 4
    elif severity in {"high", "major"}:
        impact = 3
    elif severity in {"medium", "moderate"}:
        impact = 2
    elif severity in {"low", "minor"}:
        impact = 1
    elif any(term in text for term in ("crash", "security", "data loss", "corrupt")):
        impact = 4
    elif any(term in text for term in ("cannot", "blocked", "wrong", "invalid", "bypass")):
        impact = 3
    elif any(term in text for term in ("inconsistent", "reveals", "incorrect", "mismatch")):
        impact = 2
    else:
        impact = 1

    if any(term in text for term in ("global", "all users", "security", "system")):
        scope = 4
    elif any(term in text for term in ("multiple", "cross", "session", "workflow")):
        scope = 3
    elif any(term in text for term in ("feature", "progress", "core", "critical path")):
        scope = 2
    else:
        scope = 1

    steps = _reproduction_steps(candidate)
    observed = _observed_fault(candidate)
    expected = _expected_behavior(candidate)
    if len(steps) >= 2 and observed and expected:
        reproducibility = 4
    elif steps and observed and expected:
        reproducibility = 3
    elif steps and (observed or expected):
        reproducibility = 2
    elif steps or observed or expected:
        reproducibility = 1
    else:
        reproducibility = 0
    return {
        "impact": max(0, min(4, impact)),
        "scope": max(0, min(4, scope)),
        "reproducibility": max(0, min(4, reproducibility)),
    }


def _normalize_dimensions(payload: Any) -> dict[str, int]:
    dimensions: dict[str, int] = {}
    if not isinstance(payload, dict):
        payload = {}
    for name in ("impact", "scope", "reproducibility"):
        try:
            score = int(payload.get(name, 0) or 0)
        except (TypeError, ValueError):
            score = 0
        dimensions[name] = max(0, min(4, score))
    return dimensions


def _tier_for_total(total: int) -> str:
    for item in DEFAULT_RUBRIC["tier_mapping"]:
        if int(item["min_total"]) <= total <= int(item["max_total"]):
            return str(item["tier"])
    return "critical" if total > 12 else "none"


def _match_validation_case(
    candidate: dict[str, Any],
    generated_test: GeneratedTestCase,
    validation_cases: list[dict[str, Any]],
) -> dict[str, Any] | None:
    text = _candidate_text(candidate)
    step_text = " ".join(generated_test.steps)
    combined = f"{text} {step_text}".lower()
    for item in validation_cases:
        keywords = _string_list(item.get("keywords"))
        if keywords and all(keyword.lower() in combined for keyword in keywords):
            return item
        expected_failure = str(item.get("expected_failure", "")).strip().lower()
        if expected_failure and expected_failure in combined:
            return item
    return None


def _load_baseline_values(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not str(path):
        return []
    if not path.is_file():
        raise FileNotFoundError(f"Missing baseline value file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    bugs = payload.get("bugs", []) if isinstance(payload, dict) else []
    normalized: list[dict[str, Any]] = []
    for item in bugs:
        if not isinstance(item, dict):
            continue
        tier = str(item.get("tier", "none")).strip().lower() or "none"
        points = int(item.get("points", TIER_POINTS.get(tier, 0)) or 0)
        normalized.append(
            {
                "id": str(item.get("id", "")),
                "tier": tier,
                "points": points,
                "dimensions": _normalize_dimensions(item.get("dimensions", {})),
                "rationale": str(item.get("rationale", "")),
            }
        )
    return normalized


def _load_validation_cases(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not str(path) or not path.is_file():
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    return [item for item in cases if isinstance(item, dict)]


def _load_ground_truth(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    bugs = payload.get("bugs", []) if isinstance(payload, dict) else []
    return [item for item in bugs if isinstance(item, dict)]


def _reward_from_values(*, agent_value: float, human_value: float) -> float:
    if human_value <= 0:
        return 1.0 if agent_value > 0 else 0.0
    if agent_value >= human_value:
        return 1.0
    return max(0.0, float(agent_value) / float(human_value))


def _candidate_text(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("title", ""),
        candidate.get("description", ""),
        _expected_behavior(candidate),
        _observed_fault(candidate),
        " ".join(str(tag) for tag in candidate.get("tags", []) if tag),
    ]
    evidence = candidate.get("evidence", {})
    if isinstance(evidence, dict):
        for key, value in evidence.items():
            if key in {
                "expected_behavior",
                "observed_fault",
                "expected_outcome",
                "actual_behavior",
                "failure",
                "assertion",
            }:
                continue
            if value:
                parts.append(str(value))
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _expected_behavior(candidate: dict[str, Any]) -> str:
    evidence = candidate.get("evidence", {})
    if isinstance(evidence, dict):
        for key in ("expected_behavior", "expected_outcome", "expected", "correct_behavior"):
            value = evidence.get(key)
            if value:
                return str(value).strip()
    for key in ("expected_behavior", "expected", "correct_behavior"):
        value = candidate.get(key)
        if value:
            return str(value).strip()
    return ""


def _observed_fault(candidate: dict[str, Any]) -> str:
    evidence = candidate.get("evidence", {})
    if isinstance(evidence, dict):
        for key in ("observed_fault", "actual_behavior", "failure", "assertion"):
            value = evidence.get(key)
            if value:
                return str(value).strip()
    for key in ("observed_fault", "actual_behavior", "failure"):
        value = candidate.get(key)
        if value:
            return str(value).strip()
    return str(candidate.get("description", "")).strip()


def _expected_failure_assertion(candidate: dict[str, Any]) -> str:
    observed = _observed_fault(candidate)
    expected = _expected_behavior(candidate)
    if expected and observed:
        return f"Expected: {expected} Actual: {observed}"
    return observed or expected


def _reproduction_steps(candidate: dict[str, Any]) -> list[str]:
    evidence = candidate.get("evidence", {})
    values: list[Any] = []
    if isinstance(evidence, dict):
        values.append(evidence.get("minimal_reproduction"))
        values.append(evidence.get("reproduction_steps"))
    values.append(candidate.get("reproduction_hints"))
    for value in values:
        steps = _string_list(value)
        if steps:
            return steps
    return []


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _command_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return shlex.split(value)
    return []


def _run_json_command(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not command.strip():
        return {}
    try:
        completed = subprocess.run(
            shlex.split(command),
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=float(os.environ.get("GBQA_REWARD_COMMAND_TIMEOUT", "120")),
            check=False,
        )
    except Exception:  # noqa: BLE001
        return {}
    if completed.returncode != 0:
        return {}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}


def _error_result(error: str) -> dict[str, Any]:
    return {
        "evaluation_method": "value_based",
        "rubric_version": RUBRIC_VERSION,
        "reward": 0.0,
        "agent_value": 0.0,
        "human_value": 0.0,
        "verified_bug_count": 0,
        "evaluated_bug_count": 0,
        "ignored_bug_count": 0,
        "total_reported": 0,
        "total_ground_truth": 0,
        "max_reported_bugs": 0,
        "details": [],
        "ignored_candidates": [],
        "baseline": {},
        "error": error,
    }
