"""Planner-visible tool registry with progressive skill disclosure."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .codebase_types import UniversalCodebaseAdapter
from .log_analyzer import LogAnalyzer
from .log_sources import LogSource
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
    input_schema: Dict[str, Any] | None = None
    side_effect: str = "read"

    def invoke(
        self,
        payload: ToolPayload,
        runtime_context: ToolRuntimeContext,
    ) -> ToolInvocationResult:
        return self.handler(payload, runtime_context)

    def parse_action(self, action_text: str) -> ToolPayload:
        return self.action_parser(action_text)


@dataclass
class SkillCard:
    """Agent Skills-style metadata loaded before activation."""

    name: str
    description: str
    instructions: str = ""
    path: str = ""


class ToolRegistry:
    """Registers executable tools and discloses optional tools progressively."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}
        self._tool_skills: Dict[str, str] = {}
        self._skills: Dict[str, SkillCard] = {}
        self._activated_skills: set[str] = set()

    def register(self, tool: Tool, *, skill_name: str = "") -> None:
        self._tools[tool.name] = tool
        if skill_name:
            sn = skill_name.strip().lower()
            self._tool_skills[tool.name] = sn
            if sn not in self._skills:
                self.register_skill(
                    SkillCard(
                        name=sn,
                        description=f"Optional skill for {sn} tools.",
                    )
                )

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def list_visible_tools(self) -> List[Tool]:
        return [
            tool
            for tool in self._tools.values()
            if self._is_tool_visible(tool.name)
        ]

    def register_skill(self, skill: SkillCard) -> None:
        name = skill.name.strip().lower()
        if not name:
            raise ValueError("Skill name must not be empty")
        self._skills[name] = SkillCard(
            name=name,
            description=skill.description.strip(),
            instructions=skill.instructions.strip(),
            path=skill.path.strip(),
        )
        self._ensure_use_skill_tool()

    def activate_skill(self, skill_name: str) -> Dict[str, Any]:
        name = str(skill_name).strip().lower()

        if name not in self._skills:
            return {
                "success": False,
                "skill": name,
                "message": f"Unknown or disabled skill: {name}",
            }
        self._activated_skills.add(name)
        visible_tools = [
            tool.name
            for tool in self._tools.values()
            if self._tool_skills.get(tool.name) == name
        ]
        if not visible_tools:
            return {
                "success": False,
                "skill": name,
                "message": f"Skill '{name}' has no registered tools in this run.",
            }
        return {
            "success": True,
            "skill": name,
            "description": self._skills[name].description,
            "instructions": self._skills[name].instructions,
            "path": self._skills[name].path,
            "tools": visible_tools,
        }

    def parse_action(self, name: str, action_text: str) -> ToolPayload:
        return self._get(name).parse_action(action_text)

    def invoke(
        self,
        name: str,
        payload: ToolPayload,
        runtime_context: ToolRuntimeContext,
    ) -> ToolInvocationResult:
        return self._get(name).invoke(payload, runtime_context)

    def invoke_internal(
        self,
        name: str,
        payload: ToolPayload,
        runtime_context: ToolRuntimeContext,
    ) -> ToolInvocationResult:
        return self._get(name, include_hidden=True).invoke(payload, runtime_context)

    def render_prompt_section(self) -> str:
        lines = ["## Available Tools:"]
        for tool in self.list_visible_tools():
            lines.append(
                f"- {tool.name}: {tool.description} Format: `{tool.action_format}`."
            )
        activated_skills = [
            skill
            for skill in self._skills.values()
            if skill.name in self._activated_skills and skill.instructions
        ]
        if activated_skills:
            lines.extend(["", "## Activated Skill Instructions:"])
            for skill in activated_skills:
                lines.append(f"### {skill.name}")
                lines.append(skill.instructions)
        available_skills = [
            skill
            for skill in self._skills.values()
            if skill.name not in self._activated_skills
        ]
        if available_skills:
            lines.extend(
                [
                    "",
                    "## Available Skills:",
                    (
                        "Use `use_skill` with the skill name to load that skill's "
                        "full SKILL.md instructions when relevant."
                    ),
                ]
            )
            for skill in available_skills:
                path = f" (SKILL.md: {skill.path})" if skill.path else ""
                lines.append(f"- {skill.name}: {skill.description}{path}")
        return "\n".join(lines)

    def describe_policy(self) -> Dict[str, Any]:
        """Return structured tool/skill policy for run metadata."""

        return {
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "path": skill.path,
                    "activated": skill.name in self._activated_skills,
                }
                for skill in self._skills.values()
            ],
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "action_format": tool.action_format,
                    "input_schema": tool.input_schema or _string_action_schema(
                        tool.action_format
                    ),
                    "side_effect": tool.side_effect,
                    "skill": self._tool_skills.get(tool.name, ""),
                    "visible": self._is_tool_visible(tool.name),
                }
                for tool in self._tools.values()
            ],
        }

    def _get(self, name: str, *, include_hidden: bool = False) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        if not include_hidden and not self._is_tool_visible(name):
            skill_name = self._tool_skills.get(name, "")
            if skill_name:
                raise KeyError(
                    f"Tool '{name}' is not currently visible. "
                    f"Open skill '{skill_name}' first."
                )
            raise KeyError(f"Tool '{name}' is not currently visible")
        return self._tools[name]

    def _is_tool_visible(self, name: str) -> bool:
        skill_name = self._tool_skills.get(name, "")
        return not skill_name or skill_name in self._activated_skills

    def _ensure_use_skill_tool(self) -> None:
        if "use_skill" in self._tools:
            return
        self.register(
            Tool(
                name="use_skill",
                description="Load an available skill's SKILL.md instructions and reveal its tools",
                action_format="skill name",
                handler=lambda payload, runtime: _invoke_use_skill_tool(
                    payload,
                    runtime,
                    self,
                ),
                action_parser=_parse_use_skill_action,
                input_schema={
                    "type": "object",
                    "properties": {"skill": {"type": "string"}},
                    "required": ["skill"],
                },
                side_effect="control",
            )
        )


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
            input_schema={
                "type": "object",
                "properties": {"action": {"type": "string"}},
                "required": ["action"],
            },
            side_effect="environment",
        )
    )


