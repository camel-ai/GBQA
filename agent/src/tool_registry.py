"""Planner-visible tool registry."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Dict, List, Optional

from .game_clients import CodeToolProvider, RuntimeLogProvider
from .log_analyzer import LogAnalyzer
from .types import CapabilityDescriptor, Observation


ToolPayload = Dict[str, Any]
ToolRuntimeContext = Dict[str, Any]
ToolHandler = Callable[[ToolPayload, ToolRuntimeContext], "ToolInvocationResult"]
ToolActionParser = Callable[[str], ToolPayload]


@dataclass
class ToolInvocationResult:
    """Normalized result returned by a registry tool invocation."""

    observation: Observation
    refreshed_capability: Optional[CapabilityDescriptor] = None


@dataclass
class Tool:
    """Describes a planner-visible callable tool."""

    name: str
    description: str
    action_format: str
    handler: ToolHandler
    action_parser: ToolActionParser

    def invoke(
        self,
        payload: ToolPayload,
        runtime_context: ToolRuntimeContext,
    ) -> ToolInvocationResult:
        return self.handler(payload, runtime_context)

    def parse_action(self, action_text: str) -> ToolPayload:
        return self.action_parser(action_text)


class ToolRegistry:
    """Registers planner-visible tools and dispatches invocations."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def parse_action(self, name: str, action_text: str) -> ToolPayload:
        return self._get(name).parse_action(action_text)

    def invoke(
        self,
        name: str,
        payload: ToolPayload,
        runtime_context: ToolRuntimeContext,
    ) -> ToolInvocationResult:
        return self._get(name).invoke(payload, runtime_context)

    def render_prompt_section(self) -> str:
        lines = ["## Available Tools:"]
        for tool in self.list_tools():
            lines.append(
                f"- {tool.name}: {tool.description} Format: `{tool.action_format}`."
            )
        return "\n".join(lines)

    def _get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]


def register_game_action_tool(
    registry: ToolRegistry,
    handler: ToolHandler,
) -> None:
    """Register the primary gameplay-action tool."""
    registry.register(
        Tool(
            name="game_action",
            description=(
                "Execute one semantic gameplay action through the operator and active execution backend"
            ),
            action_format="semantic action string",
            handler=handler,
            action_parser=lambda action_text: {"action": _require_action(action_text)},
        )
    )


def register_code_tools(
    registry: ToolRegistry,
    provider: CodeToolProvider,
) -> None:
    """Register white-box source-code tools."""
    registry.register(
        Tool(
            name="code_list_files",
            description="List available source code files for the current game",
            action_format="any non-empty text (ignored)",
            handler=lambda payload, runtime: _invoke_code_tool(
                "code_list_files",
                payload,
                runtime,
                provider.list_code_files(),
            ),
            action_parser=lambda _action_text: {},
        )
    )
    registry.register(
        Tool(
            name="code_read_file",
            description="Read a source file, optionally with a line range",
            action_format="path or path:start-end",
            handler=lambda payload, runtime: _invoke_code_tool(
                "code_read_file",
                payload,
                runtime,
                provider.read_code_file(
                    payload["path"],
                    start_line=int(payload.get("start_line", 0)),
                    end_line=int(payload.get("end_line", 0)),
                ),
            ),
            action_parser=_parse_code_read_action,
        )
    )
    registry.register(
        Tool(
            name="code_search",
            description="Search source code using a regex pattern",
            action_format="pattern",
            handler=lambda payload, runtime: _invoke_code_tool(
                "code_search",
                payload,
                runtime,
                provider.search_code(payload["pattern"]),
            ),
            action_parser=lambda action_text: {"pattern": _require_action(action_text)},
        )
    )
    registry.register(
        Tool(
            name="code_write_file",
            description="Modify a source file using JSON payload or path:old->new patch shorthand",
            action_format="JSON string or path:old_text->new_text",
            handler=lambda payload, runtime: _invoke_code_tool(
                "code_write_file",
                payload,
                runtime,
                provider.write_code_file(
                    payload["path"],
                    content=str(payload.get("content", "")),
                    patch=payload.get("patch"),
                ),
            ),
            action_parser=_parse_code_write_action,
        )
    )
    registry.register(
        Tool(
            name="code_restore_file",
            description="Restore a file previously modified by code_write_file",
            action_format="path",
            handler=lambda payload, runtime: _invoke_code_tool(
                "code_restore_file",
                payload,
                runtime,
                provider.restore_code_file(payload["path"]),
            ),
            action_parser=lambda action_text: {"path": _require_action(action_text)},
        )
    )


def register_runtime_log_tool(
    registry: ToolRegistry,
    provider: RuntimeLogProvider,
) -> None:
    """Register runtime debug-log access."""
    registry.register(
        Tool(
            name="code_read_debug_logs",
            description=(
                "Read or clear runtime debug logs for the current active game session; "
                "the session id is inferred automatically"
            ),
            action_format="read or clear",
            handler=lambda payload, runtime: _invoke_runtime_log_tool(
                payload,
                runtime,
                provider,
            ),
            action_parser=_parse_debug_log_action,
        )
    )


