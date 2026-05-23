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
    CuaSandboxClient,
    CuaComputerUseExecutionBackend,
    CuaComputerUseSettings,
    _run_async,
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


class AwaitableStub:
    def __init__(self, value="awaited") -> None:
        self._value = value

    def __await__(self):
        async def _inner():
            return self._value

        return _inner().__await__()


class FakeSdkMouse:
    def __init__(self, calls) -> None:  # noqa: ANN001
        self.calls = calls

    def click(self, x, y, button="left"):  # noqa: ANN001
        self.calls.append(("mouse.click", x, y, button))
        return AwaitableStub(None)

    def right_click(self, x, y):  # noqa: ANN001
        self.calls.append(("mouse.right_click", x, y))
        return AwaitableStub(None)

    def double_click(self, x, y):  # noqa: ANN001
        self.calls.append(("mouse.double_click", x, y))
        return AwaitableStub(None)

    def scroll(self, x, y, scroll_x=0, scroll_y=3):  # noqa: ANN001
        self.calls.append(("mouse.scroll", x, y, scroll_x, scroll_y))
        return AwaitableStub(None)


class FakeSdkKeyboard:
    def __init__(self, calls) -> None:  # noqa: ANN001
        self.calls = calls

    def type(self, text):  # noqa: ANN001
        self.calls.append(("keyboard.type", text))
        return AwaitableStub(None)

    def keypress(self, keys):  # noqa: ANN001
        self.calls.append(("keyboard.keypress", keys))
        return AwaitableStub(None)


class FakeSdkScreen:
    def __init__(self, calls, screenshot: bytes) -> None:  # noqa: ANN001
        self.calls = calls
        self._screenshot = screenshot

    def size(self):
        self.calls.append(("screen.size",))
        return AwaitableStub((1280, 720))

    def screenshot(self):
        self.calls.append(("screen.screenshot",))
        return AwaitableStub(self._screenshot)


class FakeSdkShell:
    def __init__(self, calls) -> None:  # noqa: ANN001
        self.calls = calls

    def run(self, command, timeout=30):  # noqa: ANN001
        self.calls.append(("shell.run", command, timeout))
        return AwaitableStub(None)


class FakeSdkSandbox:
    def __init__(self, screenshot: bytes) -> None:
        self.calls = []
        self.mouse = FakeSdkMouse(self.calls)
        self.keyboard = FakeSdkKeyboard(self.calls)
        self.screen = FakeSdkScreen(self.calls, screenshot)
        self.shell = FakeSdkShell(self.calls)


def _png_bytes(tmpdir: str) -> bytes:
    path = Path(tmpdir) / "screen.png"
    Image.new("RGB", (4, 4), color="white").save(path)
    return path.read_bytes()


def main() -> None:
    assert _run_async(AwaitableStub()) == "awaited"
    with tempfile.TemporaryDirectory() as tmpdir:
        screenshot = _png_bytes(tmpdir)
        sdk_sandbox = FakeSdkSandbox(screenshot)
        sdk_client = CuaSandboxClient(
            server_url="http://127.0.0.1:8030",
            sandbox_name="gbqa-local-computer",
            startup_timeout=1,
        )
        sdk_client._sandbox = sdk_sandbox
        assert sdk_client.get_screen_size() == {"width": 1280, "height": 720}
        assert sdk_client.screenshot() == screenshot
        sdk_client.click(10, 20)
        sdk_client.click(11, 21, button="right")
        sdk_client.click(12, 22, double=True)
        sdk_client.type_text("look")
        sdk_client.press_key("enter")
        sdk_client.hotkey(["ctrl", "l"])
        sdk_client.scroll(15, 25, -3)
        sdk_client.open_url("http://127.0.0.1:5000/")
        assert ("screen.size",) in sdk_sandbox.calls
        assert ("screen.screenshot",) in sdk_sandbox.calls
        assert ("mouse.click", 10, 20, "left") in sdk_sandbox.calls
        assert ("mouse.right_click", 11, 21) in sdk_sandbox.calls
        assert ("mouse.double_click", 12, 22) in sdk_sandbox.calls
        assert ("keyboard.type", "look") in sdk_sandbox.calls
        assert ("keyboard.keypress", "enter") in sdk_sandbox.calls
        assert ("keyboard.keypress", ["ctrl", "l"]) in sdk_sandbox.calls
        assert ("mouse.scroll", 15, 25, 0, -3) in sdk_sandbox.calls
        assert any(
            call[0] == "shell.run" and "--new-window" in call[1] and call[2] == 5
            for call in sdk_sandbox.calls
        )
        sdk_client.close()

        client = FakeCuaClient(screenshot)
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
