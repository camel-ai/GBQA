"""Post-processing for Harbor Rewardkit verifier outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def primary_reward_score(scores: dict[str, float]) -> float:
    """Pick the scalar reward Harbor should treat as the headline score."""

    if "reward" in scores:
        return float(scores["reward"])
    if "recall" in scores:
        return float(scores["recall"])
    if not scores:
        return 0.0
    return float(next(iter(scores.values())))


def write_post_rewardkit_artifacts(
    rewardkit_scores: dict[str, float],
    evaluation: dict[str, Any],
    out_dir: str | Path,
) -> dict[str, float]:
    """Augment Rewardkit outputs with GBQA-specific artifacts."""

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    scores = dict(rewardkit_scores)
    primary = primary_reward_score(scores)

    (out_path / "reward.txt").write_text(f"{primary}\n", encoding="utf-8")

    details_path = out_path / "reward-details.json"
    details = _load_reward_details(details_path)
    details["gbqa"] = _gbqa_detail_payload(evaluation, scores)
    details_path.write_text(
        json.dumps(details, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (out_path / "gbqa_result.json").write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return scores


def _load_reward_details(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _gbqa_detail_payload(
    evaluation: dict[str, Any],
    scores: dict[str, float],
) -> dict[str, Any]:
    return {
        "scores": scores,
        "matched": int(evaluation.get("matched", 0) or 0),
        "total_predicted": int(evaluation.get("total_predicted", 0) or 0),
        "total_ground_truth": int(evaluation.get("total_ground_truth", 0) or 0),
        "details": evaluation.get("details", []),
        "error": evaluation.get("error", ""),
    }
