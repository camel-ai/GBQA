"""Smoke tests for the Cua computer-use backend."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

from PIL import Image

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.computeruse.cua_backend import (
    CuaComputerUseExecutionBackend,
    CuaComputerUseSettings,
)
from src.types import ExecutionCall, ExecutionRequest


class FakeCuaClient:
    def __init__(self, screenshot: bytes) -> None:
        self.calls = []
        self._screenshot = screenshot

    def start(self) -> None:
        self.calls.append(("start",))

    def close(self) -> None:
        self.calls.append(("close",))

    def open_url(self, url: str) -> None:
        self.calls.append(("open_url", url))

    def get_screen_size(self):
        return {"width": 1280, "height": 720}

    def screenshot(self) -> bytes:
        self.calls.append(("screenshot",))
        return self._screenshot

    def click(self, x: int, y: int, *, button: str = "left", double: bool = False) -> None:
        self.calls.append(("click", x, y, button, double))

    def type_text(self, text: str) -> None:
        self.calls.append(("type_text", text))

    def press_key(self, key: str) -> None:
        self.calls.append(("press_key", key))

    def hotkey(self, keys):
        self.calls.append(("hotkey", tuple(keys)))

    def scroll(self, x: int, y: int, clicks: int) -> None:
        self.calls.append(("scroll", x, y, clicks))

    def wait(self, duration_ms: int) -> None:
        self.calls.append(("wait", duration_ms))


def _png_bytes(tmpdir: str) -> bytes:
    path = Path(tmpdir) / "screen.png"
    Image.new("RGB", (4, 4), color="white").save(path)
    return path.read_bytes()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        client = FakeCuaClient(_png_bytes(tmpdir))
        backend = CuaComputerUseExecutionBackend(
            CuaComputerUseSettings(
                server_url="http://127.0.0.1:8030",
                frontend_url="http://127.0.0.1:5000/",
                screenshot_dir=str(Path(tmpdir) / "screenshots"),
                display_width=1280,
                display_height=720,
                sandbox_name="gbqa-local-computer",
                startup_timeout=1,
            ),
            client_factory=lambda: client,
        )
        session = backend.start_session({})
        assert session.backend_type == "computer_use"
        assert ("open_url", "http://127.0.0.1:5000/") in client.calls
        capability = backend.describe_capabilities(session)
        assert "click" in capability.operator_context["supported_call_kinds"]
        assert capability.operator_context["requires_arguments_for_kinds"]["click"] == [
            "x",
            "y",
        ]

        result = backend.execute(
            session,
            ExecutionRequest(
                planner_action="click and type",
                calls=[
                    ExecutionCall(kind="click", arguments={"x": 10, "y": 20}),
                    ExecutionCall(kind="type", text="look"),
                ],
            ),
        )
        assert result.observation.success is True
        assert ("click", 10, 20, "left", False) in client.calls
        assert ("type_text", "look") in client.calls
        screenshots = result.observation.artifacts["screenshots"]
        assert Path(screenshots[0]["path"]).exists()

        failure = backend.execute(
            session,
            ExecutionRequest(
                planner_action="bad click",
                calls=[ExecutionCall(kind="click")],
            ),
        )
        assert failure.observation.success is False
        assert "arguments: x, y" in failure.observation.message
        backend.close_session(session)
        print("cua computer-use backend smoke test passed")


if __name__ == "__main__":
    main()