def register_lifecycle_tools(registry: ToolRegistry) -> None:
    """Register lifecycle skill tools and activate the skill by default."""
    skill_name = "lifecycle"
    try:
        registry.register_skill(_load_builtin_skill(skill_name))
    except (FileNotFoundError, ValueError):
        registry.register_skill(
            SkillCard(
                name=skill_name,
                description="Task and session lifecycle control for QA exploration.",
            )
        )

    lifecycle_tools = [
        (
            "start_session",
            "Open a new session and make it the active session",
            "short reason for opening a session",
            lambda action_text: {"reason": _require_action(action_text)},
        ),
        (
            "end_session",
            "Close one open session without starting another",
            "session_id or session_id reason, or a reason alone for the active session",
            _parse_end_session_action,
        ),
        (
            "new_session",
            "Open a fresh session and make it active regardless of other open sessions",
            "short reason for opening a fresh session",
            lambda action_text: {"reason": _require_action(action_text)},
        ),
        (
            "refresh_session",
            "Refresh capability metadata for a specific open session",
            "session_id",
            lambda action_text: {"session_id": _require_action(action_text)},
        ),
        (
            "switch_session",
            "Switch the active session to an already-open session_id",
            "session_id",
            lambda action_text: {"session_id": _require_action(action_text)},
        ),
        (
            "list_sessions",
            "List open session_ids and the current active session_id",
            "any non-empty text (ignored)",
            lambda _action_text: {},
        ),
        (
            "end_task",
            "Finish the current QA task and stop the interaction loop",
            "short reason for finishing the task",
            lambda action_text: {"reason": _require_action(action_text)},
        ),
    ]
    for name, description, action_format, action_parser in lifecycle_tools:
        registry.register(
            Tool(
                name=name,
                description=description,
                action_format=action_format,
                handler=lambda payload, runtime, tool_name=name: _invoke_lifecycle_tool(
                    tool_name,
                    payload,
                    runtime,
                ),
                action_parser=action_parser,
                input_schema=_lifecycle_tool_schema(name),
                side_effect="control",
            ),
            skill_name=skill_name,
        )
    registry.activate_skill(skill_name)


