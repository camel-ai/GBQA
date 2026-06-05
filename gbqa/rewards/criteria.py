"""Reusable Rewardkit criteria for GBQA tasks."""

from __future__ import annotations

import json
import os
from pathlib import Path

from rewardkit import criterion

from gbqa.rewards.evaluation import evaluate_task_report


@criterion(shared=True, description="GBQA bug-report recall against ground truth")
def bug_recall(workspace: Path) -> float:
    return float(evaluate_task_report(workspace).get("recall", 0.0))


@criterion(shared=True, description="GBQA bug-report precision against predictions")
def bug_precision(workspace: Path) -> float:
    return float(evaluate_task_report(workspace).get("precision", 0.0))


@criterion(
    shared=True,
    description="Primary GBQA reward (recall against ground truth)",
)
def bug_primary_reward(workspace: Path) -> float:
    return float(evaluate_task_report(workspace).get("reward", 0.0))


@criterion(
    shared=True,
    description="GBQA exported trajectory exists at {path}",
)
def trajectory_exported(workspace: Path, path: str = "") -> bool:
    del workspace
    trajectory_path = Path(
        path or os.environ.get("GBQA_TRAJECTORY_PATH", "/logs/agent/gbqa/trace.jsonl")
    )
    if not trajectory_path.is_file():
        steps_path = Path(
            os.environ.get("GBQA_STEPS_PATH", "/logs/agent/gbqa/steps.jsonl")
        )
        if not steps_path.is_file():
            return False
        trajectory_path = steps_path
    text = trajectory_path.read_text(encoding="utf-8").strip()
    if not text:
        return False
    if trajectory_path.suffix == ".jsonl":
        return any(line.strip() for line in text.splitlines())
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return bool(payload)


@criterion(
    shared=True,
    description="ATIF trajectory tool '{tool_name}' was used (path: {path})",
)
def atif_trajectory_tool_used(
    workspace: Path,
    tool_name: str,
    min_count: int = 1,
    path: str = "/logs/trajectory.json",
) -> bool:
    del workspace
    from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

    data = load_trajectory(
        path or os.environ.get("GBQA_ATIF_TRAJECTORY_PATH", "/logs/trajectory.json")
    )
    if data is None:
        return False
    calls = collect_tool_calls(data)
    count = sum(1 for call in calls if call.get("function_name") == tool_name)
    return count >= min_count
