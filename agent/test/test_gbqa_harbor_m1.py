"""Smoke tests for the Harbor + Daytona M1 compatibility layer."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from gbqa.harbor.agent import GBQAHarborAgent
from gbqa.harbor.config import render_agent_config
from gbqa.cli.harbor_run import build_harbor_command
from gbqa.env import load_root_dotenv
from gbqa.protocol.schemas import load_bug_candidates
from gbqa.reporting.export import export_harbor_artifacts
from gbqa.spec import load_gbqa_metadata
from gbqa.verifier import evaluate_bug_report, write_harbor_reward


TASK_METADATA_PATH = ROOT_DIR / "gbqa" / "tasks" / "dark-castle" / "gbqa.yaml"


def test_metadata_loader() -> None:
    metadata = load_gbqa_metadata(TASK_METADATA_PATH)
    assert metadata.task_id == "gbqa/dark-castle"
    assert metadata.task_slug == "dark-castle"
    assert metadata.task_title == "Dark Castle: Night of Awakening"
    assert metadata.default_provider == "daytona"
    assert metadata.default_interaction_mode == "api"
    assert metadata.supported_interaction_modes == ["api", "browser", "computer_use"]
    assert metadata.computer_use_server_url == "http://127.0.0.1:8030"
    assert metadata.interaction_adapter("computer_use")["display"] == {
        "width": 1280,
        "height": 720,
    }
    assert metadata.service_api_base_url == "http://127.0.0.1:5000/api/agent"
    assert metadata.service_frontend_url == "http://127.0.0.1:5000/"
    assert "Text adventure" in metadata.agent_profile
    assert metadata.software_type == "github_release"
    assert metadata.software_repository == "https://github.com/Tsumugii24/dark-castle"
    assert metadata.software_selected_release_role == "latest_minus_one"
    assert metadata.software_selected_version == "v0.1.0"
    assert metadata.software_latest_version == "v0.2.0"
    assert metadata.software_archive_url == (
        "https://github.com/Tsumugii24/dark-castle/archive/refs/tags/v0.1.0.tar.gz"
    )
    assert metadata.software_install_dir == "/sandbox/software/dark-castle"


def test_config_rendering() -> None:
    metadata = load_gbqa_metadata(TASK_METADATA_PATH)
    api_config = render_agent_config(metadata=metadata, interaction_mode="api", max_steps=3)
    api_payload = yaml.safe_load(api_config)
    browser_config = render_agent_config(
        metadata=metadata,
        interaction_mode="browser",
        max_steps=3,
    )
    computer_config = render_agent_config(
        metadata=metadata,
        interaction_mode="computer_use",
        max_steps=3,
    )
    computer_payload = yaml.safe_load(computer_config)
    assert "primary: api" in api_config
    assert "primary: playwright_mcp" in browser_config
    assert "primary: computer_use" in computer_config
    assert "http://127.0.0.1:5000/api/agent" in api_config
    assert "Dark Castle: Night of Awakening" in api_config
    assert "http://127.0.0.1:5000/" in browser_config
    assert computer_payload["interaction"]["primary"] == "computer_use"
    assert computer_payload["interaction"]["adapters"]["computer_use"]["server_url"] == (
        "http://127.0.0.1:8030"
    )
    assert computer_payload["interaction"]["adapters"]["computer_use"]["display"] == {
        "width": 1280,
        "height": 720,
    }
    assert "execution_backend" not in api_payload
    assert "code_tool_" + "provider" not in api_payload
    assert "runtime_log_" + "provider" not in api_payload
    assert api_payload["interaction"]["primary"] == "api"
    assert api_payload["interaction"]["adapters"]["api"]["base_url"] == (
        "http://127.0.0.1:5000/api/agent"
    )
    assert api_payload["interaction"]["adapters"]["logs"]["enabled"] is True
    assert api_payload["interaction"]["adapters"]["logs"]["session_id_field"] == (
        metadata.service_session_id_field
    )
    assert "analysis_" + "enabled" not in api_payload["interaction"]["adapters"]["logs"]
    assert api_payload["interaction"]["adapters"]["code"]["enabled"] is False
    assert "input_token_limit" in api_payload["llm"]
    assert "context_token_limit" not in api_payload["llm"]
    assert "message_window_" + "size" not in api_payload["llm"]
    assert "reset_between_" + "turns" not in api_payload["llm"]
    assert api_payload["llm"]["reasoning"]["mode"] == "auto"
    assert api_payload["memory"]["memory_context_token_limit"] == 12000
    assert api_payload["memory"]["long_term_file"].endswith(
        "/memory/{task_slug}/long_term.json"
    )
    assert api_payload["tasks"]["dark-castle"]["base_url"] == (
        "http://127.0.0.1:5000/api/agent"
    )
    assert "ga" + "mes" not in api_payload


def test_agent_harness_example_has_no_task_endpoints() -> None:
    payload = yaml.safe_load((ROOT_DIR / "agent" / "config.yaml.example").read_text())
    assert "ga" + "mes" not in payload
    assert "code_tool_" + "provider" not in payload
    assert "runtime_log_" + "provider" not in payload
    assert "execution_backend" not in payload
    assert "interaction" in payload
    assert "logs" in payload["interaction"]["adapters"]
    assert payload["interaction"]["adapters"]["logs"] == {"enabled": False}
    assert payload["run"]["interaction_mode"] in {"api", "browser", "computer_use"}
    assert "input_token_limit" in payload["llm"]
    assert "context_token_limit" not in payload["llm"]
    assert "message_window_" + "size" not in payload["llm"]
    assert "reset_between_" + "turns" not in payload["llm"]
    assert "reasoning" in payload["llm"]
    assert "memory_context_token_limit" in payload["memory"]
    assert "{ga" + "me_id}" not in payload["memory"]["long_term_file"]
    assert "{task_slug}" in payload["memory"]["long_term_file"]


def test_artifact_export_and_verifier() -> None:
    temp_root = ROOT_DIR / "agent" / "test" / "_tmp_gbqa_harbor"
    shutil.rmtree(temp_root, ignore_errors=True)
    report_dir = temp_root / "reports" / "dark-castle" / "run-001"
    out_dir = temp_root / "out"
    report_dir.mkdir(parents=True)
    report = {
        "metadata": {"source": "test"},
        "summary": "test report",
        "bugs": [
            {
                "title": "Key assembles with only two fragments",
                "description": "Running combine after two key fragments creates the full key.",
                "confidence": 0.9,
                "evidence": {},
                "tags": [],
            }
        ],
        "steps": [{"step": 1, "environment": {"artifacts": {}}}],
    }
    (report_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (report_dir / "trace.jsonl").write_text('{"step": 1}\n', encoding="utf-8")

    exported = export_harbor_artifacts(
        reports_root=temp_root / "reports",
        task_id="gbqa/dark-castle",
        out_dir=out_dir,
    )
    assert Path(exported["run"]).exists()
    assert Path(exported["bugs"]).exists()
    assert Path(exported["steps"]).exists()
    assert len(load_bug_candidates(out_dir / "bugs.json")) == 1

    result = evaluate_bug_report(
        bugs_path=out_dir / "bugs.json",
        ground_truth_path=ROOT_DIR / "gbqa" / "tasks" / "dark-castle" / "bugs" / "dark-castle.json",
        match_threshold=0.1,
    )
    assert result["matched"] == 1
    assert result["total_ground_truth"] == 3
    assert result["reward"] > 0

    write_harbor_reward(result, temp_root / "verifier")
    assert (temp_root / "verifier" / "reward.txt").exists()
    assert (temp_root / "verifier" / "reward.json").exists()
    assert (temp_root / "verifier" / "gbqa_result.json").exists()
    reward_payload = json.loads((temp_root / "verifier" / "reward.json").read_text())
    assert reward_payload == {"reward": result["reward"]}
    assert all(
        isinstance(value, (int, float))
        for value in reward_payload.values()
    )
    gbqa_result = json.loads((temp_root / "verifier" / "gbqa_result.json").read_text())
    assert gbqa_result["details"] == result["details"]
    assert gbqa_result["precision"] == result["precision"]
    shutil.rmtree(temp_root, ignore_errors=True)


def test_empty_and_malformed_reports_score_zero() -> None:
    temp_root = ROOT_DIR / "agent" / "test" / "_tmp_gbqa_verifier"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    truth = ROOT_DIR / "gbqa" / "tasks" / "dark-castle" / "bugs" / "dark-castle.json"

    empty = temp_root / "empty.json"
    empty.write_text('{"bugs": []}', encoding="utf-8")
    assert evaluate_bug_report(bugs_path=empty, ground_truth_path=truth)["reward"] == 0.0

    malformed = temp_root / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    malformed_result = evaluate_bug_report(bugs_path=malformed, ground_truth_path=truth)
    assert malformed_result["reward"] == 0.0
    assert "error" in malformed_result
    shutil.rmtree(temp_root, ignore_errors=True)


def test_harbor_agent_command_construction() -> None:
    command = GBQAHarborAgent.build_run_command(max_steps=5)
    assert "/opt/venv/bin/python run_agent.py" in command
    assert "--task dark-castle" in command
    assert "--max-steps 5" in command
    assert "cd /sandbox/agent" in command
    assert "--config /sandbox/runtime/config.yaml" in command
    assert "/logs/agent/gbqa/gbqa-agent.stdout" in command


def test_harbor_agent_defaults_to_zenmux_base_url() -> None:
    temp_root = ROOT_DIR / "agent" / "test" / "_tmp_no_env"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    keys = ["GBQA_ENV_FILE", "BASE_URL"]
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ.pop(key, None)
        os.environ["GBQA_ENV_FILE"] = str(temp_root / "missing.env")
        env = GBQAHarborAgent(logs_dir=Path("logs"), interaction_mode="api")._runtime_env()
        assert env["BASE_URL"] == "https://zenmux.ai/api/v1"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(temp_root, ignore_errors=True)


def test_harbor_run_wrapper_preserves_harbor_arguments() -> None:
    assert build_harbor_command(["run", "-p", "gbqa/tasks/dark-castle"]) == [
        "harbor",
        "run",
        "-p",
        "gbqa/tasks/dark-castle",
    ]
    command = build_harbor_command(
        [
            "run",
            "-p",
            str(ROOT_DIR / "gbqa" / "tasks" / "dark-castle"),
            "--ak",
            "interaction_mode=computer_use",
        ]
    )
    assert command[:3] == ["harbor", "run", "-p"]
    assert command[3].endswith("tmp/harbor_task_overlays/dark-castle-computer-use")
    assert Path(command[3], "environment", "Dockerfile").exists()
    overlay_dockerfile = Path(command[3], "environment", "Dockerfile").read_text()
    assert "@playwright/mcp" not in overlay_dockerfile


def test_harbor_agent_requires_model_key_and_name() -> None:
    try:
        GBQAHarborAgent._validate_runtime_env({"BASE_URL": "https://zenmux.ai/api/v1"})
    except RuntimeError as exc:
        assert "API_KEY" in str(exc)
        assert "MODEL_NAME" in str(exc)
        assert "BASE_URL" not in str(exc)
    else:
        raise AssertionError("API_KEY and MODEL_NAME must be required for model requests")


def test_root_dotenv_feeds_harbor_agent_runtime_env() -> None:
    temp_root = ROOT_DIR / "agent" / "test" / "_tmp_root_env"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    env_path = temp_root / ".env"
    env_path.write_text(
        "\n".join(
            [
                "DAYTONA_API_KEY=daytona-from-root",
                "API_KEY=api-key-from-root",
                "BASE_URL=https://example.test/v1",
                "MODEL_NAME=model-from-root",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    keys = [
        "GBQA_ENV_FILE",
        "DAYTONA_API_KEY",
        "API_KEY",
        "MODEL_NAME",
        "BASE_URL",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ.pop(key, None)
        os.environ["GBQA_ENV_FILE"] = str(env_path)

        assert load_root_dotenv() == env_path
        assert os.environ["DAYTONA_API_KEY"] == "daytona-from-root"

        agent = GBQAHarborAgent(logs_dir=Path("logs"), interaction_mode="api")
        runtime_env = agent._runtime_env()
        assert runtime_env["API_KEY"] == "api-key-from-root"
        assert runtime_env["MODEL_NAME"] == "model-from-root"
        assert runtime_env["BASE_URL"] == "https://example.test/v1"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(temp_root, ignore_errors=True)


async def _exercise_setup_with_fake_environment() -> None:
    class Result:
        return_code = 0

    class FakeEnvironment:
        def __init__(self) -> None:
            self.commands = []
            self.uploads = []

        async def exec(self, command, **kwargs):  # noqa: ANN001
            self.commands.append((command, kwargs))
            return Result()

        async def upload_dir(self, source_dir, target_dir):  # noqa: ANN001
            self.uploads.append((str(source_dir), target_dir))

    env = FakeEnvironment()
    agent = GBQAHarborAgent(logs_dir=Path("logs"), interaction_mode="api", max_steps=2)
    await agent.setup(env)
    assert any(target == "/sandbox/agent" for _, target in env.uploads)
    assert any(target == "/sandbox/gbqa" for _, target in env.uploads)
    assert not any("hub" in target and "dark-castle" in target for _, target in env.uploads)
    assert any(
        "https://github.com/Tsumugii24/dark-castle/archive/refs/tags/v0.1.0.tar.gz"
        in command
        for command, _ in env.commands
    )
    assert any("/sandbox/software/dark-castle" in command for command, _ in env.commands)
    assert any("config.yaml" in command for command, _ in env.commands)


def test_harbor_agent_setup_with_fake_environment() -> None:
    asyncio.run(_exercise_setup_with_fake_environment())


def main() -> None:
    test_metadata_loader()
    test_config_rendering()
    test_agent_harness_example_has_no_task_endpoints()
    test_artifact_export_and_verifier()
    test_empty_and_malformed_reports_score_zero()
    test_harbor_agent_command_construction()
    test_harbor_agent_defaults_to_zenmux_base_url()
    test_harbor_run_wrapper_preserves_harbor_arguments()
    test_harbor_agent_requires_model_key_and_name()
    test_root_dotenv_feeds_harbor_agent_runtime_env()
    test_harbor_agent_setup_with_fake_environment()
    print("gbqa harbor m1 smoke tests passed")


if __name__ == "__main__":
    main()
