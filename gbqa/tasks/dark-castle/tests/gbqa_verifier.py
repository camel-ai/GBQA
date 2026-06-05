#!/usr/bin/env python3
"""Backward-compatible Harbor verifier entrypoint."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/sandbox")

from gbqa.rewards.runner import run_task_verifier


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a GBQA bug report")
    parser.add_argument("--bugs", default=os.environ.get("GBQA_BUGS_PATH", ""))
    parser.add_argument(
        "--ground-truth",
        default=os.environ.get("GBQA_GROUND_TRUTH", ""),
    )
    parser.add_argument("--out-dir", default="/logs/verifier")
    parser.add_argument("--tests-dir", default="/tests")
    parser.add_argument("--workspace", default="/sandbox")
    parser.add_argument("--match-threshold", type=float, default=0.65)
    parser.add_argument(
        "--legacy-only",
        action="store_true",
        help="Skip rewardkit discovery and only write GBQA reward artifacts.",
    )
    args = parser.parse_args()

    if args.bugs:
        os.environ["GBQA_BUGS_PATH"] = args.bugs
    if args.ground_truth:
        os.environ["GBQA_GROUND_TRUTH"] = args.ground_truth

    scores = run_task_verifier(
        tests_dir=args.tests_dir,
        workspace=args.workspace,
        out_dir=args.out_dir,
        bugs_path=args.bugs or None,
        ground_truth_path=args.ground_truth or None,
        match_threshold=args.match_threshold,
        use_rewardkit=not args.legacy_only,
    )
    print(f"[gbqa_verifier] wrote verifier rewards: {scores}")


if __name__ == "__main__":
    main()
