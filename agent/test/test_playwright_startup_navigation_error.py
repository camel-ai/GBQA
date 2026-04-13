"""Smoke test for Playwright startup failing on navigate tool errors."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.computeruse.mcp_client import McpProtocolError
from src.computeruse.playwright_backend import (
    PlaywrightMcpExecutionBackend,
    PlaywrightMcpSettings,
)


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def start(self) -> None:
        return None

    def list_tools(self):  # noqa: ANN001
        return {"tools": [{"name": "browser_navigate"}]}

    def call_tool(self, tool_name, arguments):  # noqa: ANN001
        if tool_name == "browser_navigate":
            return {"isError": True, "content": [{"text": "navigation failed"}]}
        raise AssertionError(f"Unexpected tool call: {tool_name} {arguments}")

    def close(self) -> None:
        self.closed = True


def main() -> None:
    client = FakeClient()
    backend = PlaywrightMcpExecutionBackend(
        PlaywrightMcpSettings(
            command=["npx"],
            startup_timeout=20,
            frontend_url="http://localhost:5000/",
            snapshot_tool="browser_snapshot",
            screenshot_tool="browser_take_screenshot",
            navigate_tool="browser_navigate",
            click_tool="browser_click",
            type_tool="browser_type",
            press_tool="browser_press_key",
            wait_tool="browser_wait_for",
            screenshot_dir="tmp/playwright_artifacts",
        ),
        client_factory=lambda: client,
    )

    try:
        backend.start_session({})
    except McpProtocolError as exc:
        assert "navigation failed" in str(exc)
        assert client.closed is True
        print("playwright startup navigation error smoke test passed")
        return

    raise AssertionError("start_session should fail when navigation tool returns isError")


if __name__ == "__main__":
    main()
