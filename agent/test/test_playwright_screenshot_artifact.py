"""Smoke test for Playwright screenshot artifacts flowing into observations."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.computeruse.playwright_backend import (
    PlaywrightMcpExecutionBackend,
    PlaywrightMcpSettings,
)
from src.types import ExecutionCall, ExecutionRequest, SessionHandle


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def call_tool(self, tool_name, arguments):  # noqa: ANN001
        self.calls.append((tool_name, dict(arguments)))
        if tool_name == "browser_take_screenshot":
            filename = Path(arguments["filename"])
            filename.parent.mkdir(parents=True, exist_ok=True)
            filename.write_bytes(b"fake-image")
            return {"content": [{"text": f"Saved screenshot to {filename}"}]}
        if tool_name == "browser_snapshot":
            return {
                "content": [
                    {
                        "text": (
                            "### Page\n"
                            "- Page URL: http://localhost:5000/\n"
                            "### Snapshot\n"
                            "```yaml\n"
                            "- button \"Look\" [ref=e1]\n"
                            "```"
                        )
                    }
                ]
            }
        return {"content": [{"text": "ok"}]}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
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
                screenshot_dir=tmpdir,
            ),
            client_factory=FakeClient,
        )
        client = FakeClient()
        session = SessionHandle(
            session_id="session",
            backend_type="playwright_mcp",
            raw={"client": client, "tools": {"tools": []}},
        )

        result = backend.execute(
            session,
            ExecutionRequest(
                planner_action="Capture a screenshot of the current page.",
                calls=[ExecutionCall(kind="screenshot", target="current page")],
            ),
        )

        screenshots = result.observation.artifacts.get("screenshots", [])
        assert len(screenshots) == 1
        assert Path(screenshots[0]["path"]).exists()
        assert result.observation.summary.startswith("### Page")
        print("playwright screenshot artifact smoke test passed")


if __name__ == "__main__":
    main()
