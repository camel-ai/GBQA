#!/usr/bin/env python3
"""Harbor verifier entrypoint — thin wrapper around gbqa.verifier."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure /sandbox is on the path so gbqa can be imported.
sys.path.insert(0, "/sandbox")

from gbqa.verifier import evaluate_bug_report, write_harbor_reward


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate a GBQA bug report")
    parser.add_argument("--bugs", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--match-threshold", type=float, default=0.65)
    args = parser.parse_args()

    result = evaluate_bug_report(
        bugs_path=args.bugs,
        ground_truth_path=args.ground_truth,
        match_threshold=args.match_threshold,
    )
    write_harbor_reward(result, args.out_dir)


if __name__ == "__main__":
    main()