def register_code_tools(
    registry: ToolRegistry,
    codebase_adapter: UniversalCodebaseAdapter,
) -> None:
    """Register white-box source-code tools."""
    skill_name = "code"
    try:
        registry.register_skill(_load_builtin_skill(skill_name))
    except (FileNotFoundError, ValueError):
        # Mandatory fallback registration if SKILL.md is missing or unparseable
        registry.register_skill(
            SkillCard(
                name=skill_name,
                description="Codebase reading and white-box debugging capabilities.",
            )
        )

    registry.register(
        Tool(
            name="code_list_files",
            description="List available source code files for the current environment",
            action_format="any non-empty text (ignored)",
            handler=lambda payload, runtime: _invoke_code_list(payload, runtime, codebase_adapter),
            action_parser=lambda _: {},
            input_schema={"type": "object", "properties": {}},
            side_effect="read",
        ),
        skill_name=skill_name,
    )
    registry.register(
        Tool(
            name="code_read_file",
            description="Read a source file, optionally with a line range",
            action_format="path or path:start-end",
            handler=lambda payload, runtime: _invoke_code_read(payload, runtime, codebase_adapter),
            action_parser=_parse_code_read_action,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["path"],
            },
            side_effect="read",
        ),
        skill_name=skill_name,
    )
    registry.register(
        Tool(
            name="code_search",
            description="Search source code using a regex pattern",
            action_format="pattern",
            handler=lambda payload, runtime: _invoke_code_search(payload, runtime, codebase_adapter),
            action_parser=lambda action_text: {"pattern": _require_action(action_text)},
            input_schema={
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
            side_effect="read",
        ),
        skill_name=skill_name,
    )
    registry.register(
        Tool(
            name="code_write_file",
            description="Modify code (use ONLY for white-box debugging)",
            action_format="path:content",
            handler=lambda payload, runtime: _invoke_code_write(payload, runtime, codebase_adapter),
            action_parser=_parse_code_write_action,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "patch": {"type": "object"},
                },
                "required": ["path"],
            },
            side_effect="write",
        ),
        skill_name=skill_name,
    )
    registry.register(
        Tool(
            name="code_restore_file",
            description="Undo code changes",
            action_format="path",
            handler=lambda payload, runtime: _invoke_code_restore(payload, runtime, codebase_adapter),
            action_parser=lambda action_text: {"path": _require_action(action_text)},
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            side_effect="write",
        ),
        skill_name=skill_name,
    )


def register_log_tools(
    registry: ToolRegistry,
    sources: List[LogSource],
    analyzer: LogAnalyzer,
) -> None:
    """Register source-backed log reading and analysis tools."""
    active_sources = list(sources)
    if not active_sources:
        return
    skill_name = "logs"
    try:
        registry.register_skill(_load_builtin_skill(skill_name))
    except (FileNotFoundError, ValueError):
        registry.register_skill(
            SkillCard(
                name=skill_name,
                description="Exposed runtime logs and agent trajectory analysis.",
            )
        )

    registry.register(
        Tool(
            name="log_list",
            description="List exposed runtime and agent trajectory log sources",
            action_format="any non-empty text (ignored)",
            handler=lambda payload, runtime: _invoke_log_list_tool(
                payload,
                runtime,
                active_sources,
            ),
            action_parser=lambda _action_text: {},
            input_schema={"type": "object", "properties": {}},
            side_effect="read",
        ),
        skill_name=skill_name,
    )
    registry.register(
        Tool(
            name="log_read",
            description="Read exposed runtime or agent trajectory log sources",
            action_format="source name or 'all'",
            handler=lambda payload, runtime: _invoke_log_read_tool(
                payload,
                runtime,
                active_sources,
            ),
            action_parser=lambda action_text: {"source": _require_action(action_text)},
            input_schema={
                "type": "object",
                "properties": {"source": {"type": "string"}},
                "required": ["source"],
            },
            side_effect="read",
        ),
        skill_name=skill_name,
    )
    registry.register(
        Tool(
            name="log_analyze",
            description="Analyze exposed runtime logs and agent trajectory for anomalies",
            action_format=(
                "analyze, failures, or JSON object with source/start_step/end_step/"
                "failures_only/limit/include_debug_output"
            ),
            handler=lambda payload, runtime: _invoke_source_log_analysis_tool(
                payload,
                runtime,
                active_sources,
                analyzer,
            ),
            action_parser=_parse_log_analysis_action,
            input_schema={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "start_step": {"type": "integer"},
                    "end_step": {"type": "integer"},
                    "failures_only": {"type": "boolean"},
                    "limit": {"type": "integer"},
                    "include_debug_output": {"type": "boolean"},
                },
            },
            side_effect="read",
        ),
        skill_name=skill_name,
    )


