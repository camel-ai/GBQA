"""Harbor-compatible reward output writers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_reward_scores(result: dict[str, Any]) -> dict[str, float]:
    """Build numeric Harbor reward.json metrics from a GBQA evaluation."""

    recall = float(result.get("recall", 0.0) or 0.0)
    precision = float(result.get("precision", 0.0) or 0.0)
    primary = float(result.get("reward", recall) or recall)
    return {
        "recall": recall,
        "precision": precision,
        "reward": primary,
    }


def write_verifier_outputs(
    result: dict[str, Any],
    out_dir: str | Path,
    *,
    rewardkit_scores: dict[str, float] | None = None,
) -> dict[str, float]:
    """Write reward.txt, reward.json, reward-details.json, and gbqa_result.json."""

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    scores = dict(rewardkit_scores or {})
    scores.update(build_reward_scores(result))
    primary = float(scores.get("reward", scores.get("recall", 0.0)) or 0.0)

    (out_path / "reward.txt").write_text(f"{primary}\n", encoding="utf-8")
    (out_path / "reward.json").write_text(
        json.dumps(scores, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    details_path = out_path / "reward-details.json"
    details = _load_reward_details(details_path)
    details["gbqa"] = _gbqa_detail_payload(result, scores)
    details_path.write_text(
        json.dumps(details, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (out_path / "gbqa_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
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
    result: dict[str, Any],
    scores: dict[str, float],
) -> dict[str, Any]:
    return {
        "scores": scores,
        "matched": int(result.get("matched", 0) or 0),
        "total_predicted": int(result.get("total_predicted", 0) or 0),
        "total_ground_truth": int(result.get("total_ground_truth", 0) or 0),
        "details": result.get("details", []),
        "error": result.get("error", ""),
    }
