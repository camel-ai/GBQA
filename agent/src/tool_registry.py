"""Planner-visible tool registry."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Dict, List, Optional

from .codebase_types import UniversalCodebaseAdapter
from .environment_clients import CodeToolAdapter, RuntimeLogAdapter
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


def register_environment_action_tool(
    registry: ToolRegistry,
    handler: ToolHandler,
) -> None:
    """Register the primary environment-action tool."""
    registry.register(
        Tool(
            name="environment_action",
            description=(
                "Execute one semantic environment action through the operator and active execution backend"
            ),
            action_format="semantic action string",
            handler=handler,
            action_parser=lambda action_text: {"action": _require_action(action_text)},
        )
    )


def register_code_tools(
    registry: ToolRegistry,
    adapter: CodeToolAdapter,
    codebase_adapter: Optional[UniversalCodebaseAdapter] = None,
) -> None:
    """Register white-box source-code interaction tools."""
    # Heuristically select the best adapter (API or Sandbox)
    ca = codebase_adapter or UniversalCodebaseAdapter(api_client=adapter)

    registry.register(
        Tool(
            name="code_list_files",
            description="List available source code files in the hub environment",
            action_format="any text",
            handler=lambda payload, runtime: _invoke_code_list(payload, runtime, ca),
            action_parser=lambda _: {},
        )
    )
    registry.register(
        Tool(
            name="code_read_file",
            description="Read source code from a file",
            action_format="path",
            handler=lambda payload, runtime: _invoke_code_read(payload, runtime, ca),
            action_parser=lambda t: {"path": t.strip()},
        )
    )
    registry.register(
        Tool(
            name="code_search",
            description="Search source code using a regex pattern",
            action_format="regex",
            handler=lambda payload, runtime: _invoke_code_search(payload, runtime, ca),
            action_parser=lambda t: {"pattern": t.strip()},
        )
    )
    registry.register(
        Tool(
            name="code_write_file",
            description="Modify code (use ONLY for white-box debugging)",
            action_format="path:content",
            handler=lambda payload, runtime: _invoke_code_write(payload, runtime, ca),
            action_parser=_parse_code_write_action,
        )
    )
    registry.register(
        Tool(
            name="code_restore_file",
            description="Undo code changes",
            action_format="path",
            handler=lambda payload, runtime: _invoke_code_restore(payload, runtime, ca),
            action_parser=lambda t: {"path": t.strip()},
        )
    )


def register_runtime_log_tool(
    registry: ToolRegistry,
    adapter: RuntimeLogAdapter,
) -> None:
    """Register access to runtime debug/console logs."""
    registry.register(
        Tool(
            name="code_read_debug_logs",
            description="Read real-time debug/console output from the environment",
            action_format="read or clear",
            handler=lambda payload, runtime: _invoke_runtime_log_tool(payload, runtime, adapter),
            action_parser=lambda t: {"clear": t.strip().lower() == "clear"},
        )
    )


def register_log_analysis_tool(
    registry: ToolRegistry,
    adapter: RuntimeLogAdapter,
    analyzer: LogAnalyzer,
) -> None:
    """Register the log anomaly detection tool."""
    registry.register(
        Tool(
            name="log_analyze",
            description="Analyze session history and debug logs for anomalies",
            action_format="analyze or JSON filters",
            handler=lambda payload, runtime: _invoke_log_analysis_tool(payload, runtime, adapter, analyzer),
            action_parser=_parse_log_analysis_action,
        )
    )


def _require_action(action_text: str) -> str:
    text = str(action_text).strip()
    if not text:
        raise ValueError("Planner action must not be empty")
    return text


def _parse_code_write_action(action_text: str) -> ToolPayload:
    if action_text.startswith("{"):
        return json.loads(action_text)
    parts = action_text.split(":", 1)
    if len(parts) < 2:
        raise ValueError("code_write_file requires 'path:content'")
    return {"path": parts[0].strip(), "content": parts[1]}


def _parse_log_analysis_action(action_text: str) -> ToolPayload:
    if action_text.strip().startswith("{"):
        return json.loads(action_text)
    return {"include_debug_output": True}


def _invoke_code_list(payload, runtime, adapter: UniversalCodebaseAdapter):
    files = adapter.list_files()
    res = {"success": True, "files": [{"path": f.path} for f in files]}
    return ToolInvocationResult(observation=_tool_observation("code_list_files", payload, res))

def _invoke_code_read(payload, runtime, adapter: UniversalCodebaseAdapter):
    content = adapter.read_file(payload.get("path", ""))
    res = {"success": content is not None, "content": content}
    return ToolInvocationResult(observation=_tool_observation("code_read_file", payload, res))

def _invoke_code_search(payload, runtime, adapter: UniversalCodebaseAdapter):
    matches = adapter.search_code(payload.get("pattern", ""))
    res = {"success": True, "matches": matches}
    return ToolInvocationResult(observation=_tool_observation("code_search", payload, res))

def _invoke_code_write(payload, runtime, adapter: UniversalCodebaseAdapter):
    success = adapter.write_file(payload.get("path", ""), payload.get("content", ""))
    return ToolInvocationResult(observation=_tool_observation("code_write_file", payload, {"success": success}))

def _invoke_code_restore(payload, runtime, adapter: UniversalCodebaseAdapter):
    success = adapter.restore_file(payload.get("path", ""))
    return ToolInvocationResult(observation=_tool_observation("code_restore_file", payload, {"success": success}))


def _invoke_runtime_log_tool(payload, runtime, adapter: RuntimeLogAdapter):
    session = runtime.get("session")
    if not session: raise RuntimeError("No active session")
    
    # Heuristic: try to get logs from client if available (e.g. CUA)
    client = session.raw.get("client") if isinstance(session.raw, dict) else None
    if client and hasattr(client, "read_browser_logs"):
        res = {"success": True, "logs": client.read_browser_logs()}
    elif getattr(session, "backend_type", "api") == "api":
        res = adapter.read_debug_logs(session.session_id, clear=payload.get("clear", False))
    else:
        res = {"success": False, "message": "Log capture not supported for this backend"}
    
    return ToolInvocationResult(observation=_tool_observation("code_read_debug_logs", payload, res))


def _invoke_log_analysis_tool(payload, runtime, adapter, analyzer: LogAnalyzer):
    session = runtime.get("session")
    if not session: raise RuntimeError("No active session")
    
    # Fetch history data
    history = runtime.get("history", [])
    if getattr(session, "backend_type", "api") == "api":
        session_res = adapter.read_session_log(session.session_id)
        session_data = session_res.get("data", {"commands": history})
    else:
        session_data = {"commands": history}
    
    # Try to fetch debug logs
    debug_logs = ""
    client = session.raw.get("client") if isinstance(session.raw, dict) else None
    if client and hasattr(client, "read_browser_logs"):
        try: debug_logs = client.read_browser_logs()
        except: pass
    
    analysis = analyzer.analyze_session(session_data, debug_logs)
    return ToolInvocationResult(observation=_tool_observation("log_analyze", payload, {"success": True, "analysis": analysis}))


def _tool_observation(tool_name: str, payload: ToolPayload, result: Dict[str, Any]) -> Observation:
    success = bool(result.get("success", False))
    summary = f"Code tool result: {tool_name} {'succeeded' if success else 'failed'}"
    if tool_name == "code_search":
        count = len(result.get("matches", []))
        summary = f"Code tool result: search found {count} matches"
    
    return Observation(
        success=success,
        message=str(result.get("message", "")) or summary,
        state={},
        raw=result,
        summary=summary,
        env_state={},
        artifacts={},
        execution={"diagnostics": {"tool": tool_name, "payload": payload}}
    )
