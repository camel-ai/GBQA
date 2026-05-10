#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bugs", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--match-threshold", type=float, default=0.65)
    args = parser.parse_args()
    result = evaluate(args.bugs, args.ground_truth, args.match_threshold)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reward.txt").write_text(f"{result['reward']}\n", encoding="utf-8")
    (out_dir / "reward.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def evaluate(bugs_path: str, ground_truth_path: str, threshold: float) -> dict[str, Any]:
    try:
        predicted = _load_bugs(Path(bugs_path))
        truth = _load_truth(Path(ground_truth_path))
    except Exception as exc:  # noqa: BLE001
        return {
            "reward": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "matched": 0,
            "total_predicted": 0,
            "total_ground_truth": 0,
            "details": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    matched = 0
    used: set[int] = set()
    details: list[MatchDetail] = []
    for bug in predicted:
        index, score = _best_match(bug, truth, used, threshold)
        is_match = index is not None
        if is_match:
            matched += 1
            used.add(index)
        matched_truth = truth[index] if index is not None else {}
        details.append(
            MatchDetail(
                predicted_title=str(bug.get("title", "")),
                predicted_description=str(bug.get("description", "")),
                match_id=str(matched_truth.get("id", "")),
                score=score,
                rationale="sequence_matcher",
                matched=is_match,
            )
        )

    precision = matched / len(predicted) if predicted else 0.0
    recall = matched / len(truth) if truth else 0.0
    return {
        "reward": recall,
        "precision": precision,
        "recall": recall,
        "matched": matched,
        "total_predicted": len(predicted),
        "total_ground_truth": len(truth),
        "details": [asdict(detail) for detail in details],
    }


def _load_bugs(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    bugs = payload.get("bugs", []) if isinstance(payload, dict) else payload
    return [bug for bug in bugs if isinstance(bug, dict)]


def _load_truth(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    bugs = payload.get("bugs", []) if isinstance(payload, dict) else []
    return [_normalize_truth(bug) for bug in bugs if isinstance(bug, dict)]


def _best_match(
    bug: dict[str, Any],
    truth: list[dict[str, Any]],
    used: set[int],
    threshold: float,
) -> tuple[int | None, float]:
    best_index = None
    best_score = 0.0
    bug_text = _bug_text(bug)
    for index, item in enumerate(truth):
        if index in used:
            continue
        score = _match_score(bug, item, bug_text)
        if score > best_score:
            best_index = index
            best_score = score
    if best_score >= threshold:
        return best_index, best_score
    return None, best_score


def _bug_text(bug: dict[str, Any]) -> str:
    evidence = bug.get("evidence", {})
    parts = [bug.get("title", ""), bug.get("description", "")]
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
    steps = payload.get("minimal_reproduction", [])
    if not isinstance(steps, list):
        steps = [steps] if steps else []
    observed_fault = str(payload.get("observed_fault", "")).strip()
    return {
        "id": str(payload.get("id", "")),
        "bug_type": str(payload.get("bug_type", "")),
        "difficulty": str(payload.get("difficulty", "")),
        "minimal_reproduction": [str(step) for step in steps],
        "observed_fault": observed_fault,
        "title": observed_fault,
        "description": observed_fault,
    }


def _truth_text(truth: dict[str, Any]) -> str:
    return " ".join(
        str(part).strip()
        for part in [
            truth.get("title", ""),
            truth.get("description", ""),
            truth.get("bug_type", ""),
            truth.get("difficulty", ""),
            " ".join(truth.get("minimal_reproduction", [])),
            truth.get("observed_fault", ""),
        ]
        if str(part).strip()
    )


if __name__ == "__main__":
    main()
