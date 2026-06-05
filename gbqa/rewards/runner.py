"""Rewardkit-first verifier runner for GBQA Harbor tasks."""

from __future__ import annotations

import argparse
from pathlib import Path

from gbqa.rewards.evaluation import evaluate_task_report
from gbqa.rewards.output import write_verifier_outputs


def run_task_verifier(
    *,
    tests_dir: str | Path,
    workspace: str | Path,
    out_dir: str | Path,
    bugs_path: str | Path | None = None,
    ground_truth_path: str | Path | None = None,
    match_threshold: float | None = None,
    use_rewardkit: bool = True,
) -> dict[str, float]:
    """Run rewardkit criteria when available, then write GBQA reward artifacts."""

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    rewardkit_scores: dict[str, float] = {}

    if use_rewardkit:
        try:
            import rewardkit as rk
        except ImportError:
            rewardkit_scores = {}
        else:
            rewardkit_scores = rk.run(
                tests_dir,
                workspace=workspace,
                output=out_path / "reward.json",
            )

    result = evaluate_task_report(
        Path(workspace),
        bugs_path=bugs_path,
        ground_truth_path=ground_truth_path,
        match_threshold=match_threshold,
    )
    return write_verifier_outputs(
        result,
        out_path,
        rewardkit_scores=rewardkit_scores,
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
    parser.add_argument("--match-threshold", type=float)
    parser.add_argument(
        "--legacy-only",
        action="store_true",
        help="Skip rewardkit discovery and only write GBQA reward artifacts.",
    )
    args = parser.parse_args()
    scores = run_task_verifier(
        tests_dir=args.tests_dir,
        workspace=args.workspace,
        out_dir=args.out_dir,
        bugs_path=args.bugs,
        ground_truth_path=args.ground_truth,
        match_threshold=args.match_threshold,
        use_rewardkit=not args.legacy_only,
    )
    print(f"[gbqa.rewards] wrote verifier rewards: {scores}")


if __name__ == "__main__":
    main()
