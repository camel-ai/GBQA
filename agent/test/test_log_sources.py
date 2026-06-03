from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.log_sources import (
    AgentTrajectoryLogSource,
    FileDirectoryRuntimeLogSource,
    FileRuntimeLogSource,
    LogSourceSpec,
    build_log_sources,
)
from src.types import Action, Observation, StepRecord


def test_file_runtime_log_source_tails_file() -> None:
    tmp_path = Path(tempfile.mkdtemp(prefix="gbqa-log-source-"))
    log_path = tmp_path / "server.log"
    log_path.write_text("first line\nsecond line\n", encoding="utf-8")
    source = FileRuntimeLogSource(
        LogSourceSpec(
            name="server",
            kind="file",
            path=str(log_path),
            tail_bytes=32,
        )
    )

    result = source.read()

    assert result.success is True
    assert result.name == "server"
    assert result.kind == "file"
    assert "second line" in result.text
    assert result.metadata["path"] == str(log_path)


def test_file_runtime_log_source_reports_missing_file() -> None:
    tmp_path = Path(tempfile.mkdtemp(prefix="gbqa-log-source-"))
    source = FileRuntimeLogSource(
        LogSourceSpec(
            name="missing",
            kind="file",
            path=str(tmp_path / "missing.log"),
        )
    )

    result = source.read()

    assert result.success is False
    assert "does not exist" in result.error


def test_file_directory_runtime_log_source_reads_recent_matching_files() -> None:
    tmp_path = Path(tempfile.mkdtemp(prefix="gbqa-log-source-"))
    older = tmp_path / "game_older.json"
    newer = tmp_path / "game_newer.json"
    ignored = tmp_path / "server.log"
    older.write_text('{"turn": 1, "command": "look"}', encoding="utf-8")
    newer.write_text('{"turn": 2, "command": "north"}', encoding="utf-8")
    ignored.write_text("server stdout", encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    source = FileDirectoryRuntimeLogSource(
        LogSourceSpec(
            name="session_logs",
            kind="file_directory",
            path=str(tmp_path),
            glob="game_*.json",
            max_files=1,
        )
    )

    result = source.read()

    assert result.success is True
    assert result.name == "session_logs"
    assert "game_newer.json" in result.text
    assert "north" in result.text
    assert "game_older.json" not in result.text
    assert result.metadata["glob"] == "game_*.json"


def test_build_log_sources_supports_file_and_file_directory() -> None:
    sources = build_log_sources(
        [
            {"name": "stdout", "kind": "file", "path": "/logs/runtime/server.log"},
            {
                "name": "sessions",
                "kind": "file_directory",
                "path": "/tmp/sessions",
                "glob": "game_*.json",
            },
        ]
    )

    assert any(isinstance(source, FileRuntimeLogSource) for source in sources)
    assert any(isinstance(source, FileDirectoryRuntimeLogSource) for source in sources)


def test_agent_trajectory_source_converts_steps_to_commands() -> None:
    steps = [
        StepRecord(
            step=1,
            action=Action(tool="environment_action", command="look"),
            observation=Observation(
                success=True,
                message="You are in a hall.",
                state={},
                summary="You are in a hall.",
                env_state={"location": "hall"},
            ),
        ),
        StepRecord(
            step=2,
            action=Action(tool="code_search", command="Dragon"),
            observation=Observation(
                success=False,
                message="No matches.",
                state={},
                summary="No matches.",
                env_state={},
            ),
        ),
        StepRecord(
            step=3,
            action=Action(tool="log_analyze", command="analyze"),
            observation=Observation(
                success=True,
                message="No anomalies.",
                state={},
                summary="No anomalies.",
                env_state={},
            ),
        ),
        StepRecord(
            step=4,
            action=Action(tool="custom_probe", command="probe"),
            observation=Observation(
                success=True,
                message="Probe completed.",
                state={},
                summary="Probe completed.",
                env_state={},
            ),
        ),
    ]

    result = AgentTrajectoryLogSource().read({"steps": steps})

    assert result.success is True
    assert result.session["total_turns"] == 4
    assert result.session["commands"][0]["command"] == "look"
    assert result.session["commands"][0]["category"] == "environment_interactions"
    assert result.session["commands"][1]["tool"] == "code_search"
    assert result.session["commands"][1]["category"] == "code_tool_interactions"
    assert result.session["commands"][1]["response"]["success"] is False
    assert result.session["commands"][2]["category"] == "log_tool_interactions"
    assert result.session["commands"][3]["category"] == "other_tool_interactions"
    assert result.session["groups"]["environment_interactions"][0]["command"] == "look"
    assert result.session["groups"]["code_tool_interactions"][0]["tool"] == (
        "code_search"
    )
    assert result.session["groups"]["log_tool_interactions"][0]["tool"] == (
        "log_analyze"
    )
    assert result.session["groups"]["other_tool_interactions"][0]["tool"] == (
        "custom_probe"
    )
    assert result.session["category_counts"] == {
        "environment_interactions": 1,
        "code_tool_interactions": 1,
        "log_tool_interactions": 1,
        "other_tool_interactions": 1,
    }


def main() -> None:
    test_file_runtime_log_source_tails_file()
    test_file_runtime_log_source_reports_missing_file()
    test_file_directory_runtime_log_source_reads_recent_matching_files()
    test_build_log_sources_supports_file_and_file_directory()
    test_agent_trajectory_source_converts_steps_to_commands()
    print("log source tests passed")


if __name__ == "__main__":
    main()
