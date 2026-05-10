"""Smoke test for backend-specific endpoint resolution in run_agent."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from run_agent import _apply_task_metadata, _resolve_task_endpoints
from src.config import Config


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
    print("run_agent endpoint resolution smoke test passed")


if __name__ == "__main__":
    main()
