"""Smoke test for backend-specific endpoint resolution in run_agent."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from run_agent import (
    _apply_harness_mode,
    _apply_task_metadata,
    _register_interaction_mode_tools,
    _resolve_task_endpoints,
    build_log_tool_sources,
)
from src.config import Config
from src.execution_backends import resolve_backend_spec
from src.log_sources import (
    AgentTrajectoryLogSource,
    FileDirectoryRuntimeLogSource,
    FileRuntimeLogSource,
)
from src.tool_registry import ToolRegistry


def main() -> None:
    service_base_url, frontend_url = _resolve_task_endpoints(
        backend_type="api",
        backend_settings={},
        task_id="demo",
        task_config={"base_url": "http://example.test/api/agent"},
    )
    assert service_base_url == "http://example.test/api/agent"
    assert frontend_url == ""

    service_base_url, frontend_url = _resolve_task_endpoints(
        backend_type="playwright_mcp",
        backend_settings={},
        task_id="demo",
        task_config={"frontend_url": "http://example.test/app"},
    )
    assert service_base_url == ""
    assert frontend_url == "http://example.test/app"

    service_base_url, frontend_url = _resolve_task_endpoints(
        backend_type="computer_use",
        backend_settings={},
        task_id="demo",
        task_config={"frontend_url": "http://example.test/app"},
    )
    assert service_base_url == ""
    assert frontend_url == "http://example.test/app"

    config = Config(
        raw={
            "run": {"interaction_mode": "api"},
            "interaction": {
                "primary": "playwright_mcp",
                "adapters": {"playwright_mcp": {}},
            },
        },
        root_dir=ROOT_DIR,
    )
    _apply_task_metadata(
        config,
        os.path.join(ROOT_DIR, "..", "gbqa", "tasks", "dark-castle", "gbqa.yaml"),
    )
    injected_task = config.get_task("dark-castle")
    assert injected_task["base_url"] == "http://127.0.0.1:5000/api/agent"
    assert injected_task["frontend_url"] == "http://127.0.0.1:5000/"
    assert "ga" + "mes" not in config.raw
    assert config.get_section("interaction")["primary"] == "api"
    assert config.get_section("interaction")["adapters"]["api"]["base_url"] == (
        "http://127.0.0.1:5000/api/agent"
    )
    assert config.get_section("interaction")["adapters"]["logs"]["enabled"] is True

    computer_config = Config(
        raw={
            "run": {"interaction_mode": "computer_use"},
            "interaction": {
                "primary": "api",
                "adapters": {"computer_use": {}},
            },
        },
        root_dir=ROOT_DIR,
    )
    _apply_task_metadata(
        computer_config,
        os.path.join(ROOT_DIR, "..", "gbqa", "tasks", "dark-castle", "gbqa.yaml"),
    )
    computer_interaction = computer_config.get_section("interaction")
    assert computer_interaction["primary"] == "computer_use"
    assert computer_interaction["adapters"]["computer_use"]["server_url"] == (
        "http://127.0.0.1:8030"
    )
    assert computer_interaction["adapters"]["computer_use"]["frontend_url"] == (
        "http://127.0.0.1:5000/"
    )

    default_config = Config(
        raw={
            "run": {"interaction_profile": "default"},
            "interaction": {
                "primary": "computer_use",
                "adapters": {"api": {}, "playwright_mcp": {}, "computer_use": {}},
            },
        },
        root_dir=ROOT_DIR,
    )
    _apply_task_metadata(
        default_config,
        os.path.join(ROOT_DIR, "..", "gbqa", "tasks", "dark-castle", "gbqa.yaml"),
    )
    default_run = default_config.get_section("run")
    default_interaction = default_config.get_section("interaction")
    assert default_run["interaction_profile"] == "default"
    assert default_run["interaction_mode"] == "api"
    assert default_run["enabled_interaction_modes"] == [
        "api",
        "browser",
        "computer_use",
    ]
    assert default_interaction["primary"] == "api"
    assert default_interaction["primary_mode"] == "api"
    assert default_interaction["enabled_modes"] == [
        "api",
        "browser",
        "computer_use",
    ]
    assert default_interaction["enabled_backends"] == [
        "api",
        "playwright_mcp",
        "computer_use",
    ]
    default_spec = resolve_backend_spec(default_config)
    assert default_spec.backend_type == "api"
    assert default_spec.primary_mode == "api"
    assert default_spec.enabled_modes == ["api", "browser", "computer_use"]
    assert default_spec.enabled_backends == [
        "api",
        "playwright_mcp",
        "computer_use",
    ]

    default_browser_config = Config(
        raw={
            "run": {
                "interaction_profile": "default",
                "interaction_mode": "browser",
            },
            "interaction": {
                "primary": "api",
                "adapters": {"api": {}, "playwright_mcp": {}, "computer_use": {}},
            },
        },
        root_dir=ROOT_DIR,
    )
    _apply_task_metadata(
        default_browser_config,
        os.path.join(ROOT_DIR, "..", "gbqa", "tasks", "dark-castle", "gbqa.yaml"),
    )
    assert default_browser_config.get_section("run")["interaction_profile"] == "default"
    assert default_browser_config.get_section("run")["interaction_mode"] == "browser"
    assert default_browser_config.get_section("interaction")["primary"] == (
        "playwright_mcp"
    )
    assert default_browser_config.get_section("interaction")["enabled_modes"] == [
        "api",
        "browser",
        "computer_use",
    ]

    _apply_harness_mode(default_config, "minimal")
    assert default_config.get_section("harness")["mode"] == "minimal"
    assert default_config.get_section("interaction")["adapters"]["logs"]["enabled"] is False
    assert default_config.get_section("interaction")["adapters"]["code"]["enabled"] is False
    assert default_config.get_section("tool_policy")["auto_log_analysis"]["enabled"] is False
    assert default_config.get_section("tool_policy")["auto_code_lookup"]["enabled"] is False
    assert default_config.get_section("subagents")["enabled"] is False
    assert default_config.get_section("subagents")["explorer"]["enabled"] is False

    _apply_harness_mode(default_config, "full")
    assert default_config.get_section("harness")["mode"] == "full"
    assert default_config.get_section("interaction")["adapters"]["logs"]["enabled"] is True
    assert default_config.get_section("interaction")["adapters"]["code"]["enabled"] is True
    assert default_config.get_section("tool_policy")["auto_log_analysis"]["enabled"] is True
    assert default_config.get_section("tool_policy")["auto_code_lookup"]["enabled"] is True
    assert default_config.get_section("subagents")["enabled"] is True
    assert default_config.get_section("subagents")["explorer"]["enabled"] is True
    assert default_config.get_section("subagents")["code_localizer"]["enabled"] is True

    sources = build_log_tool_sources(
        {
            "enabled": True,
            "sources": [
                {
                    "name": "server",
                    "kind": "file",
                    "path": "/logs/runtime/server.log",
                },
                {
                    "name": "sessions",
                    "kind": "file_directory",
                    "path": "/sandbox/software/example/.cache/log",
                    "glob": "game_*.json",
                },
            ],
        }
    )
    assert any(isinstance(source, AgentTrajectoryLogSource) for source in sources)
    assert any(isinstance(source, FileRuntimeLogSource) for source in sources)
    assert any(isinstance(source, FileDirectoryRuntimeLogSource) for source in sources)

    registry = ToolRegistry()
    _register_interaction_mode_tools(
        registry=registry,
        enabled_modes=["api", "browser", "computer_use"],
        primary_mode="api",
        operator=object(),
        backend=object(),
        task_id="demo",
    )
    visible_tools = {tool.name for tool in registry.list_visible_tools()}
    assert {"api_action", "browser_action", "computer_action"} <= visible_tools
    print("run_agent endpoint resolution smoke test passed")


if __name__ == "__main__":
    main()
