"""Harbor Rewardkit verifier runner for GBQA Harbor tasks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from gbqa.rewards.evaluation import evaluate_task_report
from gbqa.rewards.output import write_post_rewardkit_artifacts


class RewardkitDependencyError(ImportError):
    """Raised when harbor-rewardkit is not installed."""


def require_rewardkit():
    """Import Harbor Rewardkit or fail with an actionable error."""

    try:
        import rewardkit as rk
    except ImportError as exc:
        raise RewardkitDependencyError(
            "harbor-rewardkit is required for GBQA verification. "
            "Install it with: pip install harbor-rewardkit"
        ) from exc
    return rk


def run_task_verifier(
    *,
    tests_dir: str | Path,
    workspace: str | Path,
    out_dir: str | Path,
    bugs_path: str | Path | None = None,
    ground_truth_path: str | Path | None = None,
    eval_method: str | None = None,
) -> dict[str, float]:
    """Run Rewardkit criteria and write GBQA post-processing artifacts."""

    rk = require_rewardkit()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    env_updates = {
        "GBQA_EVAL_METHOD": eval_method,
        "GBQA_BUGS_PATH": str(bugs_path) if bugs_path is not None else None,
        "GBQA_GROUND_TRUTH": (
            str(ground_truth_path) if ground_truth_path is not None else None
        ),
    }
    previous_env = {key: os.environ.get(key) for key in env_updates}
    try:
        for key, value in env_updates.items():
            if value is not None:
                os.environ[key] = value
        evaluation = evaluate_task_report(
            Path(workspace),
            bugs_path=bugs_path,
            ground_truth_path=ground_truth_path,
            eval_method=eval_method,
        )
        (out_path / "gbqa_result.json").write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rewardkit_scores = rk.run(
            tests_dir,
            workspace=workspace,
            output=out_path / "reward.json",
        )
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return write_post_rewardkit_artifacts(
        rewardkit_scores,
        evaluation,
        out_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run GBQA verifier criteria via Harbor Rewardkit",
    )
    parser.add_argument("--tests-dir", default="/tests")
    parser.add_argument("--workspace", default="/sandbox")
    parser.add_argument("--out-dir", default="/logs/verifier")
    parser.add_argument("--bugs")
    parser.add_argument("--ground-truth")
    parser.add_argument("--eval-method")
    args = parser.parse_args()
    scores = run_task_verifier(
        tests_dir=args.tests_dir,
        workspace=args.workspace,
        out_dir=args.out_dir,
        bugs_path=args.bugs,
        ground_truth_path=args.ground_truth,
        eval_method=args.eval_method,
    )
    print(f"[gbqa.rewards] wrote verifier rewards: {scores}")


if __name__ == "__main__":
    main()