def register_log_analysis_tool(
    registry: ToolRegistry,
    provider: RuntimeLogProvider,
    analyzer: LogAnalyzer,
) -> None:
    """Register session-log analysis using the active game_client session."""
    registry.register(
        Tool(
            name="log_analyze",
            description=(
                "Analyze the current game session log for anomalies and optionally "
                "show filtered commands"
            ),
            action_format=(
                "analyze, failures, or JSON object with start_turn/end_turn/"
                "failures_only/limit/include_debug_output"
            ),
            handler=lambda payload, runtime: _invoke_log_analysis_tool(
                payload,
                runtime,
                provider,
                analyzer,
            ),
            action_parser=_parse_log_analysis_action,
        )
    )


def _require_action(action_text: str) -> str:
    text = str(action_text).strip()
    if not text:
        raise ValueError("Planner action must not be empty")
    return text


def _parse_code_read_action(action_text: str) -> ToolPayload:
    text = _require_action(action_text)
    path, separator, line_spec = text.rpartition(":")
    if not separator or "-" not in line_spec:
        return {"path": text}
    start_text, dash, end_text = line_spec.partition("-")
    if not dash or not start_text.isdigit() or not end_text.isdigit():
        return {"path": text}
    return {
        "path": path.strip(),
        "start_line": int(start_text),
        "end_line": int(end_text),
    }


def _parse_code_write_action(action_text: str) -> ToolPayload:
    text = _require_action(action_text)
    if text.startswith("{"):
        payload = json.loads(text)
        if not isinstance(payload, dict) or not str(payload.get("path", "")).strip():
            raise ValueError("code_write_file JSON must include a non-empty 'path'")
        return payload
    path, separator, patch_spec = text.partition(":")
    if not separator or "->" not in patch_spec:
        raise ValueError(
            "code_write_file action must be JSON or use path:old_text->new_text"
        )
    search_text, arrow, replace_text = patch_spec.partition("->")
    if not arrow:
        raise ValueError(
            "code_write_file patch shorthand must use path:old_text->new_text"
        )
    return {
        "path": path.strip(),
        "patch": {
            "search": search_text,
            "replace": replace_text,
        },
    }


def _parse_debug_log_action(action_text: str) -> ToolPayload:
    text = _require_action(action_text).lower()
    if text not in {"read", "clear"}:
        raise ValueError("code_read_debug_logs action must be 'read' or 'clear'")
    return {"clear": text == "clear"}


def _parse_log_analysis_action(action_text: str) -> ToolPayload:
    text = _require_action(action_text)
    lowered = text.lower()
    if lowered in {"analyze", "summary"}:
        return {"include_debug_output": True}
    if lowered == "failures":
        return {"include_debug_output": True, "failures_only": True}
    if text.startswith("{"):
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("log_analyze JSON action must decode to an object")
        payload.setdefault("include_debug_output", True)
        return payload
    raise ValueError(
        "log_analyze action must be 'analyze', 'failures', or a JSON object"
    )


def _invoke_code_tool(
    tool_name: str,
    payload: ToolPayload,
    runtime_context: ToolRuntimeContext,
    result: Dict[str, Any],
) -> ToolInvocationResult:
    del runtime_context
    return ToolInvocationResult(
        observation=_tool_observation(tool_name, payload, result),
    )


def _invoke_runtime_log_tool(
    payload: ToolPayload,
    runtime_context: ToolRuntimeContext,
    provider: RuntimeLogProvider,
) -> ToolInvocationResult:
    session = runtime_context.get("session")
    if session is None or getattr(session, "backend_type", "") != "game_client":
        raise RuntimeError(
            "code_read_debug_logs is only available when the active backend exposes a stable current game session"
        )
    result = provider.read_debug_logs(
        getattr(session, "session_id", ""),
        clear=bool(payload.get("clear", False)),
    )
    return ToolInvocationResult(
        observation=_tool_observation("code_read_debug_logs", payload, result),
    )


def _invoke_log_analysis_tool(
    payload: ToolPayload,
    runtime_context: ToolRuntimeContext,
    provider: RuntimeLogProvider,
    analyzer: LogAnalyzer,
) -> ToolInvocationResult:
    session = runtime_context.get("session")
    if session is None or getattr(session, "backend_type", "") != "game_client":
        raise RuntimeError(
            "log_analyze is only available when the active backend exposes a stable current game session"
        )

    game_id = getattr(session, "session_id", "")
    session_result = provider.read_session_log(game_id)
    if not bool(session_result.get("success", False)):
        return ToolInvocationResult(
            observation=_tool_observation("log_analyze", payload, session_result),
        )

    session_data = session_result.get("data", {})
    debug_output = ""
    debug_log_error = ""
    if bool(payload.get("include_debug_output", True)):
        debug_result = provider.read_debug_logs(game_id, clear=False)
        if bool(debug_result.get("success", False)):
            debug_output = str(debug_result.get("logs", ""))
        else:
            debug_log_error = str(debug_result.get("message", "")).strip()

    result: Dict[str, Any] = {
        "success": True,
        "game_id": game_id,
        "analysis": analyzer.analyze_session(session_data, debug_output),
    }
    if _has_log_analysis_filters(payload):
        result["filtered_commands"] = analyzer.filter_commands(
            session_data,
            start_turn=int(payload.get("start_turn", 0)),
            end_turn=int(payload.get("end_turn", 0)),
            failures_only=bool(payload.get("failures_only", False)),
            limit=int(payload.get("limit", 50)),
        )
    if debug_log_error:
        result["debug_log_error"] = debug_log_error

    return ToolInvocationResult(
        observation=_tool_observation("log_analyze", payload, result),
    )


