"""Tests for Harbor Rewardkit-compatible GBQA verifier outputs."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(ROOT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gbqa.rewards.output import build_reward_scores, write_verifier_outputs
from gbqa.rewards.runner import run_task_verifier
from gbqa.verifier import evaluate_bug_report


TASK_TESTS_DIR = (
    Path(REPO_ROOT) / "gbqa" / "tasks" / "dark-castle" / "tests"
)
GROUND_TRUTH = (
    Path(REPO_ROOT) / "gbqa" / "tasks" / "dark-castle" / "bugs" / "dark-castle.json"
)


def test_build_reward_scores_exposes_recall_precision_and_primary() -> None:
    scores = build_reward_scores(
        {
            "reward": 0.25,
            "recall": 0.25,
            "precision": 0.5,
        }
    )
    assert scores == {"recall": 0.25, "precision": 0.5, "reward": 0.25}


def test_write_verifier_outputs_writes_rewardkit_files() -> None:
    temp_root = Path(REPO_ROOT) / "agent" / "test" / "_tmp_gbqa_rewards"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    result = {
        "reward": 0.5,
        "recall": 0.5,
        "precision": 1.0,
        "matched": 1,
        "total_predicted": 1,
        "total_ground_truth": 2,
        "details": [],
    }
    scores = write_verifier_outputs(
        result,
        temp_root,
        rewardkit_scores={"recall": 0.5, "precision": 1.0},
    )
    assert scores["reward"] == 0.5
    reward_payload = json.loads((temp_root / "reward.json").read_text())
    assert reward_payload == {
        "recall": 0.5,
        "precision": 1.0,
        "reward": 0.5,
    }
    details = json.loads((temp_root / "reward-details.json").read_text())
    assert details["gbqa"]["matched"] == 1
    assert (temp_root / "gbqa_result.json").exists()
    shutil.rmtree(temp_root, ignore_errors=True)


def test_run_task_verifier_with_rewardkit_layout() -> None:
    try:
        import rewardkit  # noqa: F401
    except ImportError:
        return

    temp_root = Path(REPO_ROOT) / "agent" / "test" / "_tmp_gbqa_rewardkit"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    bugs = temp_root / "bugs.json"
    out_dir = temp_root / "verifier"
    bugs.write_text(
        json.dumps(
            {
                "bugs": [
                    {
                        "title": "Locked door opens without key",
                        "description": "The iron door opens even when no key is held.",
                        "evidence": {
                            "observed_fault": "Door opens without key",
                            "minimal_reproduction": ["go north", "open door"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    scores = run_task_verifier(
        tests_dir=TASK_TESTS_DIR,
        workspace=temp_root,
        out_dir=out_dir,
        bugs_path=bugs,
        ground_truth_path=GROUND_TRUTH,
        use_rewardkit=True,
    )
    assert "recall" in scores
    assert "precision" in scores
    assert "reward" in scores
    reward_payload = json.loads((out_dir / "reward.json").read_text())
    assert isinstance(reward_payload["recall"], (int, float))
    assert isinstance(reward_payload["precision"], (int, float))
    details = json.loads((out_dir / "reward-details.json").read_text())
    assert "recall" in details
    assert "precision" in details
    assert "gbqa" in details
    shutil.rmtree(temp_root, ignore_errors=True)


def test_legacy_only_runner_matches_evaluate_bug_report() -> None:
    temp_root = Path(REPO_ROOT) / "agent" / "test" / "_tmp_gbqa_rewardkit_legacy"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    bugs = temp_root / "bugs.json"
    out_dir = temp_root / "verifier"
    bugs.write_text('{"bugs": []}', encoding="utf-8")

    scores = run_task_verifier(
        tests_dir=TASK_TESTS_DIR,
        workspace=temp_root,
        out_dir=out_dir,
        bugs_path=bugs,
        ground_truth_path=GROUND_TRUTH,
        use_rewardkit=False,
    )
    expected = evaluate_bug_report(bugs_path=bugs, ground_truth_path=GROUND_TRUTH)
    assert scores["recall"] == expected["recall"]
    assert scores["precision"] == expected["precision"]
    assert scores["reward"] == expected["reward"]
    shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    test_build_reward_scores_exposes_recall_precision_and_primary()
    test_write_verifier_outputs_writes_rewardkit_files()
    test_run_task_verifier_with_rewardkit_layout()
    test_legacy_only_runner_matches_evaluate_bug_report()
    print("gbqa rewards tests passed")


if __name__ == "__main__":
    main()
