"""Tests for Harbor Rewardkit-compatible GBQA targeted verifier outputs."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(ROOT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gbqa.rewards.output import primary_reward_score, write_post_rewardkit_artifacts
from gbqa.rewards.runner import (
    RewardkitDependencyError,
    require_rewardkit,
    run_task_verifier,
)
from gbqa.rewards.targeted import evaluate_targeted_bug_report
from gbqa.rewards.template import install_task_verifier_tests


TASK_DIR = Path(REPO_ROOT) / "gbqa" / "tasks" / "dark-castle-key-fragment-combine"
TASK_TESTS_DIR = TASK_DIR / "tests"
GROUND_TRUTH = TASK_DIR / "bugs" / "dark-castle.json"


@contextmanager
def _temp_test_dir(name: str) -> Iterator[Path]:
    temp_root = Path(REPO_ROOT) / "agent" / "test" / name
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    try:
        yield temp_root
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _programmatic_tests_dir(temp_root: Path) -> Path:
    """Copy verifier tests for a local Rewardkit run."""

    destination = temp_root / "tests"
    shutil.copytree(TASK_TESTS_DIR, destination)
    return destination


def _matching_issue(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "issue": {
                    "title": "Key assembles with only two fragments",
                    "description": "The combine command creates the final key early.",
                    "expected_behavior": "Combining key fragments should require all three fragments.",
                    "observed_fault": "The player can combine only two fragments into the complete key.",
                    "reproduction": [
                        "Collect two key fragments.",
                        "Execute `combine`.",
                    ],
                    "pinpoint": {
                        "file": "backend/game/actions.py",
                        "class": "ActionHandler",
                        "function": "handle_combine",
                    },
                    "root_cause": "ActionHandler.handle_combine uses a two-fragment threshold.",
                }
            }
        ),
        encoding="utf-8",
    )


def test_require_rewardkit_imports() -> None:
    rk = require_rewardkit()
    assert hasattr(rk, "run")


def test_primary_reward_score_prefers_reward_key() -> None:
    assert primary_reward_score({"reward": 0.4, "target_bug_found": 1.0}) == 0.4
    assert primary_reward_score({"target_bug_found": 1.0}) == 1.0


def test_write_post_rewardkit_artifacts_preserves_reward_json() -> None:
    with _temp_test_dir("_tmp_gbqa_rewards") as temp_root:
        (temp_root / "reward.json").write_text(
            json.dumps(
                {
                    "reward": 1.0,
                    "target_bug_found": 1.0,
                    "issue_report_complete": 1.0,
                    "issue_pinpoint_aligned": 1.0,
                }
            ),
            encoding="utf-8",
        )
        evaluation = {
            "evaluation_method": "targeted_bug",
            "rubric_version": "targeted_function_pinpoint_v1",
            "reward": 1.0,
            "found_target_bug": True,
            "target_bug_id": "dark-castle-key-fragment-combine",
            "report_complete": True,
            "pinpoint_aligned": True,
            "evaluated_issue_count": 1,
            "ignored_issue_count": 0,
            "total_reported": 1,
            "details": [],
        }
        scores = write_post_rewardkit_artifacts(
            {
                "reward": 1.0,
                "target_bug_found": 1.0,
                "issue_report_complete": 1.0,
                "issue_pinpoint_aligned": 1.0,
            },
            evaluation,
            temp_root,
        )
        assert scores["reward"] == 1.0
        reward_payload = json.loads((temp_root / "reward.json").read_text())
        assert reward_payload == scores
        assert (temp_root / "reward.txt").read_text().strip() == "1.0"
        details = json.loads((temp_root / "reward-details.json").read_text())
        assert details["gbqa"]["found_target_bug"] is True
        assert details["gbqa"]["pinpoint_aligned"] is True
        assert (temp_root / "gbqa_result.json").exists()


def test_run_task_verifier_with_rewardkit_layout() -> None:
    with _temp_test_dir("_tmp_gbqa_rewardkit") as temp_root:
        previous_trajectory_path = os.environ.get("GBQA_TRAJECTORY_PATH")
        try:
            trace_path = temp_root / "trace.jsonl"
            trace_path.write_text('{"type":"trace","step":1}\n', encoding="utf-8")
            os.environ["GBQA_TRAJECTORY_PATH"] = str(trace_path)
            issue = temp_root / "issue.json"
            out_dir = temp_root / "verifier"
            _matching_issue(issue)

            scores = run_task_verifier(
                tests_dir=_programmatic_tests_dir(temp_root),
                workspace=temp_root,
                out_dir=out_dir,
                bugs_path=issue,
                ground_truth_path=GROUND_TRUTH,
                eval_method="targeted_bug",
            )
            assert scores["reward"] == 1.0
            assert scores["target_bug_found"] == 1.0
            assert scores["issue_report_complete"] == 1.0
            assert scores["issue_pinpoint_aligned"] == 1.0
            assert "trajectory" in scores
            details = json.loads((out_dir / "reward-details.json").read_text())
            assert details["gbqa"]["target_bug_id"] == (
                "dark-castle-key-fragment-combine"
            )
        finally:
            if previous_trajectory_path is None:
                os.environ.pop("GBQA_TRAJECTORY_PATH", None)
            else:
                os.environ["GBQA_TRAJECTORY_PATH"] = previous_trajectory_path


def test_rewardkit_dependency_error_message() -> None:
    assert "harbor-rewardkit is required" in RewardkitDependencyError(
        "harbor-rewardkit is required for GBQA verification. "
        "Install it with: pip install harbor-rewardkit"
    ).args[0]


def test_rewardkit_discovers_rule_based_criteria() -> None:
    rk = require_rewardkit()
    with _temp_test_dir("_tmp_gbqa_reward_discover") as temp_root:
        rewards = rk.discover(TASK_TESTS_DIR, workspace=temp_root)
        reward_names = {reward.name for reward in rewards}
        assert "reward" in reward_names
        assert "target_bug_found" in reward_names
        assert "issue_report_complete" in reward_names
        assert "issue_pinpoint_aligned" in reward_names
        assert "quality" not in reward_names


def test_dark_castle_verifier_env_has_subscription_defaults() -> None:
    task_toml = TASK_DIR / "task.toml"
    config = tomllib.loads(task_toml.read_text(encoding="utf-8"))
    verifier_env = config["verifier"]["env"]
    assert verifier_env["GBQA_EVAL_METHOD"] == "${GBQA_EVAL_METHOD:-targeted_bug}"
    assert set(verifier_env) == {"GBQA_EVAL_METHOD"}
    assert all(":-" in value for value in verifier_env.values())


def test_template_installs_rule_based_targeted_verifier() -> None:
    with _temp_test_dir("_tmp_gbqa_template") as temp_root:
        install_task_verifier_tests(
            temp_root,
            ground_truth_path="/tests/bugs/example.json",
        )
        test_script = (temp_root / "test.sh").read_text(encoding="utf-8")
        assert "/tests/bugs/example.json" in test_script
        assert "__GBQA_GROUND_TRUTH__" not in test_script
        assert not (temp_root / "quality").exists()
        assert not (temp_root / "judge").exists()
        assert not (temp_root / "value").exists()
        assert (temp_root / "target_bug_found" / "check.py").is_file()
        assert (temp_root / "issue_report_complete" / "check.py").is_file()
        assert (temp_root / "issue_pinpoint_aligned" / "check.py").is_file()


def test_targeted_evaluation_scores_matching_issue() -> None:
    with _temp_test_dir("_tmp_gbqa_targeted_eval") as temp_root:
        issue = temp_root / "issue.json"
        _matching_issue(issue)
        result = evaluate_targeted_bug_report(
            issue_path=issue,
            ground_truth_path=GROUND_TRUTH,
        )
        assert result["found_target_bug"] is True
        assert result["report_complete"] is True
        assert result["pinpoint_aligned"] is True
        assert result["reward"] == 1.0


def test_targeted_evaluation_rejects_wrong_function() -> None:
    with _temp_test_dir("_tmp_gbqa_targeted_wrong") as temp_root:
        issue = temp_root / "issue.json"
        _matching_issue(issue)
        payload = json.loads(issue.read_text(encoding="utf-8"))
        payload["issue"]["pinpoint"]["function"] = "handle_open"
        payload["issue"]["pinpoint"]["class"] = "ActionHandler"
        payload["issue"]["root_cause"] = "ActionHandler.handle_open mishandles opening."
        issue.write_text(json.dumps(payload), encoding="utf-8")
        result = evaluate_targeted_bug_report(
            issue_path=issue,
            ground_truth_path=GROUND_TRUTH,
        )
        assert result["report_complete"] is True
        assert result["pinpoint_aligned"] is False
        assert result["reward"] == 0.0


def test_targeted_evaluation_short_circuits_incomplete_report_status() -> None:
    with _temp_test_dir("_tmp_gbqa_targeted_incomplete") as temp_root:
        issue = temp_root / "issue.json"
        _matching_issue(issue)
        payload = json.loads(issue.read_text(encoding="utf-8"))
        payload["report_status"] = "incomplete"
        payload["missing_fields"] = ["pinpoint"]
        payload["issue"]["pinpoint"] = {}
        issue.write_text(json.dumps(payload), encoding="utf-8")

        result = evaluate_targeted_bug_report(
            issue_path=issue,
            ground_truth_path=GROUND_TRUTH,
        )
        assert result["report_status"] == "incomplete"
        assert result["missing_report_fields"] == ["pinpoint"]
        assert result["report_complete"] is False
        assert result["pinpoint_aligned"] is False
        assert result["reward"] == 0.0


def test_targeted_evaluation_short_circuits_invalid_report_status() -> None:
    with _temp_test_dir("_tmp_gbqa_targeted_invalid") as temp_root:
        issue = temp_root / "issue.json"
        _matching_issue(issue)
        payload = json.loads(issue.read_text(encoding="utf-8"))
        payload["report_status"] = "invalid"
        payload["exit_status"] = "completed"
        issue.write_text(json.dumps(payload), encoding="utf-8")

        result = evaluate_targeted_bug_report(
            issue_path=issue,
            ground_truth_path=GROUND_TRUTH,
        )
        assert result["report_status"] == "invalid"
        assert result["exit_status"] == "completed"
        assert result["report_complete"] is False
        assert result["pinpoint_aligned"] is False
        assert result["reward"] == 0.0


def test_targeted_evaluation_treats_empty_pinpoint_locator_as_incomplete() -> None:
    with _temp_test_dir("_tmp_gbqa_targeted_empty_pinpoint") as temp_root:
        issue = temp_root / "issue.json"
        _matching_issue(issue)
        payload = json.loads(issue.read_text(encoding="utf-8"))
        payload["report_status"] = "complete"
        payload["issue"]["pinpoint"] = {
            "file": "",
            "function": "",
            "rationale": "Likely a light-source calculation problem.",
        }
        issue.write_text(json.dumps(payload), encoding="utf-8")

        result = evaluate_targeted_bug_report(
            issue_path=issue,
            ground_truth_path=GROUND_TRUTH,
        )
        assert result["report_status"] == "incomplete"
        assert result["missing_report_fields"] == ["pinpoint"]
        assert result["report_complete"] is False
        assert result["reward"] == 0.0


def test_targeted_evaluation_accepts_nested_pinpoint_locations() -> None:
    with _temp_test_dir("_tmp_gbqa_targeted_locations") as temp_root:
        issue = temp_root / "issue.json"
        _matching_issue(issue)
        payload = json.loads(issue.read_text(encoding="utf-8"))
        payload["issue"]["pinpoint"] = {
            "locations": [
                {
                    "file": "backend/game/actions.py",
                    "class": "ActionHandler",
                    "function": "handle_combine",
                    "qualified_name": "ActionHandler.handle_combine",
                    "rationale": "The combine prerequisite check is off by one.",
                }
            ],
            "rationale": "The final key assembly gate is implemented in the action handler.",
        }
        issue.write_text(json.dumps(payload), encoding="utf-8")

        result = evaluate_targeted_bug_report(
            issue_path=issue,
            ground_truth_path=GROUND_TRUTH,
        )
        assert result["report_status"] == "complete"
        assert result["pinpoint_aligned"] is True
        assert result["reward"] == 1.0


def test_targeted_evaluation_accepts_patch_style_pinpoint() -> None:
    with _temp_test_dir("_tmp_gbqa_targeted_patch") as temp_root:
        issue = temp_root / "issue.json"
        _matching_issue(issue)
        payload = json.loads(issue.read_text(encoding="utf-8"))
        payload["issue"]["pinpoint"] = {
            "patch": (
                "diff --git a/backend/game/actions.py b/backend/game/actions.py\n"
                "@@ def handle_combine(self, game):\n"
                "-    if len(owned_fragments) < 2:\n"
                "-        missing = 2 - len(owned_fragments)\n"
                "+    if len(owned_fragments) < 3:\n"
                "+        missing = 3 - len(owned_fragments)\n"
            ),
            "rationale": "SWE-style minimal patch for the failing prerequisite gate.",
        }
        issue.write_text(json.dumps(payload), encoding="utf-8")

        result = evaluate_targeted_bug_report(
            issue_path=issue,
            ground_truth_path=GROUND_TRUTH,
        )
        assert result["report_status"] == "complete"
        assert result["pinpoint_aligned"] is True
        assert result["reward"] == 1.0


def main() -> None:
    test_require_rewardkit_imports()
    test_primary_reward_score_prefers_reward_key()
    test_write_post_rewardkit_artifacts_preserves_reward_json()
    test_run_task_verifier_with_rewardkit_layout()
    test_rewardkit_discovers_rule_based_criteria()
    test_dark_castle_verifier_env_has_subscription_defaults()
    test_template_installs_rule_based_targeted_verifier()
    test_rewardkit_dependency_error_message()
    test_targeted_evaluation_scores_matching_issue()
    test_targeted_evaluation_rejects_wrong_function()
    test_targeted_evaluation_short_circuits_incomplete_report_status()
    test_targeted_evaluation_short_circuits_invalid_report_status()
    test_targeted_evaluation_treats_empty_pinpoint_locator_as_incomplete()
    test_targeted_evaluation_accepts_nested_pinpoint_locations()
    test_targeted_evaluation_accepts_patch_style_pinpoint()
    print("gbqa rewards tests passed")


if __name__ == "__main__":
    main()
