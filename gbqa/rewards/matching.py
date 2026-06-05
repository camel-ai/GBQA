"""GBQA bug-report matching used by Rewardkit criteria."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


@dataclass
class MatchDetail:
    predicted_title: str
    predicted_description: str
    match_id: str
    score: float
    rationale: str
    matched: bool


def evaluate_bug_report(
    *,
    bugs_path: str | Path,
    ground_truth_path: str | Path,
    match_threshold: float = 0.65,
) -> dict[str, Any]:
    """Evaluate a GBQA bug report and return structured match metrics."""

    try:
        predicted = _load_predicted_bugs(Path(bugs_path))
        ground_truth = _load_ground_truth(Path(ground_truth_path))
    except Exception as exc:  # noqa: BLE001
        return _error_result(f"{type(exc).__name__}: {exc}")

    if not ground_truth:
        return _error_result("No ground-truth bugs were loaded.")

    used_truth_indices: set[int] = set()
    details: list[MatchDetail] = []
    matched = 0
    for bug in predicted:
        match_index, score = _best_match_index(
            bug,
            ground_truth,
            used_truth_indices,
            match_threshold,
        )
        is_match = match_index is not None
        if is_match:
            matched += 1
            used_truth_indices.add(match_index)
        truth = ground_truth[match_index] if match_index is not None else {}
        details.append(
            MatchDetail(
                predicted_title=str(bug.get("title", "")),
                predicted_description=str(bug.get("description", "")),
                match_id=str(truth.get("id", "")),
                score=score,
                rationale="sequence_matcher",
                matched=is_match,
            )
        )

    precision = matched / len(predicted) if predicted else 0.0
    recall = matched / len(ground_truth) if ground_truth else 0.0
    return {
        "reward": recall,
        "precision": precision,
        "recall": recall,
        "matched": matched,
        "total_predicted": len(predicted),
        "total_ground_truth": len(ground_truth),
        "details": [asdict(detail) for detail in details],
    }


def _load_predicted_bugs(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        path = path / "bugs.json"
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        bugs = payload.get("bugs", [])
    elif isinstance(payload, list):
        bugs = payload
    else:
        bugs = []
    return [bug for bug in bugs if isinstance(bug, dict)]


def _load_ground_truth(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    bugs = payload.get("bugs", []) if isinstance(payload, dict) else []
    return [_normalize_truth(item) for item in bugs if isinstance(item, dict)]


def _best_match_index(
    bug: dict[str, Any],
    truth: list[dict[str, Any]],
    used_indices: set[int],
    match_threshold: float,
) -> tuple[int | None, float]:
    best_score = 0.0
    best_index: int | None = None
    bug_text = _bug_text(bug)
    for index, item in enumerate(truth):
        if index in used_indices:
            continue
        score = _match_score(bug, item, bug_text)
        if score > best_score:
            best_score = score
            best_index = index
    if best_score >= match_threshold:
        return best_index, best_score
    return None, best_score


def _bug_text(bug: dict[str, Any]) -> str:
    evidence = bug.get("evidence", {})
    parts = [
        bug.get("title", ""),
        bug.get("description", ""),
        " ".join(str(tag) for tag in bug.get("tags", []) if tag),
    ]
    if isinstance(evidence, dict):
        parts.extend(str(value) for value in evidence.values())
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _match_score(
    bug: dict[str, Any],
    truth: dict[str, Any],
    bug_text: str,
) -> float:
    scores = [SequenceMatcher(None, bug_text, _truth_text(truth)).ratio()]
    for left in _bug_match_parts(bug):
        for right in _truth_match_parts(truth):
            if left and right:
                scores.append(SequenceMatcher(None, left, right).ratio())
    return max(scores) if scores else 0.0


def _bug_match_parts(bug: dict[str, Any]) -> list[str]:
    evidence = bug.get("evidence", {})
    parts = [str(bug.get("title", "")), str(bug.get("description", ""))]
    if isinstance(evidence, dict):
        observed_fault = evidence.get("observed_fault")
        if observed_fault:
            parts.append(str(observed_fault))
        reproduction = evidence.get("minimal_reproduction")
        if isinstance(reproduction, list):
            parts.append(" ".join(str(step) for step in reproduction))
        elif reproduction:
            parts.append(str(reproduction))
    return [part.strip() for part in parts if part and part.strip()]


def _truth_match_parts(truth: dict[str, Any]) -> list[str]:
    return [
        str(part).strip()
        for part in [
            truth.get("title", ""),
            truth.get("description", ""),
            truth.get("observed_fault", ""),
            " ".join(truth.get("minimal_reproduction", [])),
        ]
        if str(part).strip()
    ]


def _normalize_truth(payload: dict[str, Any]) -> dict[str, Any]:
    minimal_reproduction = payload.get("minimal_reproduction") or payload.get(
        "test_steps", []
    )
    if isinstance(minimal_reproduction, str):
        minimal_reproduction = [minimal_reproduction]
    if not isinstance(minimal_reproduction, list):
        minimal_reproduction = []
    observed_fault = str(
        payload.get("observed_fault")
        or payload.get("actual_behavior")
        or payload.get("description")
        or ""
    ).strip()
    return {
        "id": str(payload.get("id", "")).strip(),
        "bug_type": str(payload.get("bug_type", "")).strip(),
        "difficulty": str(payload.get("difficulty", "")).strip(),
        "minimal_reproduction": [str(step).strip() for step in minimal_reproduction],
        "observed_fault": observed_fault,
        "title": str(payload.get("title") or observed_fault).strip(),
        "description": str(payload.get("description") or observed_fault).strip(),
    }


def _truth_text(truth: dict[str, Any]) -> str:
    parts = [
        truth.get("title", ""),
        truth.get("description", ""),
        truth.get("bug_type", ""),
        truth.get("difficulty", ""),
        " ".join(truth.get("minimal_reproduction", [])),
        truth.get("observed_fault", ""),
    ]
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _error_result(error: str) -> dict[str, Any]:
    return {
        "reward": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "matched": 0,
        "total_predicted": 0,
        "total_ground_truth": 0,
        "details": [],
        "error": error,
    }
