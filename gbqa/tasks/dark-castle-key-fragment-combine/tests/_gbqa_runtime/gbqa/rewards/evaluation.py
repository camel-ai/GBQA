"""Shared GBQA bug-report evaluation for rewardkit criteria."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from gbqa.rewards.paths import (
    resolve_bugs_path,
    resolve_ground_truth_path,
)
from gbqa.rewards.targeted import evaluate_targeted_bug_report

_RESULT_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def evaluate_task_report(
    workspace: Path | None = None,
    *,
    bugs_path: str | Path | None = None,
    ground_truth_path: str | Path | None = None,
    eval_method: str | None = None,
) -> dict[str, Any]:
    """Evaluate the current task bug report, caching by resolved input paths."""

    del workspace
    method = str(eval_method or os.environ.get("GBQA_EVAL_METHOD", "targeted_bug"))
    method = method.strip().lower().replace("-", "_")
    bugs = resolve_bugs_path(bugs_path=bugs_path)
    ground_truth = resolve_ground_truth_path(ground_truth_path=ground_truth_path)
    cache_key = (
        method,
        str(bugs),
        str(ground_truth),
    )
    if cache_key not in _RESULT_CACHE:
        if method in {"targeted", "targeted_bug", "basic"}:
            _RESULT_CACHE[cache_key] = evaluate_targeted_bug_report(
                issue_path=bugs,
                ground_truth_path=ground_truth,
            )
        else:
            _RESULT_CACHE[cache_key] = {
                "evaluation_method": method,
                "reward": 0.0,
                "error": f"Unsupported GBQA_EVAL_METHOD: {method}",
            }
    return _RESULT_CACHE[cache_key]
