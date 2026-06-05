"""Shared GBQA bug-report evaluation for rewardkit criteria."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from gbqa.rewards.paths import resolve_bugs_path, resolve_ground_truth_path
from gbqa.rewards.matching import evaluate_bug_report

_RESULT_CACHE: dict[tuple[str, str, float], dict[str, Any]] = {}


def evaluate_task_report(
    workspace: Path | None = None,
    *,
    bugs_path: str | Path | None = None,
    ground_truth_path: str | Path | None = None,
    match_threshold: float | None = None,
) -> dict[str, Any]:
    """Evaluate the current task bug report, caching by resolved input paths."""

    del workspace
    threshold = (
        float(match_threshold)
        if match_threshold is not None
        else float(os.environ.get("GBQA_MATCH_THRESHOLD", "0.65"))
    )
    bugs = resolve_bugs_path(bugs_path=bugs_path)
    ground_truth = resolve_ground_truth_path(ground_truth_path=ground_truth_path)
    cache_key = (str(bugs), str(ground_truth), threshold)
    if cache_key not in _RESULT_CACHE:
        _RESULT_CACHE[cache_key] = evaluate_bug_report(
            bugs_path=bugs,
            ground_truth_path=ground_truth,
            match_threshold=threshold,
        )
    return _RESULT_CACHE[cache_key]