def _string_action_schema(action_format: str) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": action_format,
            }
        },
        "required": ["action"],
    }


def _lifecycle_tool_schema(name: str) -> Dict[str, Any]:
    if name in {"refresh_session", "switch_session"}:
        return {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        }
    if name == "end_session":
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "reason": {"type": "string"},
            },
        }
    if name == "list_sessions":
        return {"type": "object", "properties": {}}
    return {
        "type": "object",
        "properties": {"reason": {"type": "string"}},
        "required": ["reason"],
    }


def _require_action(action_text: str) -> str:
    text = str(action_text).strip()
    if not text:
        raise ValueError("Planner action must not be empty")
    return text


def _load_builtin_skill(skill_name: str) -> SkillCard:
    # Try multiple common relative paths for the skills directory
    root = Path(__file__).resolve().parents[1]
    paths_to_try = [
        root / "skills" / skill_name / "SKILL.md",
        root.parent / "skills" / skill_name / "SKILL.md",
        Path("/sandbox/agent/skills") / skill_name / "SKILL.md",
        Path("agent/skills") / skill_name / "SKILL.md",
    ]
    for skill_path in paths_to_try:
        if skill_path.exists():
            return _load_skill_file(skill_path)
    
    raise FileNotFoundError(f"Skill file not found for: {skill_name}")


def _load_skill_file(path: Path) -> SkillCard:
    if not path.exists():
        raise FileNotFoundError(f"Skill file not found: {path}")
    text = path.read_text(encoding="utf-8")
    metadata, body = _parse_skill_markdown(text)
    name = str(metadata.get("name") or "").strip().lower()
    description = str(metadata.get("description") or "").strip()
    if not name or not description:
        raise ValueError(f"Skill file must define name and description: {path}")
    return SkillCard(
        name=name,
        description=description,
        instructions=body,
        path=str(path),
    )


