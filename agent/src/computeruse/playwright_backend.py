"""Playwright MCP execution backend."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional
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
from .mcp_client import McpProtocolError, StdioMcpClient, default_mcp_cwd


@dataclass(frozen=True)
class PlaywrightMcpSettings:
    """Resolved Playwright MCP settings."""

    command: List[str]
    startup_timeout: int
    frontend_url: str
    snapshot_tool: str
    screenshot_tool: str
    navigate_tool: str
    click_tool: str
    type_tool: str
    press_tool: str
    wait_tool: str
    screenshot_dir: str


class PlaywrightMcpExecutionBackend:
    """ExecutionBackend using an MCP Playwright server over stdio."""

    backend_type = "playwright_mcp"

    def __init__(
        self,
        settings: PlaywrightMcpSettings,
        *,
        client_factory: Optional[Callable[[], StdioMcpClient]] = None,
    ) -> None:
        if not settings.command:
            raise ValueError("Playwright MCP command must not be empty")
        self._settings = settings
        self._client_factory = client_factory or (
            lambda: StdioMcpClient(
                settings.command,
                cwd=default_mcp_cwd("."),
                startup_timeout=settings.startup_timeout,
            )
        )

    @classmethod
    def from_config(
        cls,
        *,
        config: Config,
        game_id: str,
        game_config: Dict[str, Any],
        backend_settings: Dict[str, Any],
    ) -> "PlaywrightMcpExecutionBackend":
        del game_id
        frontend_url = str(backend_settings.get("frontend_url", "")).strip()
        if not frontend_url:
            port = game_config.get("port")
            frontend_url = game_config.get("frontend_url") or f"http://localhost:{port}"
        settings = PlaywrightMcpSettings(
            command=[str(item) for item in backend_settings.get("command", [])],
            startup_timeout=int(backend_settings.get("startup_timeout", 20)),
            frontend_url=frontend_url,
            snapshot_tool=str(backend_settings.get("snapshot_tool", "browser_snapshot")),
            screenshot_tool=str(
                backend_settings.get("screenshot_tool", "browser_take_screenshot")
            ),
            navigate_tool=str(backend_settings.get("navigate_tool", "browser_navigate")),
            click_tool=str(backend_settings.get("click_tool", "browser_click")),
            type_tool=str(backend_settings.get("type_tool", "browser_type")),
            press_tool=str(backend_settings.get("press_tool", "browser_press_key")),
            wait_tool=str(backend_settings.get("wait_tool", "browser_wait_for")),
            screenshot_dir=config.resolve_path(
                str(backend_settings.get("screenshot_dir", "tmp/playwright_artifacts"))
            ),
        )
        return cls(settings=settings)

    def start_session(self, run_context: Dict[str, Any]) -> SessionHandle:
        del run_context
        client = self._client_factory()
        try:
            client.start()
            tools = client.list_tools()
            self._call_tool(
                client,
                self._settings.navigate_tool,
                {"url": self._settings.frontend_url},
            )
            initial_observation = self._snapshot_observation(client)
            return SessionHandle(
                session_id=str(uuid4()),
                backend_type=self.backend_type,
                raw={"client": client, "tools": tools},
                metadata={"frontend_url": self._settings.frontend_url},
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
        client = self._client(session)
        tools = session.raw.get("tools")
        if refresh or not tools:
            tools = client.list_tools()
            session.raw["tools"] = tools
        tool_names = self._tool_names(tools)
        planner_summary = (
            "You are operating a browser UI through an operator. "
            "You can request clicks on visible buttons or controls, type text into inputs, "
            "press keys, wait for the page to update, capture screenshots, and read the current page snapshot. "
            "Use describe_capabilities if you need this summary again."
        )
        return CapabilityDescriptor(
            planner_summary=planner_summary,
            operator_context={
                "translation_mode": "llm_first",
                "requires_ref_for_kinds": ["click", "type"],
                "supported_call_kinds": [
                    "navigate",
                    "click",
                    "type",
                    "press",
                    "wait",
                    "screenshot",
                    "snapshot",
                ],
                "available_tools": tool_names,
                "frontend_url": self._settings.frontend_url,
            },
            raw={"tools": tools},
        )

    def execute(
        self,
        session: SessionHandle,
        request: ExecutionRequest,
    ) -> BackendExecutionResult:
        client = self._client(session)
        per_call_results: List[Dict[str, Any]] = []
        screenshot_artifacts: List[Dict[str, Any]] = []
        attempt = ExecutionAttempt(
            attempt=1,
            translated_calls=request.calls,
            final_status="failed",
        )
        try:
            for call in request.calls:
                tool_name, arguments = self._map_call(call)
                tool_result = self._call_tool(client, tool_name, arguments)
                tool_error = self._tool_result_error(tool_result)
                screenshot_path = ""
                if call.kind == "screenshot":
                    screenshot_path = str(arguments.get("filename", "")).strip()
                    if screenshot_path:
                        screenshot_artifacts.append(
                            {
                                "path": screenshot_path,
                                "mime_type": "image/png",
                                "label": call.target or "current page",
                            }
                        )
                per_call_results.append(
                    {
                        "kind": call.kind,
                        "ref": call.ref,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "is_error": bool(tool_result.get("isError", False)),
                        "result_excerpt": self._result_excerpt(tool_result),
                        "artifact_path": screenshot_path,
                    }
                )
                if tool_error:
                    raise McpProtocolError(tool_error)
            observation = self._snapshot_observation(
                client,
                per_call_results=per_call_results,
                screenshots=screenshot_artifacts,
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
        except McpProtocolError as exc:
            return self._execution_failure_result(
                attempt=attempt,
                per_call_results=per_call_results,
                error_text=str(exc),
                error_kind=self._error_kind(str(exc)),
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

    def _snapshot_observation(
        self,
        client: Any,
        *,
        per_call_results: Optional[List[Dict[str, Any]]] = None,
        screenshots: Optional[List[Dict[str, Any]]] = None,
    ) -> Observation:
        snapshot = self._call_tool(client, self._settings.snapshot_tool, {})
        snapshot_error = self._tool_result_error(snapshot)
        if snapshot_error:
            raise McpProtocolError(snapshot_error)
        snapshot_text = self._extract_text(snapshot)
        env_state = self._extract_env_state(snapshot_text)
        artifacts = {"snapshot": snapshot}
        if screenshots:
            artifacts["screenshots"] = screenshots
        return Observation(
            success=True,
            message=snapshot_text,
            state={},
            summary=snapshot_text or "Browser observation captured.",
            env_state=env_state,
            artifacts=artifacts,
            execution={
                "attempts": [],
                "diagnostics": {
                    "backend_type": self.backend_type,
                    "per_call_results": per_call_results or [],
                },
            },
        )

    def _map_call(self, call: ExecutionCall) -> tuple[str, Dict[str, Any]]:
        if call.kind == "navigate":
            return self._settings.navigate_tool, {"url": call.url or call.text}
        if call.kind == "click":
            if call.ref:
                return self._settings.click_tool, {"ref": call.ref, "element": call.target}
            return self._settings.click_tool, {"selector": call.target, "element": call.target}
        if call.kind == "type":
            if call.ref:
                return self._settings.type_tool, {
                    "ref": call.ref,
                    "element": call.target or "command input",
                    "text": call.text,
                }
            return self._settings.type_tool, {
                "selector": call.target or "command input",
                "element": call.target or "command input",
                "text": call.text,
            }
        if call.kind == "press":
            return self._settings.press_tool, {"key": call.text or call.target}
        if call.kind == "wait":
            return self._settings.wait_tool, {
                "time": max(call.duration_ms or 1000, 0) / 1000.0
            }
        if call.kind == "screenshot":
            filename = self._screenshot_filename(call)
            arguments: Dict[str, Any] = {"filename": filename}
            if call.ref:
                arguments["ref"] = call.ref
                arguments["element"] = call.target or "target element"
            return self._settings.screenshot_tool, arguments
        if call.kind == "snapshot":
            return self._settings.snapshot_tool, {}
        raise McpProtocolError(f"Unsupported call kind: {call.kind}")

    def _screenshot_filename(self, call: ExecutionCall) -> str:
        output_dir = Path(self._settings.screenshot_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", (call.target or "page").strip()).strip("-")
        if not stem:
            stem = "page"
        filename = f"{stem}-{uuid4().hex[:8]}.png"
        return str((output_dir / filename).resolve())

    @staticmethod
    def _client(session: SessionHandle) -> Any:
        client = session.raw.get("client")
        if client is None or not hasattr(client, "call_tool"):
            raise McpProtocolError("Missing MCP client in session")
        return client

    @staticmethod
    def _tool_names(payload: Dict[str, Any]) -> List[str]:
        tools = payload.get("tools", []) if isinstance(payload, dict) else []
        names = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if name:
                names.append(name)
        return names

    @staticmethod
    def _call_tool(
        client: Any,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not tool_name:
            raise McpProtocolError("Tool name is empty")
        return client.call_tool(tool_name, arguments)

    @staticmethod
    def _extract_text(payload: Dict[str, Any]) -> str:
        texts: List[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                text = value.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(payload)
        unique_lines = []
        seen = set()
        for line in texts:
            if line in seen:
                continue
            seen.add(line)
            unique_lines.append(line)
        return "\n".join(unique_lines)

    @staticmethod
    def _extract_env_state(visible_text: str) -> Dict[str, Any]:
        lines = [line.strip() for line in visible_text.splitlines() if line.strip()]
        cleaned_lines = [
            PlaywrightMcpExecutionBackend._clean_snapshot_line(line) for line in lines
        ]
        location = PlaywrightMcpExecutionBackend._value_after_label(
            cleaned_lines,
            "Location:",
        )
        inventory = PlaywrightMcpExecutionBackend._value_after_label(
            cleaned_lines,
            "Inventory:",
        )
        turn = PlaywrightMcpExecutionBackend._value_after_label(cleaned_lines, "Turn:")
        light = PlaywrightMcpExecutionBackend._capture(r"(No light|Light on)", visible_text)
        output_lines = [
            line
            for line in cleaned_lines
            if line
            and (
                "Press the button below" in line
                or line.startswith("You")
                or line.startswith("Error:")
            )
        ]
        actionable_elements = PlaywrightMcpExecutionBackend._extract_actionable_elements(
            lines
        )
        controls = [
            item["label"]
            for item in actionable_elements
            if item.get("role") == "button" and item.get("enabled", False)
        ]
        status_bits = [item for item in [location, inventory, turn, light] if item]
        return {
            "visible_text": visible_text,
            "output_text": "\n".join(output_lines).strip(),
            "status_bar": {
                "location": location,
                "inventory": inventory,
                "turn": turn,
                "light": light,
            },
            "status_summary": "; ".join(status_bits),
            "controls_summary": (
                f"Visible controls: {', '.join(controls)}" if controls else ""
            ),
            "input_enabled": any(
                item.get("role") == "textbox" and item.get("enabled", False)
                for item in actionable_elements
            ),
            "actionable_elements": actionable_elements,
        }

    @staticmethod
    def _clean_snapshot_line(line: str) -> str:
        text = line.strip().strip("'")
        paragraph_match = re.match(
            r"-?\s*(?:paragraph|generic|text|heading)\b.*?:\s*(.+)$",
            text,
        )
        if paragraph_match:
            return paragraph_match.group(1).strip().strip('"')
        quoted_match = re.match(r'-?\s*(?:button|textbox)\s+"([^"]+)"', text)
        if quoted_match:
            return quoted_match.group(1).strip()
        return text

    @staticmethod
    def _extract_actionable_elements(lines: List[str]) -> List[Dict[str, Any]]:
        elements: List[Dict[str, Any]] = []
        for line in lines:
            text = line.strip().strip("'")
            match = re.match(r'-?\s*(button|textbox)\s+"([^"]+)"(.*)$', text)
            if not match:
                continue
            role, label, attrs = match.groups()
            ref_match = re.search(r"\[ref=([^\]]+)\]", attrs)
            if not ref_match:
                continue
            elements.append(
                {
                    "role": role,
                    "label": label.strip(),
                    "ref": ref_match.group(1).strip(),
                    "enabled": "[disabled]" not in attrs,
                }
            )
        return elements

    @staticmethod
    def _tool_result_error(payload: Dict[str, Any]) -> str:
        if not isinstance(payload, dict) or not payload.get("isError", False):
            return ""
        text = PlaywrightMcpExecutionBackend._extract_text(payload)
        if text:
            return text
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _capture(pattern: str, text: str) -> str:
        match = re.search(pattern, text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _value_after_label(lines: List[str], label: str) -> str:
        for index, line in enumerate(lines):
            if line != label:
                continue
            if index + 1 < len(lines):
                return lines[index + 1].strip().strip('"')
        return ""

    @staticmethod
    def _error_kind(error_text: str) -> str:
        lowered = error_text.lower()
        if "not found" in lowered:
            return "element_not_found"
        if "timeout" in lowered:
            return "timeout"
        if "tool" in lowered and "not" in lowered:
            return "tool_not_found"
        if "visible" in lowered:
            return "not_visible"
        return "execution_error"

    @staticmethod
    def _result_excerpt(payload: Dict[str, Any]) -> str:
        text = PlaywrightMcpExecutionBackend._extract_text(payload)
        if text:
            return text[:500]
        return json.dumps(payload, ensure_ascii=False)[:500]

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
            summary=f"Execution failure in Playwright MCP: {error_text}",
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
