"""Smoke tests for the GBQA Harbor + Daytona compatibility layer."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.src.config import load_config
from gbqa.harbor.agent import GBQAHarborAgent
from gbqa.harbor.config import render_agent_config
from gbqa.cli.harbor_run import build_harbor_command
from gbqa.env import load_root_dotenv
from gbqa.protocol.schemas import load_bug_candidates
from gbqa.reporting.export import export_harbor_artifacts
from gbqa.spec import load_gbqa_metadata
from gbqa.rewards.output import write_post_rewardkit_artifacts
from gbqa.rewards.value_based import evaluate_value_based_report


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
    assert metadata.evaluation_method == "value_based"
    assert metadata.value_rubric_version == "impact_scope_repro_v1"
    assert metadata.baseline_values_path.name == "baseline_values.json"
    assert metadata.validation_cases_path.name == "validation_cases.json"
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
    assert metadata.software_ready_path == "backend/app.py"
    assert metadata.runtime_start_workdir == "{software_install_dir}/backend"
    assert metadata.runtime_start_command == (
        "env PORT={service_port} setsid -f {python} app.py"
    )
    assert metadata.runtime_stdout_path == "/logs/runtime/dark-castle-server.log"
    assert metadata.runtime_artifact_exports == [
        {
            "source": "/sandbox/software/dark-castle/.cache/log/.",
            "destination": "/logs/runtime/software_session_logs/",
        }
    ]
    assert metadata.internal_log_sources == [
        {
            "name": "stdout_stderr",
            "kind": "file",
            "path": "/logs/runtime/dark-castle-server.log",
            "description": (
                "Dark Castle backend stdout/stderr captured by the GBQA "
                "environment launcher."
            ),
            "tail_bytes": 200000,
        },
        {
            "name": "software_session_logs",
            "kind": "file_directory",
            "path": "/sandbox/software/dark-castle/.cache/log",
            "glob": "game_*.json",
            "description": (
                "Dark Castle software-owned per-session JSON logs written by "
                "the game backend."
            ),
            "tail_bytes": 200000,
            "max_files": 5,
        }
    ]


def test_config_rendering() -> None:
    metadata = load_gbqa_metadata(TASK_METADATA_PATH)
    api_config = render_agent_config(metadata=metadata, interaction_mode="api", max_steps=3)
    api_payload = tomllib.loads(api_config)
    full_api_config = render_agent_config(
        metadata=metadata,
        interaction_mode="api",
        harness_mode="full",
        max_steps=3,
    )
    full_api_payload = tomllib.loads(full_api_config)
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
    computer_payload = tomllib.loads(computer_config)
    default_config = render_agent_config(
        metadata=metadata,
        interaction_mode="default",
        max_steps=3,
    )
    default_payload = tomllib.loads(default_config)
    assert 'primary = "api"' in api_config
    assert 'primary = "playwright_mcp"' in browser_config
    assert 'primary = "computer_use"' in computer_config
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
    assert api_payload["run"]["interaction_profile"] == "api"
    assert api_payload["run"]["harness_mode"] == "minimal"
    assert api_payload["run"]["task_metadata_path"] == (
        "/sandbox/gbqa/tasks/dark-castle/gbqa.yaml"
    )
    assert api_payload["harness"]["mode"] == "minimal"
    assert api_payload["run"]["enabled_interaction_modes"] == ["api"]
    assert api_payload["interaction"]["primary"] == "api"
    assert api_payload["interaction"]["enabled_modes"] == ["api"]
    assert api_payload["interaction"]["adapters"]["api"]["base_url"] == (
        "http://127.0.0.1:5000/api/agent"
    )
    assert default_payload["run"]["interaction_profile"] == "default"
    assert default_payload["run"]["interaction_mode"] == "api"
    assert default_payload["run"]["enabled_interaction_modes"] == [
        "api",
        "browser",
        "computer_use",
    ]
    assert default_payload["interaction"]["primary"] == "api"
    assert default_payload["interaction"]["primary_mode"] == "api"
    assert default_payload["interaction"]["enabled_modes"] == [
        "api",
        "browser",
        "computer_use",
    ]
    assert default_payload["interaction"]["enabled_backends"] == [
        "api",
        "playwright_mcp",
        "computer_use",
    ]
    assert api_payload["interaction"]["adapters"]["logs"]["enabled"] is False
    assert api_payload["interaction"]["adapters"]["logs"]["session_id_field"] == (
        metadata.service_session_id_field
    )
    log_sources = api_payload["interaction"]["adapters"]["logs"]["sources"]
    assert log_sources[0]["name"] == (
        "stdout_stderr"
    )
    assert log_sources[0]["path"] == (
        "/logs/runtime/dark-castle-server.log"
    )
    assert log_sources[1]["name"] == "software_session_logs"
    assert log_sources[1]["kind"] == "file_directory"
    assert log_sources[1]["glob"] == "game_*.json"
    assert "analysis_" + "enabled" not in api_payload["interaction"]["adapters"]["logs"]
    assert api_payload["interaction"]["adapters"]["code"]["enabled"] is False
    assert api_payload["tool_policy"]["auto_log_analysis"]["enabled"] is False
    assert api_payload["tool_policy"]["auto_code_lookup"]["enabled"] is False
    assert api_payload["tool_policy"]["end_conditions"]["end_on_terminal"] is False
    assert api_payload["hooks"]["enabled"] is True
    assert api_payload["hooks"]["diagnostics"] is False
    assert api_payload["hooks"]["context_injection"] is False
    assert api_payload["subagents"]["enabled"] is False
    assert api_payload["subagents"]["explorer"]["enabled"] is False
    assert full_api_payload["run"]["harness_mode"] == "full"
    assert full_api_payload["harness"]["mode"] == "full"
    assert full_api_payload["interaction"]["adapters"]["logs"]["enabled"] is True
    assert full_api_payload["interaction"]["adapters"]["code"]["enabled"] is True
    assert full_api_payload["interaction"]["adapters"]["code"]["root_dir"] == (
        "/sandbox/software/dark-castle"
    )
    assert full_api_payload["tool_policy"]["auto_log_analysis"]["enabled"] is True
    assert full_api_payload["tool_policy"]["auto_code_lookup"]["enabled"] is True
    assert full_api_payload["hooks"]["diagnostics"] is True
    assert full_api_payload["hooks"]["context_injection"] is True
    assert full_api_payload["subagents"]["enabled"] is True
    assert full_api_payload["subagents"]["explorer"]["enabled"] is True
    assert full_api_payload["subagents"]["log_analyst"]["enabled"] is True
    assert "input_token_limit" in api_payload["llm"]
    assert "context_token_limit" not in api_payload["llm"]
    assert "message_window_" + "size" not in api_payload["llm"]
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
    payload = tomllib.loads((ROOT_DIR / "agent" / "config.toml.example").read_text())
    assert "ga" + "mes" not in payload
    assert "code_tool_" + "provider" not in payload
    assert "runtime_log_" + "provider" not in payload
    assert "execution_backend" not in payload
    assert "interaction" in payload
    assert payload["run"]["harness_mode"] == "minimal"
    assert payload["harness"]["mode"] == "minimal"
    assert "logs" in payload["interaction"]["adapters"]
    assert payload["interaction"]["adapters"]["logs"] == {"enabled": False}
    assert payload["interaction"]["adapters"]["code"] == {"enabled": False}
    assert payload["hooks"]["enabled"] is True
    assert payload["hooks"]["diagnostics"] is False
    assert payload["subagents"]["enabled"] is False
    assert payload["subagents"]["code_localizer"]["enabled"] is False
    assert payload["tool_policy"]["auto_log_analysis"]["enabled"] is False
    assert payload["tool_policy"]["auto_code_lookup"]["enabled"] is False
    assert payload["tool_policy"]["end_conditions"]["end_on_terminal"] is False
    assert payload["run"]["interaction_profile"] == "default"
    assert payload["run"]["interaction_mode"] == "api"
    assert payload["interaction"]["enabled_modes"] == [
        "api",
        "browser",
        "computer_use",
    ]
    assert "input_token_limit" in payload["llm"]
    assert "context_token_limit" not in payload["llm"]
    assert "message_window_" + "size" not in payload["llm"]
    assert "reasoning" in payload["llm"]
    assert "memory_context_token_limit" in payload["memory"]
    assert "{ga" + "me_id}" not in payload["memory"]["long_term_file"]
    assert "{task_slug}" in payload["memory"]["long_term_file"]


def test_agent_config_loader_requires_toml() -> None:
    toml_path = ROOT_DIR / "agent" / "test" / "_tmp_config.toml"
    yaml_path = ROOT_DIR / "agent" / "test" / "_tmp_config.yaml"
    toml_path.write_text(
        (ROOT_DIR / "agent" / "config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    yaml_path.write_text("run:\n  interaction_mode: api\n", encoding="utf-8")
    try:
        config = load_config(str(toml_path))
        assert config.get_section("run")["interaction_profile"] == "default"
        assert config.get_section("run")["interaction_mode"] == "api"
        try:
            load_config(str(yaml_path))
        except ValueError as exc:
            assert ".toml" in str(exc)
        else:
            raise AssertionError("YAML config fallback must stay disabled")
    finally:
        toml_path.unlink(missing_ok=True)
        yaml_path.unlink(missing_ok=True)


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
                "evidence": {
                    "observed_fault": "The player can assemble the complete key with only two fragments.",
                    "minimal_reproduction": [
                        "Collect any two key fragments.",
                        "Execute combine.",
                    ],
                },
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

    task_dir = ROOT_DIR / "gbqa" / "tasks" / "dark-castle"
    result = evaluate_value_based_report(
        bugs_path=out_dir / "bugs.json",
        ground_truth_path=task_dir / "bugs" / "dark-castle.json",
        baseline_values_path=task_dir / "tests" / "value" / "baseline_values.json",
        validation_cases_path=task_dir / "tests" / "value" / "validation_cases.json",
    )
    assert result["total_ground_truth"] == 3
    assert result["verified_bug_count"] == 1
    assert result["agent_value"] > 0
    assert result["human_value"] == 15
    assert result["reward"] > 0

    verifier_dir = temp_root / "verifier"
    verifier_dir.mkdir(parents=True, exist_ok=True)
    (verifier_dir / "reward.json").write_text(
        json.dumps(
            {
                "reward": result["reward"],
                "agent_value": result["agent_value"],
                "human_value": result["human_value"],
                "verified_bug_count": result["verified_bug_count"],
                "evaluated_bug_count": result["evaluated_bug_count"],
            }
        ),
        encoding="utf-8",
    )
    write_post_rewardkit_artifacts(
        {
            "reward": result["reward"],
            "agent_value": result["agent_value"],
            "human_value": result["human_value"],
            "verified_bug_count": result["verified_bug_count"],
            "evaluated_bug_count": result["evaluated_bug_count"],
        },
        result,
        verifier_dir,
    )
    assert (verifier_dir / "reward.txt").exists()
    assert (verifier_dir / "reward.json").exists()
    assert (verifier_dir / "gbqa_result.json").exists()
    reward_payload = json.loads((verifier_dir / "reward.json").read_text())
    assert reward_payload["reward"] == result["reward"]
    assert reward_payload["agent_value"] == result["agent_value"]
    assert reward_payload["human_value"] == result["human_value"]
    assert all(
        isinstance(value, (int, float))
        for value in reward_payload.values()
    )
    assert (temp_root / "verifier" / "reward-details.json").exists()
    gbqa_result = json.loads((temp_root / "verifier" / "gbqa_result.json").read_text())
    assert gbqa_result["details"] == result["details"]
    assert gbqa_result["agent_value"] == result["agent_value"]
    shutil.rmtree(temp_root, ignore_errors=True)


def test_empty_and_malformed_reports_score_zero() -> None:
    temp_root = ROOT_DIR / "agent" / "test" / "_tmp_gbqa_verifier"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    truth = ROOT_DIR / "gbqa" / "tasks" / "dark-castle" / "bugs" / "dark-castle.json"

    empty = temp_root / "empty.json"
    empty.write_text('{"bugs": []}', encoding="utf-8")
    baseline = (
        ROOT_DIR
        / "gbqa"
        / "tasks"
        / "dark-castle"
        / "tests"
        / "value"
        / "baseline_values.json"
    )
    validation = (
        ROOT_DIR
        / "gbqa"
        / "tasks"
        / "dark-castle"
        / "tests"
        / "value"
        / "validation_cases.json"
    )
    assert (
        evaluate_value_based_report(
            bugs_path=empty,
            ground_truth_path=truth,
            baseline_values_path=baseline,
            validation_cases_path=validation,
        )["reward"]
        == 0.0
    )

    malformed = temp_root / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    malformed_result = evaluate_value_based_report(
        bugs_path=malformed,
        ground_truth_path=truth,
        baseline_values_path=baseline,
        validation_cases_path=validation,
    )
    assert malformed_result["reward"] == 0.0
    assert "error" in malformed_result
    shutil.rmtree(temp_root, ignore_errors=True)


def test_harbor_agent_command_construction() -> None:
    command = GBQAHarborAgent.build_run_command(max_steps=5)
    assert "/opt/venv/bin/python run_agent.py" in command
    assert "--task dark-castle" in command
    assert "--max-steps 5" in command
    assert "cd /sandbox/agent" in command
    assert "--config /sandbox/runtime/config.toml" in command
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


def test_harbor_agent_default_profile_enables_all_task_modes() -> None:
    agent = GBQAHarborAgent(logs_dir=Path("logs"), interaction_mode="default")
    assert agent.interaction_mode == "default"
    assert agent.harness_mode == "minimal"
    assert agent._enabled_interaction_modes() == ["api", "browser", "computer_use"]
    full_agent = GBQAHarborAgent(
        logs_dir=Path("logs"),
        interaction_mode="api",
        harness_mode="full",
    )
    assert full_agent.harness_mode == "full"


def test_harbor_run_wrapper_preserves_harbor_arguments() -> None:
    assert build_harbor_command(
        ["run", "-p", "gbqa/tasks/dark-castle"],
        env={},
    ) == [
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
        ],
        env={},
    )
    assert command[:3] == ["harbor", "run", "-p"]
    overlay_path = Path(command[3])
    assert overlay_path.name == "dark-castle-computer-use"
    assert overlay_path.parent.name == "harbor_task_overlays"
    assert overlay_path.parent.parent.name == "tmp"
    assert Path(command[3], "environment", "Dockerfile").exists()
    overlay_dockerfile = Path(command[3], "environment", "Dockerfile").read_text()
    assert "@playwright/mcp" not in overlay_dockerfile
    default_command = build_harbor_command(
        [
            "run",
            "-p",
            str(ROOT_DIR / "gbqa" / "tasks" / "dark-castle"),
            "--ak",
            "interaction_mode=default",
        ],
        env={},
    )
    assert Path(default_command[3]).name == "dark-castle-computer-use"
    default_profile_command = build_harbor_command(
        [
            "run",
            "-p",
            str(ROOT_DIR / "gbqa" / "tasks" / "dark-castle"),
            "--ak",
            "interaction_profile=default",
        ],
        env={},
    )
    assert Path(default_profile_command[3]).name == "dark-castle-computer-use"


def test_harbor_run_wrapper_selects_builtin_task_agents() -> None:
    claude_command = build_harbor_command(
        [
            "run",
            "-p",
            "gbqa/tasks/dark-castle",
            "--gbqa-task-runner",
            "claude-code",
            "--gbqa-agent-model",
            "anthropic/claude-opus-4-7",
            "--gbqa-agent-auth",
            "subscription",
        ],
        env={"CLAUDE_CODE_OAUTH_TOKEN": "claude-token"},
    )
    assert claude_command[:5] == [
        "harbor",
        "run",
        "-p",
        "gbqa/tasks/dark-castle",
        "-a",
    ]
    assert "claude-code" in claude_command
    assert ["-m", "anthropic/claude-opus-4-7"] == claude_command[
        claude_command.index("-m") : claude_command.index("-m") + 2
    ]
    assert "--ae" in claude_command
    assert "CLAUDE_CODE_OAUTH_TOKEN=claude-token" in claude_command
    assert "CLAUDE_FORCE_OAUTH=1" in claude_command

    codex_command = build_harbor_command(
        [
            "run",
            "-p",
            "gbqa/tasks/dark-castle",
            "--gbqa-task-runner=codex",
            "--gbqa-agent-model",
            "gpt-5",
            "--gbqa-agent-auth",
            "subscription",
            "--gbqa-codex-auth-file",
            "/tmp/codex-auth.json",
        ],
        env={},
    )
    assert "codex" in codex_command
    assert "CODEX_AUTH_JSON_PATH=/tmp/codex-auth.json" in codex_command

    codex_api_command = build_harbor_command(
        [
            "run",
            "-p",
            "gbqa/tasks/dark-castle",
            "--gbqa-task-runner",
            "codex",
        ],
        env={
            "CODEX_FORCE_API_KEY": "1",
            "API_KEY": "provider-neutral-key",
            "BASE_URL": "https://example.test/v1",
        },
    )
    assert "OPENAI_API_KEY=provider-neutral-key" in codex_api_command
    assert "OPENAI_BASE_URL=https://example.test/v1" in codex_api_command


def test_harbor_run_wrapper_selects_rewardkit_agent_judges() -> None:
    temp_root = ROOT_DIR / "agent" / "test" / "_tmp_codex_auth"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    auth_path = temp_root / "auth.json"
    auth_path.write_text('{"tokens": "example"}', encoding="utf-8")
    try:
        command = build_harbor_command(
            [
                "run",
                "-p",
                "gbqa/tasks/dark-castle",
                "--gbqa-judge",
                "codex",
                "--gbqa-judge-model",
                "gpt-5.5",
                "--gbqa-judge-auth",
                "subscription",
                "--gbqa-codex-auth-file",
                str(auth_path),
            ],
            env={},
        )
        assert "REWARDKIT_JUDGE=codex" in command
        assert "REWARDKIT_MODEL=gpt-5.5" in command
        encoded = next(
            item.removeprefix("CODEX_AUTH_JSON_B64=")
            for item in command
            if item.startswith("CODEX_AUTH_JSON_B64=")
        )
        assert base64.b64decode(encoded).decode("utf-8") == '{"tokens": "example"}'

        token_command = build_harbor_command(
            [
                "run",
                "-p",
                "gbqa/tasks/dark-castle",
                "--gbqa-judge",
                "codex",
                "--gbqa-judge-auth",
                "subscription",
            ],
            env={"CODEX_ACCESS_TOKEN": "codex-token"},
        )
        assert "CODEX_ACCESS_TOKEN=codex-token" in token_command
        assert "REWARDKIT_FORCE_OAUTH=1" in token_command
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_harbor_run_wrapper_supports_cowork_judge_alias_env() -> None:
    command = build_harbor_command(
        ["run", "-p", "gbqa/tasks/dark-castle"],
        env={
            "JUDGE_AGENT": "claude-code",
            "JUDGE_MODEL": "claude-opus-4-7",
            "CLAUDE_CODE_OAUTH_TOKEN": "claude-token",
            "GBQA_JUDGE_AUTH": "subscription",
        },
    )
    assert "REWARDKIT_JUDGE=claude-code" in command
    assert "REWARDKIT_MODEL=claude-opus-4-7" in command
    assert "CLAUDE_CODE_OAUTH_TOKEN=claude-token" in command
    assert "CLAUDE_FORCE_OAUTH=1" in command
    assert "REWARDKIT_FORCE_OAUTH=1" in command


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
            self.upload_snapshots = {}

        async def exec(self, command, **kwargs):  # noqa: ANN001
            self.commands.append((command, kwargs))
            return Result()

        async def upload_dir(self, source_dir, target_dir):  # noqa: ANN001
            self.uploads.append((str(source_dir), target_dir))
            source_path = Path(source_dir)
            self.upload_snapshots[target_dir] = sorted(
                path.relative_to(source_path).as_posix()
                for path in source_path.rglob("*")
                if path.is_file()
            )

    env = FakeEnvironment()
    agent = GBQAHarborAgent(logs_dir=Path("logs"), interaction_mode="api", max_steps=2)
    await agent.setup(env)
    assert any(target == "/sandbox/agent" for _, target in env.uploads)
    assert any(target == "/sandbox/gbqa" for _, target in env.uploads)
    assert "run_agent.py" in env.upload_snapshots["/sandbox/agent"]
    assert "config.toml.example" in env.upload_snapshots["/sandbox/agent"]
    assert any(
        path.startswith("src/") for path in env.upload_snapshots["/sandbox/agent"]
    )
    assert any(
        path.startswith("prompts/") for path in env.upload_snapshots["/sandbox/agent"]
    )
    assert "skills/code/SKILL.md" in env.upload_snapshots["/sandbox/agent"]
    assert "skills/logs/SKILL.md" in env.upload_snapshots["/sandbox/agent"]
    assert not any(
        path.startswith((".playwright-mcp/", "reports/", "memory/", "tmp/"))
        or path == ".env"
        for path in env.upload_snapshots["/sandbox/agent"]
    )
    assert not any("hub" in target and "dark-castle" in target for _, target in env.uploads)
    assert any(
        "https://github.com/Tsumugii24/dark-castle/archive/refs/tags/v0.1.0.tar.gz"
        in command
        for command, _ in env.commands
    )
    assert any("/sandbox/software/dark-castle" in command for command, _ in env.commands)
    assert any("config.toml" in command for command, _ in env.commands)


def test_harbor_agent_setup_with_fake_environment() -> None:
    asyncio.run(_exercise_setup_with_fake_environment())


async def _exercise_runtime_startup_log_capture() -> None:
    class Result:
        return_code = 0

    class FakeEnvironment:
        def __init__(self) -> None:
            self.commands = []

        async def exec(self, command, **kwargs):  # noqa: ANN001
            self.commands.append((command, kwargs))
            return Result()

    env = FakeEnvironment()
    agent = GBQAHarborAgent(logs_dir=Path("logs"), interaction_mode="api")
    await agent._start_software_service(env)

    command = env.commands[-1][0]
    assert "mkdir -p /logs/agent/gbqa /logs/runtime" in command
    assert "> /logs/runtime/dark-castle-server.log" in command
    assert "2>&1" in command


def test_runtime_startup_captures_server_stdout_to_runtime_logs() -> None:
    asyncio.run(_exercise_runtime_startup_log_capture())


async def _exercise_runtime_log_artifact_export() -> None:
    class Result:
        return_code = 0

    class FakeEnvironment:
        def __init__(self) -> None:
            self.commands = []

        async def exec(self, command, **kwargs):  # noqa: ANN001
            self.commands.append((command, kwargs))
            return Result()

    env = FakeEnvironment()
    agent = GBQAHarborAgent(logs_dir=Path("logs"), interaction_mode="api")
    await agent._export_artifacts(env)

    command = env.commands[-1][0]
    assert "cp -a /sandbox/software/dark-castle/.cache/log/." in command
    assert "/logs/runtime/software_session_logs/" in command
    assert "cp -a /logs/runtime/." in command
    assert "/logs/agent/gbqa/artifacts/runtime_logs/" in command


def test_export_artifacts_copies_runtime_logs() -> None:
    asyncio.run(_exercise_runtime_log_artifact_export())


async def _exercise_computer_use_setup_starts_no_gui_services() -> None:
    class Result:
        return_code = 0
        stdout = ""
        stderr = ""

    class FakeEnvironment:
        def __init__(self) -> None:
            self.commands = []

        async def exec(self, command, **kwargs):  # noqa: ANN001
            self.commands.append((command, kwargs))
            return Result()

        async def upload_dir(self, source_dir, target_dir):  # noqa: ANN001
            del source_dir, target_dir

    env = FakeEnvironment()
    agent = GBQAHarborAgent(
        logs_dir=Path("logs"),
        interaction_mode="computer_use",
        max_steps=2,
    )
    await agent.setup(env)
    assert not any("start-computer-server.sh" in command for command, _ in env.commands)


def test_computer_use_setup_starts_no_gui_services() -> None:
    asyncio.run(_exercise_computer_use_setup_starts_no_gui_services())


async def _exercise_computer_use_preflight_explains_default_environment() -> None:
    class Result:
        return_code = 1
        stdout = ""
        stderr = "missing start-vnc.sh"

    class FakeEnvironment:
        async def exec(self, command, **kwargs):  # noqa: ANN001
            del command, kwargs
            return Result()

    agent = GBQAHarborAgent(
        logs_dir=Path("logs"),
        interaction_mode="computer_use",
        max_steps=2,
    )
    try:
        await agent._start_computer_use_services(FakeEnvironment())
    except RuntimeError as exc:
        message = str(exc)
        assert "default non-GUI environment" in message
        assert "python -m gbqa.cli.harbor_run" in message
        assert "interaction_mode=computer_use" in message
    else:
        raise AssertionError("computer_use preflight failure should raise RuntimeError")


def test_computer_use_preflight_explains_default_environment() -> None:
    asyncio.run(_exercise_computer_use_preflight_explains_default_environment())


def main() -> None:
    test_metadata_loader()
    test_config_rendering()
    test_agent_harness_example_has_no_task_endpoints()
    test_agent_config_loader_requires_toml()
    test_artifact_export_and_verifier()
    test_empty_and_malformed_reports_score_zero()
    test_harbor_agent_command_construction()
    test_harbor_agent_defaults_to_zenmux_base_url()
    test_harbor_agent_default_profile_enables_all_task_modes()
    test_harbor_run_wrapper_preserves_harbor_arguments()
    test_harbor_agent_requires_model_key_and_name()
    test_root_dotenv_feeds_harbor_agent_runtime_env()
    test_harbor_agent_setup_with_fake_environment()
    test_runtime_startup_captures_server_stdout_to_runtime_logs()
    test_export_artifacts_copies_runtime_logs()
    test_computer_use_setup_starts_no_gui_services()
    test_computer_use_preflight_explains_default_environment()
    print("gbqa harbor smoke tests passed")


if __name__ == "__main__":
    main()
