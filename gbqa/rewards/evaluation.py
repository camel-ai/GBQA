"""Shared GBQA bug-report evaluation for rewardkit criteria."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from gbqa.rewards.paths import (
    resolve_baseline_values_path,
    resolve_bugs_path,
    resolve_ground_truth_path,
    resolve_validation_cases_path,
)
from gbqa.rewards.value_based import evaluate_value_based_report

_RESULT_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def evaluate_task_report(
    workspace: Path | None = None,
    *,
    bugs_path: str | Path | None = None,
    ground_truth_path: str | Path | None = None,
    baseline_values_path: str | Path | None = None,
    validation_cases_path: str | Path | None = None,
    eval_method: str | None = None,
) -> dict[str, Any]:
    """Evaluate the current task bug report, caching by resolved input paths."""

    del workspace
    method = str(eval_method or os.environ.get("GBQA_EVAL_METHOD", "value_based"))
    method = method.strip().lower().replace("-", "_")
    bugs = resolve_bugs_path(bugs_path=bugs_path)
    ground_truth = resolve_ground_truth_path(ground_truth_path=ground_truth_path)
    baseline_values = resolve_baseline_values_path(
        baseline_values_path=baseline_values_path
    )
    validation_cases = resolve_validation_cases_path(
        validation_cases_path=validation_cases_path
    )
    cache_key = (
        method,
        str(bugs),
        str(ground_truth),
        str(baseline_values),
        str(validation_cases),
        os.environ.get("GBQA_BUG_TEST_GENERATOR_CMD", ""),
        os.environ.get("GBQA_BUG_TEST_REASONABLENESS_CMD", ""),
        os.environ.get("GBQA_BUG_TEST_EXECUTOR_CMD", ""),
        os.environ.get("GBQA_VALUE_AGENT_CMD", ""),
    )
    if cache_key not in _RESULT_CACHE:
        _RESULT_CACHE[cache_key] = evaluate_value_based_report(
            bugs_path=bugs,
            ground_truth_path=ground_truth,
            baseline_values_path=baseline_values,
            validation_cases_path=validation_cases,
        )
    return _RESULT_CACHE[cache_key]
