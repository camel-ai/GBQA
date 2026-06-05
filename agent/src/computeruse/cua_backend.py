"""Cua computer-use execution backend."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from pathlib import Path
import re
import time
from typing import Any, Callable, Dict, List, Optional, Protocol
from uuid import uuid4

from ..config import Config
from ..types import (
    BackendExecutionResult,
    CapabilityDescriptor,
    ExecutionAttempt,
    ExecutionCall,
    ExecutionRequest,
    Observation,
    SessionHandle,
)


class CuaBackendError(RuntimeError):
    """Raised when Cua computer-use execution fails."""


class CuaClient(Protocol):
    """Synchronous facade used by the Cua backend."""

    def start(self) -> None: ...

    def close(self) -> None: ...

    def open_url(self, url: str) -> None: ...

    def get_screen_size(self) -> Dict[str, int]: ...

    def screenshot(self) -> bytes: ...

    def click(self, x: int, y: int, *, button: str = "left", double: bool = False) -> None: ...

    def type_text(self, text: str) -> None: ...

    def press_key(self, key: str) -> None: ...

    def hotkey(self, keys: List[str]) -> None: ...

    def scroll(self, x: int, y: int, clicks: int) -> None: ...

    def wait(self, duration_ms: int) -> None: ...

    def read_browser_logs(self) -> str: ...


@dataclass(frozen=True)
class CuaComputerUseSettings:
    """Resolved Cua computer-use settings."""

    server_url: str
    frontend_url: str
    screenshot_dir: str
    display_width: int
    display_height: int
    sandbox_name: str
    startup_timeout: int


class CuaComputerUseExecutionBackend:
    """ExecutionBackend using a local Cua computer-server."""

    backend_type = "computer_use"

    def __init__(
        self,
        settings: CuaComputerUseSettings,
        *,
        client_factory: Optional[Callable[[], CuaClient]] = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory or (
            lambda: CuaSandboxClient(
                server_url=settings.server_url,
                sandbox_name=settings.sandbox_name,
                startup_timeout=settings.startup_timeout,
            )
        )

    @classmethod
    def from_config(
        cls,
        *,
        config: Config,
        task_id: str,
        task_config: Dict[str, Any],
        backend_settings: Dict[str, Any],
    ) -> "CuaComputerUseExecutionBackend":
        del task_id
        frontend_url = str(backend_settings.get("frontend_url", "")).strip()
        if not frontend_url:
            port = task_config.get("port")
            frontend_url = task_config.get("frontend_url") or f"http://localhost:{port}"
        display = backend_settings.get("display", {})
        if not isinstance(display, dict):
            display = {}
        settings = CuaComputerUseSettings(
            server_url=str(
                backend_settings.get("server_url") or "http://127.0.0.1:8030"
            ).strip(),
            frontend_url=frontend_url,
            screenshot_dir=config.resolve_path(
                str(backend_settings.get("screenshot_dir", "tmp/cua_artifacts"))
            ),
            display_width=int(display.get("width", 1280)),
            display_height=int(display.get("height", 720)),
            sandbox_name=str(
                backend_settings.get("sandbox_name") or "gbqa-local-computer"
            ),
            startup_timeout=int(backend_settings.get("startup_timeout", 30)),
        )
        return cls(settings=settings)

    def start_session(self, run_context: Dict[str, Any]) -> SessionHandle:
        del run_context
        client = self._client_factory()
        try:
            client.start()
            navigation_result = {
                "kind": "navigate",
                "url": self._settings.frontend_url,
                "success": True,
            }
            try:
                client.open_url(self._settings.frontend_url)
            except Exception as exc:  # noqa: BLE001
                navigation_result = {
                    "kind": "navigate",
                    "url": self._settings.frontend_url,
                    "success": False,
                    "error": str(exc),
                }
            initial_observation = self._screen_observation(
                client,
                label="initial screen",
                per_call_results=[navigation_result],
            )
            return SessionHandle(
                session_id=str(uuid4()),
                backend_type=self.backend_type,
                raw={"client": client},
                metadata={
                    "frontend_url": self._settings.frontend_url,
                    "server_url": self._settings.server_url,
                },
                initial_observation=initial_observation,
            )
        except Exception:
            client.close()
            raise

    def describe_capabilities(
        self,
        session: SessionHandle,
        refresh: bool = False,
    ) -> CapabilityDescriptor:
        del refresh
        client = self._client(session)
        screen_size = self._safe_screen_size(client)
        planner_summary = (
            "You are operating a desktop browser through screenshot-based computer use. "
            "You can click visible coordinates, type text, press keys and hotkeys, scroll, "
            "wait, and capture screenshots. Use the attached screenshots as the source of truth."
        )
        return CapabilityDescriptor(
            planner_summary=planner_summary,
            operator_context={
                "translation_mode": "llm_first",
                "coordinate_system": "screen_pixels_top_left_origin",
                "screen_size": screen_size,
                "screenshot_based_control": True,
                "requires_arguments_for_kinds": {
                    "click": ["x", "y"],
                    "scroll": ["x", "y"],
                },
                "supported_call_kinds": [
                    "click",
                    "type",
                    "press",
                    "hotkey",
                    "scroll",
                    "wait",
                    "screenshot",
                ],
                "frontend_url": self._settings.frontend_url,
            },
            raw={"screen_size": screen_size, "server_url": self._settings.server_url},
        )

    def execute(
        self,
        session: SessionHandle,
        request: ExecutionRequest,
    ) -> BackendExecutionResult:
        client = self._client(session)
        per_call_results: List[Dict[str, Any]] = []
        attempt = ExecutionAttempt(
            attempt=1,
            translated_calls=request.calls,
            final_status="failed",
        )
        try:
            for call in request.calls:
                result = self._execute_call(client, call)
                per_call_results.append(result)
            observation = self._screen_observation(
                client,
                label="current screen",
                per_call_results=per_call_results,
            )
            attempt.per_call_results = per_call_results
            attempt.success = True
            attempt.final_status = "completed"
            observation.execution = {
                "attempts": [self._attempt_to_dict(attempt)],
                "diagnostics": {
                    "backend_type": self.backend_type,
                    "per_call_results": per_call_results,
                },
            }
            return BackendExecutionResult(
                observation=observation,
                attempts=[attempt],
                diagnostics={
                    "backend_type": self.backend_type,
                    "per_call_results": per_call_results,
                },
            )
        except CuaBackendError as exc:
            return self._execution_failure_result(
                attempt=attempt,
                per_call_results=per_call_results,
                error_text=str(exc),
                error_kind="invalid_computer_use_call",
            )
        except Exception as exc:  # noqa: BLE001
            return self._execution_failure_result(
                attempt=attempt,
                per_call_results=per_call_results,
                error_text=str(exc),
                error_kind="backend_exception",
                exception_type=type(exc).__name__,
            )

    def close_session(self, session: SessionHandle) -> None:
        client = session.raw.get("client")
        if client is not None and hasattr(client, "close"):
            client.close()

    def _execute_call(self, client: CuaClient, call: ExecutionCall) -> Dict[str, Any]:
        args = dict(call.arguments or {})
        if call.kind == "click":
            x, y = self._coordinates(args)
            button = str(args.get("button") or "left")
            double = bool(args.get("double", False))
            client.click(x, y, button=button, double=double)
            return {"kind": call.kind, "arguments": args, "success": True}
        if call.kind == "type":
            client.type_text(call.text)
            return {"kind": call.kind, "text": call.text, "success": True}
        if call.kind == "press":
            key = call.text or call.target or str(args.get("key") or "")
            if not key.strip():
                raise CuaBackendError("press call requires text, target, or arguments.key")
            client.press_key(key)
            return {"kind": call.kind, "key": key, "success": True}
        if call.kind == "hotkey":
            keys = args.get("keys")
            if isinstance(keys, str):
                key_list = [part.strip() for part in re.split(r"[+,]", keys) if part.strip()]
            elif isinstance(keys, list):
                key_list = [str(item).strip() for item in keys if str(item).strip()]
            else:
                key_list = [part.strip() for part in re.split(r"[+,]", call.text) if part.strip()]
            if not key_list:
                raise CuaBackendError("hotkey call requires arguments.keys or text")
            client.hotkey(key_list)
            return {"kind": call.kind, "keys": key_list, "success": True}
        if call.kind == "scroll":
            x, y = self._coordinates(args)
            clicks = int(args.get("clicks", args.get("amount", -3)))
            client.scroll(x, y, clicks)
            return {"kind": call.kind, "arguments": {**args, "clicks": clicks}, "success": True}
        if call.kind == "wait":
            duration_ms = int(call.duration_ms or args.get("duration_ms") or 1000)
            client.wait(max(duration_ms, 0))
            return {"kind": call.kind, "duration_ms": duration_ms, "success": True}
        if call.kind == "screenshot":
            return {"kind": call.kind, "success": True}
        raise CuaBackendError(f"Unsupported call kind: {call.kind}")

    def _screen_observation(
        self,
        client: CuaClient,
        *,
        label: str,
        per_call_results: Optional[List[Dict[str, Any]]] = None,
    ) -> Observation:
        screen_size = self._safe_screen_size(client)
        screenshot_path = self._save_screenshot(client.screenshot(), label=label)
        
        # Capture browser logs from the sandbox
        browser_logs = ""
        try:
            browser_logs = client.read_browser_logs()
        except Exception:  # noqa: BLE001
            pass

        summary = (
            "Computer-use screenshot captured. "
            f"Screen size: {screen_size.get('width')}x{screen_size.get('height')}. "
            f"Screenshot artifact: {screenshot_path}."
        )
        
        # Append logs to message so LogAnalyzer can find error patterns
        full_message = summary
        if browser_logs:
            full_message += f"\n\n[Browser Logs]:\n{browser_logs}"

        return Observation(
            success=True,
            message=full_message,
            state={},
            summary=summary,
            env_state={
                "screen_size": screen_size,
                "status_bar": {},
                "input_enabled": True,
                "actionable_elements": [],
            },
            artifacts={
                "screenshots": [
                    {
                        "path": screenshot_path,
                        "mime_type": "image/png",
                        "label": label,
                    }
                ]
            },
            execution={
                "attempts": [],
                "diagnostics": {
                    "backend_type": self.backend_type,
                    "per_call_results": per_call_results or [],
                    "screen_size": screen_size,
                },
            },
        )

    def _save_screenshot(self, payload: bytes, *, label: str) -> str:
        if not payload:
            raise CuaBackendError("Cua screenshot returned empty bytes")
        output_dir = Path(self._settings.screenshot_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", label.strip()).strip("-") or "screen"
        path = output_dir / f"{stem}-{uuid4().hex[:8]}.png"
        path.write_bytes(payload)
        return str(path.resolve())

    def _safe_screen_size(self, client: CuaClient) -> Dict[str, int]:
        try:
            size = client.get_screen_size()
        except Exception:  # noqa: BLE001
            size = {}
        width = int(size.get("width") or self._settings.display_width)
        height = int(size.get("height") or self._settings.display_height)
        return {"width": width, "height": height}

    @staticmethod
    def _coordinates(arguments: Dict[str, Any]) -> tuple[int, int]:
        missing = [key for key in ("x", "y") if key not in arguments]
        if missing:
            raise CuaBackendError(
                "computer-use coordinate call requires arguments: " + ", ".join(missing)
            )
        return int(arguments["x"]), int(arguments["y"])

    @staticmethod
    def _client(session: SessionHandle) -> CuaClient:
        client = session.raw.get("client")
        if client is None:
            raise CuaBackendError("Missing Cua client in session")
        return client

    @staticmethod
    def _attempt_to_dict(attempt: ExecutionAttempt) -> Dict[str, Any]:
        payload = {
            "attempt": attempt.attempt,
            "translated_calls": [
                {
                    "kind": call.kind,
                    "ref": call.ref,
                    "target": call.target,
                    "text": call.text,
                    "url": call.url,
                    "duration_ms": call.duration_ms,
                    "arguments": call.arguments,
                }
                for call in attempt.translated_calls
            ],
            "per_call_results": attempt.per_call_results,
            "retry_reason": attempt.retry_reason,
            "success": attempt.success,
            "final_status": attempt.final_status,
            "error": attempt.error,
        }
        if attempt.suspected_origin:
            payload["suspected_origin"] = attempt.suspected_origin
        return payload

    def _execution_failure_result(
        self,
        *,
        attempt: ExecutionAttempt,
        per_call_results: List[Dict[str, Any]],
        error_text: str,
        error_kind: str,
        exception_type: str = "",
    ) -> BackendExecutionResult:
        attempt.per_call_results = per_call_results
        attempt.error = error_text
        attempt.suspected_origin = "execution"
        diagnostics: Dict[str, Any] = {
            "backend_type": self.backend_type,
            "error": error_text,
            "error_kind": error_kind,
            "per_call_results": per_call_results,
        }
        if exception_type:
            diagnostics["exception_type"] = exception_type
        observation = Observation(
            success=False,
            message=error_text,
            state={},
            summary=f"Execution failure in Cua computer-use backend: {error_text}",
            env_state={},
            artifacts={},
            execution={
                "attempts": [self._attempt_to_dict(attempt)],
                "diagnostics": diagnostics,
                "suspected_origin": "execution",
            },
        )
        return BackendExecutionResult(
            observation=observation,
            attempts=[attempt],
            diagnostics=diagnostics,
        )


class CuaSandboxClient:
    """Synchronous wrapper around the Cua sandbox SDK."""

    def __init__(
        self,
        *,
        server_url: str,
        sandbox_name: str,
        startup_timeout: int,
    ) -> None:
        self._server_url = server_url
        self._sandbox_name = sandbox_name
        self._startup_timeout = startup_timeout
        self._sandbox: Any = None
        self._loop: asyncio.AbstractEventLoop | None = asyncio.new_event_loop()

    def start(self) -> None:
        try:
            from cua import Sandbox  # type: ignore
        except ImportError as exc:
            raise CuaBackendError(
                "cua is required for computer_use backend"
            ) from exc
        deadline = time.time() + max(self._startup_timeout, 1)
        last_error = ""
        while time.time() < deadline:
            try:
                self._sandbox = self._run_async(
                    Sandbox.connect(self._sandbox_name, http_url=self._server_url)
                )
                self.screenshot()
                return
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                time.sleep(1)
        raise CuaBackendError(
            f"Unable to connect to Cua computer-server at {self._server_url}: {last_error}"
        )

    def close(self) -> None:
        sandbox = self._sandbox
        self._sandbox = None
        if sandbox is None:
            self._close_loop()
            return
        disconnect = getattr(sandbox, "disconnect", None)
        if callable(disconnect):
            self._run_async(disconnect())
        self._close_loop()

    def open_url(self, url: str) -> None:
        command = (
            "browser=$(command -v firefox || command -v chromium || "
            "command -v chromium-browser || command -v google-chrome || true); "
            "if [ -z \"$browser\" ]; then exit 127; fi; "
            "setsid -f \"$browser\" --new-window "
            f"{_shell_quote(url)} >/tmp/gbqa-browser.log 2>&1 < /dev/null"
        )
        self._run_command(command, timeout_sec=5)
        time.sleep(2)

    def get_screen_size(self) -> Dict[str, int]:
        sandbox = self._require_sandbox()
        screen = getattr(sandbox, "screen", None)
        if screen is not None and hasattr(screen, "size"):
            width, height = self._run_async(screen.size())
            return {"width": int(width), "height": int(height)}
        if hasattr(sandbox, "get_dimensions"):
            width, height = self._run_async(sandbox.get_dimensions())
            return {"width": int(width), "height": int(height)}
        interface = getattr(sandbox, "interface", None)
        if interface is not None and hasattr(interface, "get_screen_size"):
            size = self._run_async(interface.get_screen_size())
            return {"width": int(size["width"]), "height": int(size["height"])}
        if screen is not None and hasattr(screen, "get_size"):
            size = self._run_async(screen.get_size())
            return {"width": int(size["width"]), "height": int(size["height"])}
        raise CuaBackendError("Cua sandbox does not expose screen dimensions")

    def screenshot(self) -> bytes:
        sandbox = self._require_sandbox()
        screen = getattr(sandbox, "screen", None)
        if screen is not None and hasattr(screen, "screenshot"):
            return bytes(self._run_async(screen.screenshot()))
        if hasattr(sandbox, "screenshot"):
            return bytes(self._run_async(sandbox.screenshot()))
        interface = getattr(sandbox, "interface", None)
        if interface is not None and hasattr(interface, "screenshot"):
            return bytes(self._run_async(interface.screenshot()))
        raise CuaBackendError("Cua sandbox does not expose screenshot")

    def click(self, x: int, y: int, *, button: str = "left", double: bool = False) -> None:
        sandbox = self._require_sandbox()
        mouse = getattr(sandbox, "mouse", None)
        if double:
            self._call_first(
                [
                    (getattr(mouse, "double_click", None), (x, y), {}),
                    (getattr(getattr(sandbox, "interface", None), "double_click", None), (x, y), {}),
                ]
            )
            return
        normalized_button = button.lower().strip() or "left"
        if normalized_button == "right":
            official_mouse_calls = [
                (getattr(mouse, "right_click", None), (x, y), {}),
                (getattr(mouse, "click", None), (x, y), {"button": "right"}),
            ]
        else:
            official_mouse_calls = [
                (
                    getattr(mouse, "click", None),
                    (x, y),
                    {"button": normalized_button},
                )
            ]
        legacy_method_name = {
            "left": "left_click",
            "right": "right_click",
            "middle": "middle_click",
        }.get(normalized_button, "left_click")
        self._call_first(
            [
                *official_mouse_calls,
                (getattr(getattr(sandbox, "interface", None), legacy_method_name, None), (x, y), {}),
                (getattr(getattr(sandbox, "interface", None), "click", None), (x, y), {"button": normalized_button}),
            ]
        )

    def type_text(self, text: str) -> None:
        sandbox = self._require_sandbox()
        keyboard = getattr(sandbox, "keyboard", None)
        self._call_first(
            [
                (getattr(keyboard, "type", None), (text,), {}),
                (getattr(keyboard, "type_text", None), (text,), {}),
                (getattr(getattr(sandbox, "interface", None), "type_text", None), (text,), {}),
            ]
        )

    def press_key(self, key: str) -> None:
        sandbox = self._require_sandbox()
        keyboard = getattr(sandbox, "keyboard", None)
        self._call_first(
            [
                (getattr(keyboard, "keypress", None), (key,), {}),
                (getattr(keyboard, "press", None), (key,), {}),
                (getattr(keyboard, "press_key", None), (key,), {}),
                (getattr(getattr(sandbox, "interface", None), "press_key", None), (key,), {}),
                (getattr(getattr(sandbox, "interface", None), "key", None), (key,), {}),
            ]
        )

    def hotkey(self, keys: List[str]) -> None:
        sandbox = self._require_sandbox()
        keyboard = getattr(sandbox, "keyboard", None)
        self._call_first(
            [
                (getattr(keyboard, "keypress", None), (keys,), {}),
                (getattr(keyboard, "hotkey", None), (keys,), {}),
                (getattr(getattr(sandbox, "interface", None), "hotkey", None), tuple(keys), {}),
            ]
        )

    def scroll(self, x: int, y: int, clicks: int) -> None:
        sandbox = self._require_sandbox()
        mouse = getattr(sandbox, "mouse", None)
        self._call_first(
            [
                (
                    getattr(mouse, "scroll", None),
                    (x, y),
                    {"scroll_x": 0, "scroll_y": clicks},
                ),
                (getattr(mouse, "scroll", None), (x, y, 0, clicks), {}),
                (getattr(getattr(sandbox, "interface", None), "scroll", None), (x, y, clicks), {}),
            ]
        )

    def wait(self, duration_ms: int) -> None:
        time.sleep(max(duration_ms, 0) / 1000.0)

    def execute_shell(self, command: str) -> str:
        """Public interface to run a shell command in the sandbox."""
        try:
            sandbox = self._require_sandbox()
            shell = getattr(sandbox, "shell", None)
            if shell is not None and hasattr(shell, "run"):
                result = self._run_async(shell.run(command))
                return str(getattr(result, "stdout", result))
            return ""
        except Exception:  # noqa: BLE001
            return ""

    def read_browser_logs(self) -> str:
        """Read the last few lines of browser logs from the sandbox."""
        return self.execute_shell("tail -n 50 /tmp/gbqa-browser.log")

    def _run_command(self, command: str, *, timeout_sec: int = 30) -> None:
        sandbox = self._require_sandbox()
        shell = getattr(sandbox, "shell", None)
        if shell is not None and hasattr(shell, "run"):
            self._run_async(shell.run(command, timeout=timeout_sec))
            return
        interface = getattr(sandbox, "interface", None)
        if interface is not None and hasattr(interface, "run_command"):
            self._run_async(interface.run_command(command))
            return
        raise CuaBackendError("Cua sandbox does not expose shell command execution")

    def _require_sandbox(self) -> Any:
        if self._sandbox is None:
            raise CuaBackendError("Cua sandbox is not connected")
        return self._sandbox

    def _call_first(self, candidates: List[tuple[Any, tuple[Any, ...], Dict[str, Any]]]) -> None:
        errors = []
        for method, args, kwargs in candidates:
            if not callable(method):
                continue
            try:
                self._run_async(method(*args, **kwargs))
                return
            except TypeError as exc:
                errors.append(str(exc))
                continue
        raise CuaBackendError(
            "Cua sandbox does not expose the requested operation"
            + (": " + "; ".join(errors[:2]) if errors else "")
        )

    def _run_async(self, value: Any) -> Any:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return _run_async(value, loop=self._loop)

    def _close_loop(self) -> None:
        loop = self._loop
        self._loop = None
        if loop is not None and not loop.is_closed():
            loop.close()


def _run_async(value: Any, loop: asyncio.AbstractEventLoop | None = None) -> Any:
    if inspect.isawaitable(value):
        if loop is not None:
            return loop.run_until_complete(_await_value(value))
        return asyncio.run(_await_value(value))
    return value


async def _await_value(value: Any) -> Any:
    return await value


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
