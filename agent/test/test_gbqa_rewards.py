"""Tests for Harbor Rewardkit-compatible GBQA verifier outputs."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(ROOT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gbqa.rewards.matching import evaluate_bug_report
from gbqa.rewards.output import primary_reward_score, write_post_rewardkit_artifacts
from gbqa.rewards.runner import RewardkitDependencyError, require_rewardkit, run_task_verifier
from gbqa.rewards.template import install_task_verifier_tests


TASK_TESTS_DIR = (
    Path(REPO_ROOT) / "gbqa" / "tasks" / "dark-castle" / "tests"
)
GROUND_TRUTH = (
    Path(REPO_ROOT) / "gbqa" / "tasks" / "dark-castle" / "bugs" / "dark-castle.json"
)


def _programmatic_tests_dir(temp_root: Path) -> Path:
    """Copy verifier tests without the LLM judge dimension (no API key needed)."""

    destination = temp_root / "tests"
    shutil.copytree(
        TASK_TESTS_DIR,
        destination,
        ignore=shutil.ignore_patterns("quality"),
    )
    return destination


def test_require_rewardkit_imports() -> None:
    rk = require_rewardkit()
    assert hasattr(rk, "run")


def test_primary_reward_score_prefers_reward_key() -> None:
    assert primary_reward_score({"reward": 0.4, "recall": 0.2}) == 0.4
    assert primary_reward_score({"recall": 0.2}) == 0.2


def test_write_post_rewardkit_artifacts_preserves_reward_json() -> None:
    temp_root = Path(REPO_ROOT) / "agent" / "test" / "_tmp_gbqa_rewards"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    (temp_root / "reward.json").write_text(
        json.dumps({"recall": 0.5, "precision": 1.0, "reward": 0.5}),
        encoding="utf-8",
    )
    evaluation = {
        "reward": 0.5,
        "recall": 0.5,
        "precision": 1.0,
        "matched": 1,
        "total_predicted": 1,
        "total_ground_truth": 2,
        "details": [],
    }
    scores = write_post_rewardkit_artifacts(
        {"recall": 0.5, "precision": 1.0, "reward": 0.5},
        evaluation,
        temp_root,
    )
    assert scores["reward"] == 0.5
    reward_payload = json.loads((temp_root / "reward.json").read_text())
    assert reward_payload == {
        "recall": 0.5,
        "precision": 1.0,
        "reward": 0.5,
    }
    assert (temp_root / "reward.txt").read_text().strip() == "0.5"
    details = json.loads((temp_root / "reward-details.json").read_text())
    assert details["gbqa"]["matched"] == 1
    assert (temp_root / "gbqa_result.json").exists()
    shutil.rmtree(temp_root, ignore_errors=True)


def test_run_task_verifier_with_rewardkit_layout() -> None:
    temp_root = Path(REPO_ROOT) / "agent" / "test" / "_tmp_gbqa_rewardkit"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    trace_path = temp_root / "trace.jsonl"
    trace_path.write_text('{"type":"trace","step":1}\n', encoding="utf-8")
    os.environ["GBQA_TRAJECTORY_PATH"] = str(trace_path)
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
        tests_dir=_programmatic_tests_dir(temp_root),
        workspace=temp_root,
        out_dir=out_dir,
        bugs_path=bugs,
        ground_truth_path=GROUND_TRUTH,
    )
    assert "recall" in scores
    assert "precision" in scores
    assert "reward" in scores
    assert "trajectory" in scores
    reward_payload = json.loads((out_dir / "reward.json").read_text())
    assert isinstance(reward_payload["recall"], (int, float))
    assert isinstance(reward_payload["precision"], (int, float))
    details = json.loads((out_dir / "reward-details.json").read_text())
    assert "recall" in details
    assert "precision" in details
    assert "gbqa" in details
    shutil.rmtree(temp_root, ignore_errors=True)


def test_rewardkit_dependency_error_message() -> None:
    assert "harbor-rewardkit is required" in RewardkitDependencyError(
        "harbor-rewardkit is required for GBQA verification. "
        "Install it with: pip install harbor-rewardkit"
    ).args[0]


def test_quality_toml_is_discoverable() -> None:
    rk = require_rewardkit()
    temp_root = Path(REPO_ROOT) / "agent" / "test" / "_tmp_gbqa_quality_discover"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    rewards = rk.discover(TASK_TESTS_DIR, workspace=temp_root)
    reward_names = {reward.name for reward in rewards}
    assert "quality" in reward_names
    quality_rewards = [reward for reward in rewards if reward.name == "quality"]
    assert len(quality_rewards) == 1
    assert quality_rewards[0].judge is not None
    shutil.rmtree(temp_root, ignore_errors=True)


def test_quality_toml_supports_subscription_agent_judges() -> None:
    rk = require_rewardkit()
    temp_root = Path(REPO_ROOT) / "agent" / "test" / "_tmp_gbqa_quality_agents"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    previous = os.environ.get("REWARDKIT_JUDGE")
    try:
        for judge_name in ("claude-code", "codex"):
            os.environ["REWARDKIT_JUDGE"] = judge_name
            rewards = rk.discover(TASK_TESTS_DIR, workspace=temp_root)
            quality_reward = next(reward for reward in rewards if reward.name == "quality")
            assert quality_reward.judge is not None
            assert getattr(quality_reward.judge, "agent", "") == judge_name
    finally:
        if previous is None:
            os.environ.pop("REWARDKIT_JUDGE", None)
        else:
            os.environ["REWARDKIT_JUDGE"] = previous
        shutil.rmtree(temp_root, ignore_errors=True)


def test_quality_toml_references_ground_truth_and_agent_bugs() -> None:
    quality_toml = TASK_TESTS_DIR / "quality" / "quality.toml"
    text = quality_toml.read_text(encoding="utf-8")
    assert "/tests/bugs/dark-castle.json" in text
    assert "/logs/agent/gbqa/bugs.json" in text
    prompt = TASK_TESTS_DIR / "quality" / "semantic_matching.md"
    prompt_text = prompt.read_text(encoding="utf-8")
    assert "{criteria}" in prompt_text
    assert "/tests/bugs/dark-castle.json" in prompt_text
    assert "/logs/agent/gbqa/bugs.json" in prompt_text


def test_dark_castle_verifier_env_has_subscription_defaults() -> None:
    task_toml = Path(REPO_ROOT) / "gbqa" / "tasks" / "dark-castle" / "task.toml"
    config = tomllib.loads(task_toml.read_text(encoding="utf-8"))
    verifier_env = config["verifier"]["env"]
    assert verifier_env["REWARDKIT_JUDGE"] == "${REWARDKIT_JUDGE:-openai/gpt-4o}"
    assert verifier_env["REWARDKIT_MODEL"] == "${REWARDKIT_MODEL:-}"
    assert verifier_env["REWARDKIT_FORCE_OAUTH"] == "${REWARDKIT_FORCE_OAUTH:-}"
    assert verifier_env["JUDGE_AGENT"] == "${JUDGE_AGENT:-}"
    assert verifier_env["JUDGE_MODEL"] == "${JUDGE_MODEL:-}"
    assert verifier_env["JUDGE_CODEX_MODEL"] == "${JUDGE_CODEX_MODEL:-}"
    assert verifier_env["OPENAI_API_BASE"].endswith("https://zenmux.ai/api/v1}")
    assert verifier_env["ANTHROPIC_AUTH_TOKEN"] == "${ANTHROPIC_AUTH_TOKEN:-}"
    assert verifier_env["CLAUDE_CODE_OAUTH_TOKEN"] == "${CLAUDE_CODE_OAUTH_TOKEN:-}"
    assert verifier_env["CLAUDE_FORCE_OAUTH"] == "${CLAUDE_FORCE_OAUTH:-}"
    assert verifier_env["CODEX_AUTH_JSON_B64"] == "${CODEX_AUTH_JSON_B64:-}"
    assert verifier_env["CODEX_FORCE_API_KEY"] == "${CODEX_FORCE_API_KEY:-}"
    assert verifier_env["CODEX_ACCESS_TOKEN"] == "${CODEX_ACCESS_TOKEN:-}"
    assert all(":-" in value for value in verifier_env.values())


def test_template_installs_subscription_ready_quality_prompt() -> None:
    temp_root = Path(REPO_ROOT) / "agent" / "test" / "_tmp_gbqa_template_quality"
    shutil.rmtree(temp_root, ignore_errors=True)
    install_task_verifier_tests(
        temp_root,
        ground_truth_path="/tests/bugs/example.json",
    )
    prompt_text = (temp_root / "quality" / "semantic_matching.md").read_text(
        encoding="utf-8"
    )
    quality_text = (temp_root / "quality" / "quality.toml").read_text(
        encoding="utf-8"
    )
    test_script = (temp_root / "test.sh").read_text(encoding="utf-8")
    assert "/tests/bugs/example.json" in prompt_text
    assert "/tests/bugs/example.json" in quality_text
    assert "__GBQA_GROUND_TRUTH__" not in prompt_text
    assert "JUDGE_AGENT" in test_script
    assert "JUDGE_CODEX_MODEL" in test_script
    assert "CODEX_AUTH_JSON_B64" in test_script
    shutil.rmtree(temp_root, ignore_errors=True)


def test_matching_evaluates_bug_reports() -> None:
    temp_root = Path(REPO_ROOT) / "agent" / "test" / "_tmp_gbqa_matching"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    bugs = temp_root / "bugs.json"
    bugs.write_text('{"bugs": []}', encoding="utf-8")
    result = evaluate_bug_report(bugs_path=bugs, ground_truth_path=GROUND_TRUTH)
    assert result["reward"] == 0.0
    shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    test_require_rewardkit_imports()
    test_primary_reward_score_prefers_reward_key()
    test_write_post_rewardkit_artifacts_preserves_reward_json()
    test_run_task_verifier_with_rewardkit_layout()
    test_quality_toml_is_discoverable()
    test_quality_toml_supports_subscription_agent_judges()
    test_quality_toml_references_ground_truth_and_agent_bugs()
    test_dark_castle_verifier_env_has_subscription_defaults()
    test_template_installs_subscription_ready_quality_prompt()
    test_rewardkit_dependency_error_message()
    test_matching_evaluates_bug_reports()
    print("gbqa rewards tests passed")


if __name__ == "__main__":
    main()
