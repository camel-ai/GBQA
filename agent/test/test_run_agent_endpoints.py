"""Smoke test for backend-specific endpoint resolution in run_agent."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from run_agent import _resolve_game_endpoints


def main() -> None:
    game_base_url, frontend_url = _resolve_game_endpoints(
        backend_type="game_client",
        backend_settings={},
        game_id="demo",
        game_config={"base_url": "http://example.test/api/agent"},
    )
    assert game_base_url == "http://example.test/api/agent"
    assert frontend_url == ""

    game_base_url, frontend_url = _resolve_game_endpoints(
        backend_type="playwright_mcp",
        backend_settings={},
        game_id="demo",
        game_config={"frontend_url": "http://example.test/app"},
    )
    assert game_base_url == ""
    assert frontend_url == "http://example.test/app"
    print("run_agent endpoint resolution smoke test passed")


if __name__ == "__main__":
    main()