def _parse_skill_markdown(text: str) -> tuple[Dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Skill file must start with YAML frontmatter")
    metadata: Dict[str, str] = {}
    end_index = 0
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip()
    if end_index == 0:
        raise ValueError("Skill file must close YAML frontmatter with ---")
    body = "\n".join(lines[end_index + 1 :]).strip()
    return metadata, body


def _parse_use_skill_action(action_text: str) -> ToolPayload:
    text = _require_action(action_text).lower()
    # Support 'use_skill code' or just 'code'
    if text.startswith("use_skill "):
        text = text.replace("use_skill ", "", 1).strip()
    return {"skill": text}


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
        # Fallback to simple path:content
        parts = text.split(":", 1)
        if len(parts) == 2:
            return {"path": parts[0].strip(), "content": parts[1].strip()}
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


def _parse_log_analysis_action(action_text: str) -> ToolPayload:
    if action_text.strip().startswith("{"):
        return json.loads(action_text)
    return {"include_debug_output": True}


def _invoke_code_list(payload, runtime, adapter: Any):
    if hasattr(adapter, "list_code_files"):
        res = adapter.list_code_files()
    else:
        files = adapter.list_files()
        res = {"success": True, "files": [{"path": f.path} for f in files]}
    return ToolInvocationResult(observation=_tool_observation("code_list_files", payload, res))

def _invoke_code_read(payload, runtime, adapter: Any):
    path = payload.get("path", "")
    if hasattr(adapter, "read_code_file"):
        res = adapter.read_code_file(
            path,
            start_line=int(payload.get("start_line", 0) or 0),
            end_line=int(payload.get("end_line", 0) or 0),
        )
    else:
        content = adapter.read_file(path)
        res = {"success": content is not None, "path": path, "content": content}
    return ToolInvocationResult(observation=_tool_observation("code_read_file", payload, res))

def _invoke_code_search(payload, runtime, adapter: Any):
    matches = adapter.search_code(payload.get("pattern", ""))
    res = {"success": True, "matches": matches}
    return ToolInvocationResult(observation=_tool_observation("code_search", payload, res))

def _invoke_code_write(payload, runtime, adapter: Any):
    path = payload.get("path", "")
    content = payload.get("content", "")
    patch = payload.get("patch")
    if hasattr(adapter, "write_code_file"):
        res = adapter.write_code_file(path, content=content, patch=patch)
    else:
        success = adapter.write_file(path, content)
        res = {"success": success}
    return ToolInvocationResult(observation=_tool_observation("code_write_file", payload, res))

def _invoke_code_restore(payload, runtime, adapter: Any):
    path = payload.get("path", "")
    if hasattr(adapter, "restore_code_file"):
        res = adapter.restore_code_file(path)
    else:
        success = adapter.restore_file(path)
        res = {"success": success}
    return ToolInvocationResult(observation=_tool_observation("code_restore_file", payload, res))


def _invoke_use_skill_tool(
    payload: ToolPayload,
    runtime_context: ToolRuntimeContext,
    registry: ToolRegistry,
) -> ToolInvocationResult:
    del runtime_context
    result = registry.activate_skill(str(payload.get("skill") or ""))
    return ToolInvocationResult(
        observation=_tool_observation("use_skill", payload, result),
    )


def _parse_end_session_action(action_text: str) -> ToolPayload:
    text = action_text.strip()
    if not text:
        raise ValueError("end_session requires a session_id or reason")
    first, _, remainder = text.partition(" ")
    if remainder:
        return {
            "session_id": first,
            "reason": remainder.strip() or "agent requested session end",
        }
    return {"reason": first}


def _invoke_lifecycle_tool(
    tool_name: str,
    payload: ToolPayload,
    runtime_context: ToolRuntimeContext,
) -> ToolInvocationResult:
    del runtime_context
    reason = str(payload.get("reason") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    message = reason or session_id or tool_name
    return ToolInvocationResult(
        observation=_tool_observation(
            tool_name,
            payload,
            {
                "success": True,
                "message": message,
                "reason": reason,
                "session_id": session_id,
            },
        )
    )


def _invoke_log_list_tool(
    payload: ToolPayload,
    runtime_context: ToolRuntimeContext,
    sources: List[LogSource],
) -> ToolInvocationResult:
    del runtime_context
    source_payload = [
        {
            "name": source.spec.name,
            "kind": source.spec.kind,
            "path": source.spec.path,
            "glob": source.spec.glob,
            "description": source.spec.description,
        }
        for source in sources
    ]
    return ToolInvocationResult(
        observation=_tool_observation(
            "log_list",
            payload,
            {"success": True, "sources": source_payload},
        )
    )


def _invoke_log_read_tool(
    payload: ToolPayload,
    runtime_context: ToolRuntimeContext,
    sources: List[LogSource],
) -> ToolInvocationResult:
    requested = str(payload.get("source") or "all").strip()
    selected = [
        source
        for source in sources
        if requested == "all" or source.spec.name == requested
    ]
    if not selected:
        raise RuntimeError(f"Unknown log source: {requested}")
    results = [source.read(runtime_context).__dict__ for source in selected]
    return ToolInvocationResult(
        observation=_tool_observation(
            "log_read",
            payload,
            {"success": True, "sources": results},
        )
    )


def _invoke_source_log_analysis_tool(
    payload: ToolPayload,
    runtime_context: ToolRuntimeContext,
    sources: List[LogSource],
    analyzer: LogAnalyzer,
) -> ToolInvocationResult:
    requested = str(payload.get("source") or "all").strip()
    selected = [
        source
        for source in sources
        if requested == "all" or source.spec.name == requested
    ]
    if not selected:
        raise RuntimeError(f"Unknown log source: {requested}")

    sessions: List[Dict[str, Any]] = []
    debug_chunks: List[str] = []
    read_errors: List[Dict[str, str]] = []
    include_debug_output = bool(payload.get("include_debug_output", True))
    for source in selected:
        read_result = source.read(runtime_context)
        if not read_result.success:
            read_errors.append({"source": read_result.name, "error": read_result.error})
            continue
        if read_result.session:
            sessions.append(read_result.session)
        if include_debug_output and read_result.text:
            debug_chunks.append(f"== {read_result.name} ==\n{read_result.text}")

    merged_session = _merge_log_sessions(sessions)
    debug_output = "\n\n".join(debug_chunks)
    result: Dict[str, Any] = {
        "success": True,
        "analysis": analyzer.analyze_session(merged_session, debug_output),
        "sources": [source.spec.name for source in selected],
    }
    if read_errors:
        result["read_errors"] = read_errors
    if _has_log_analysis_filters(payload):
        result["filtered_commands"] = analyzer.filter_commands(
            merged_session,
            start_step=int(payload.get("start_step", 0)),
            end_step=int(payload.get("end_step", 0)),
            failures_only=bool(payload.get("failures_only", False)),
            limit=int(payload.get("limit", 50)),
        )
    return ToolInvocationResult(
        observation=_tool_observation("log_analyze", payload, result),
    )


def _merge_log_sessions(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    commands: List[Dict[str, Any]] = []
    for session in sessions:
        raw_commands = session.get("commands", [])
        if isinstance(raw_commands, list):
            commands.extend(item for item in raw_commands if isinstance(item, dict))
    return {
        "commands": commands,
        "total_steps": len(commands),
        "result": "in_progress",
    }


def _has_log_analysis_filters(payload: ToolPayload) -> bool:
    if int(payload.get("start_step", 0)) > 0:
        return True
    if int(payload.get("end_step", 0)) > 0:
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
    if tool_name in {
        "start_session",
        "end_session",
        "new_session",
        "refresh_session",
        "switch_session",
        "list_sessions",
        "end_task",
    }:
        reason = str(result.get("reason") or result.get("message") or "").strip()
        session_id = str(result.get("session_id") or "").strip()
        if tool_name == "start_session":
            return f"Lifecycle request: open a new session. Reason: {reason}".rstrip()
        if tool_name == "end_session":
            target = session_id or "active session"
            return (
                f"Lifecycle request: close session {target}. Reason: {reason}"
            ).rstrip()
        if tool_name == "new_session":
            return (
                f"Lifecycle request: open a fresh active session. Reason: {reason}"
            ).rstrip()
        if tool_name == "refresh_session":
            return f"Lifecycle request: refresh session {session_id}".rstrip()
        if tool_name == "switch_session":
            return f"Lifecycle request: switch active session to {session_id}".rstrip()
        if tool_name == "list_sessions":
            return "Lifecycle request: list open sessions and active session_id"
        return f"Lifecycle request: end task. Reason: {reason}".rstrip()
    if tool_name == "use_skill":
        skill_name = str(result.get("skill", "")).strip()
        if not bool(result.get("success", False)):
            message = str(result.get("message", "")).strip()
            return message or f"Skill activation failed: {skill_name}"
        tools = result.get("tools", [])
        tool_list = ", ".join(str(tool) for tool in tools) if isinstance(tools, list) else ""
        instructions = str(result.get("instructions", "")).strip()
        path = str(result.get("path", "")).strip()
        parts = [f"Skill loaded: {skill_name}"]
        if path:
            parts.append(f"Loaded from: {path}")
        if tool_list:
            parts.append(f"Revealed tools: {tool_list}")
        if instructions:
            parts.append(f"SKILL.md instructions:\n{instructions}")
        return "\n".join(parts)
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
    if tool_name == "log_list":
        sources = result.get("sources", [])
        if isinstance(sources, list):
            lines = ["Available log sources:"]
            for source in sources:
                if not isinstance(source, dict):
                    continue
                name = str(source.get("name", "")).strip()
                kind = str(source.get("kind", "")).strip()
                description = str(source.get("description", "")).strip()
                lines.append(f"- {name} ({kind}): {description}".rstrip())
            return "\n".join(lines)
        return "Available log sources: none."
    if tool_name == "log_read":
        sources = result.get("sources", [])
        if isinstance(sources, list):
            return "Log read result:\n" + json.dumps(
                sources,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        return "Log read result."
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
                        f"  S{command.get('step', '?')}: [{status}] "
                        f"{str(command.get('command', '')).strip()}"
                    )
        read_errors = result.get("read_errors", [])
        if isinstance(read_errors, list) and read_errors:
            for item in read_errors[:5]:
                if not isinstance(item, dict):
                    continue
                source = str(item.get("source", "")).strip() or "unknown"
                error = str(item.get("error", "")).strip()
                parts.append(f"Log source read failed ({source}): {error}")
        if parts:
            return "\n".join(parts)
    path = str(result.get("path", "")).strip()
    message = str(result.get("message", "")).strip()
    if path and message:
        return f"Code tool result ({path}): {message}"
    if message:
        return f"Code tool result: {message}"
    return f"Code tool result: {json.dumps(result, ensure_ascii=False)}"
