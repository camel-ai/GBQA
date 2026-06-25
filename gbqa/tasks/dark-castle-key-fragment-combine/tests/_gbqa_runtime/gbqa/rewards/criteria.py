"""Reusable Rewardkit criteria for GBQA tasks."""

from __future__ import annotations

import json
import os
from pathlib import Path

from rewardkit import criterion

from gbqa.rewards.evaluation import evaluate_task_report


@criterion(shared=True, description="GBQA targeted known-bug binary reward")
def targeted_bug_reward(workspace: Path) -> float:
    return float(evaluate_task_report(workspace).get("reward", 0.0))


@criterion(shared=True, description="Whether the targeted known bug was found")
def target_bug_found(workspace: Path) -> float:
    return float(bool(evaluate_task_report(workspace).get("found_target_bug", False)))


@criterion(shared=True, description="Whether the submitted issue report is complete")
def issue_report_complete(workspace: Path) -> float:
    return float(bool(evaluate_task_report(workspace).get("report_complete", False)))


@criterion(shared=True, description="Whether issue pinpoint aligns with the golden patch")
def issue_pinpoint_aligned(workspace: Path) -> float:
    return float(bool(evaluate_task_report(workspace).get("pinpoint_aligned", False)))


@criterion(
    shared=True,
    description="GBQA exported trajectory exists at {path}",
)
def trajectory_exported(workspace: Path, path: str = "") -> bool:
    del workspace
    candidates = _trajectory_candidates(path)
    return any(_trajectory_file_has_content(candidate) for candidate in candidates)


def _trajectory_candidates(path: str = "") -> list[Path]:
    if path:
        return [Path(path)]
    raw_candidates = [
        os.environ.get("GBQA_TRAJECTORY_PATH", "/logs/agent/gbqa/trace.jsonl"),
        os.environ.get("GBQA_STEPS_PATH", "/logs/agent/gbqa/steps.jsonl"),
        os.environ.get("GBQA_ATIF_TRAJECTORY_PATH", "/logs/agent/trajectory.json"),
    ]
    candidates: list[Path] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        candidates.append(Path(text))
    return candidates


def _trajectory_file_has_content(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return False
    if path.suffix == ".jsonl":
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
    path: str = "/logs/agent/trajectory.json",
) -> bool:
    del workspace
    from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

    data = load_trajectory(
        path
        or os.environ.get("GBQA_ATIF_TRAJECTORY_PATH", "/logs/agent/trajectory.json")
    )
    if data is None:
        return False
    calls = collect_tool_calls(data)
    count = sum(1 for call in calls if call.get("function_name") == tool_name)
    return count >= min_count