def _has_log_analysis_filters(payload: ToolPayload) -> bool:
    if int(payload.get("start_turn", 0)) > 0:
        return True
    if int(payload.get("end_turn", 0)) > 0:
        return True
    if bool(payload.get("failures_only", False)):
        return True
    return "limit" in payload


def _tool_observation(
    tool_name: str,
    payload: ToolPayload,
    result: Dict[str, Any],
) -> Observation:
    success = bool(result.get("success", False))
    summary = _tool_summary(tool_name, result)
    message = str(result.get("message", "")).strip() or summary
    execution: Dict[str, Any] = {
        "attempts": [],
        "diagnostics": {
            "tool": tool_name,
            "tool_payload": payload,
        },
    }
    if not success:
        execution["diagnostics"]["error"] = message
        execution["diagnostics"]["error_kind"] = "tool_execution_error"
        execution["suspected_origin"] = "execution"
    return Observation(
        success=success,
        message=message,
        state={},
        raw=result,
        summary=summary,
        env_state={},
        artifacts={},
        execution=execution,
    )


def _tool_summary(tool_name: str, result: Dict[str, Any]) -> str:
    if tool_name == "code_list_files":
        files = result.get("files", [])
        if isinstance(files, list) and files:
            file_paths = [
                str(item.get("path", "")).strip()
                for item in files
                if isinstance(item, dict) and str(item.get("path", "")).strip()
            ]
            return "Code tool result (file list):\n" + "\n".join(file_paths)
    if tool_name == "code_read_file":
        path = str(result.get("path", "")).strip()
        content = str(result.get("content", "")).strip()
        heading = f"Code tool result (read file: {path}):" if path else "Code tool result:"
        return f"{heading}\n{content}".strip()
    if tool_name == "code_search":
        matches = result.get("matches", [])
        if isinstance(matches, list) and matches:
            lines = []
            for item in matches:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path", "")).strip()
                line = item.get("line")
                text = str(item.get("text", "")).strip()
                location = f"{path}:{line}" if path and line else path or str(line or "")
                lines.append(f"{location} {text}".strip())
            if lines:
                return "Code tool result (search matches):\n" + "\n".join(lines)
        return "Code tool result: no search matches found."
    if tool_name == "code_read_debug_logs":
        logs = str(result.get("logs", "")).strip()
        if logs:
            return f"Runtime log result:\n{logs}"
    if tool_name == "log_analyze":
        parts: List[str] = []
        analysis = result.get("analysis", {})
        if isinstance(analysis, dict):
            summary = str(analysis.get("summary", "")).strip()
            if summary:
                parts.append(f"Log analysis result: {summary}")
            for anomaly in analysis.get("anomalies", [])[:5]:
                if not isinstance(anomaly, dict):
                    continue
                severity = str(anomaly.get("severity", "")).strip() or "unknown"
                anomaly_type = str(anomaly.get("type", "")).strip() or "unknown"
                description = str(anomaly.get("description", "")).strip()
                parts.append(f"- [{severity}] {anomaly_type}: {description}".rstrip())
            debug_findings = analysis.get("debug_findings", {})
            if isinstance(debug_findings, dict):
                error_count = int(debug_findings.get("error_count", 0))
                warning_count = int(debug_findings.get("warning_count", 0))
                if error_count or warning_count:
                    parts.append(
                        f"Debug findings: {error_count} errors, {warning_count} warnings"
                    )
        filtered = result.get("filtered_commands", {})
        if isinstance(filtered, dict):
            commands = filtered.get("commands", [])
            if isinstance(commands, list):
                parts.append(
                    "Filtered commands "
                    f"({filtered.get('returned_commands', len(commands))} of "
                    f"{filtered.get('filtered_total', len(commands))}):"
                )
                for command in commands[:10]:
                    if not isinstance(command, dict):
                        continue
                    response = command.get("response", {})
                    success = bool(response.get("success", False))
                    status = "OK" if success else "FAIL"
                    parts.append(
                        f"  T{command.get('turn', '?')}: [{status}] "
                        f"{str(command.get('command', '')).strip()}"
                    )
        debug_log_error = str(result.get("debug_log_error", "")).strip()
        if debug_log_error:
            parts.append(f"Debug log read failed: {debug_log_error}")
        if parts:
            return "\n".join(parts)
    path = str(result.get("path", "")).strip()
    message = str(result.get("message", "")).strip()
    if path and message:
        return f"Code tool result ({path}): {message}"
    if message:
        return f"Code tool result: {message}"
    return f"Code tool result: {json.dumps(result, ensure_ascii=False)}"
