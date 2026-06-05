"""Reusable Rewardkit criteria for GBQA bug-report scoring."""

from __future__ import annotations

from pathlib import Path

from rewardkit import criterion

from gbqa.rewards.evaluation import evaluate_task_report


@criterion(shared=True, description="GBQA bug-report recall against ground truth")
def bug_recall(workspace: Path) -> float:
    return float(evaluate_task_report(workspace).get("recall", 0.0))


@criterion(shared=True, description="GBQA bug-report precision against predictions")
def bug_precision(workspace: Path) -> float:
    return float(evaluate_task_report(workspace).get("precision", 0.0))
