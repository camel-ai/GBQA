"""Runtime and agent trajectory log sources for GBQA diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Protocol

from .types import LifecycleEvent, StepRecord


@dataclass(frozen=True)
class LogSourceSpec:
    """Declarative log source configuration."""

    name: str
    kind: str
    path: str = ""
    glob: str = "*"
    description: str = ""
    enabled: bool = True
    tail_bytes: int = 200_000
    max_files: int = 5


@dataclass(frozen=True)
class LogReadResult:
    """Result returned by one log source read."""

    name: str
    kind: str
    success: bool
    text: str = ""
    session: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class LogSource(Protocol):
    """Read one configured log source."""

    spec: LogSourceSpec

    def read(self, runtime_context: Dict[str, Any] | None = None) -> LogReadResult:
        ...


class FileRuntimeLogSource:
    """Read target runtime logs from a declared file path."""

    def __init__(self, spec: LogSourceSpec) -> None:
        if spec.kind != "file":
            raise ValueError("FileRuntimeLogSource requires kind='file'")
        self.spec = spec

    def read(self, runtime_context: Dict[str, Any] | None = None) -> LogReadResult:
        del runtime_context
        path = Path(self.spec.path)
        if not path.exists():
            return LogReadResult(
                name=self.spec.name,
                kind=self.spec.kind,
                success=False,
                error=f"log source path does not exist: {path}",
                metadata={"path": str(path)},
            )
        if path.is_dir():
            return LogReadResult(
                name=self.spec.name,
                kind=self.spec.kind,
                success=False,
                error=f"log source path is a directory, not a file: {path}",
                metadata={"path": str(path)},
            )
        tail_bytes = max(int(self.spec.tail_bytes), 0)
        text = _read_tail(path, tail_bytes)
        return LogReadResult(
            name=self.spec.name,
            kind=self.spec.kind,
            success=True,
            text=text,
            metadata={"path": str(path), "tail_bytes": tail_bytes},
        )


class FileDirectoryRuntimeLogSource:
    """Read recent target runtime logs from a declared directory and glob."""

    def __init__(self, spec: LogSourceSpec) -> None:
        if spec.kind != "file_directory":
            raise ValueError("FileDirectoryRuntimeLogSource requires kind='file_directory'")
        self.spec = spec

    def read(self, runtime_context: Dict[str, Any] | None = None) -> LogReadResult:
        del runtime_context
        path = Path(self.spec.path)
        if not path.exists():
            return LogReadResult(
                name=self.spec.name,
                kind=self.spec.kind,
                success=False,
                error=f"log source directory does not exist: {path}",
                metadata={"path": str(path), "glob": self.spec.glob},
            )
        if not path.is_dir():
            return LogReadResult(
                name=self.spec.name,
                kind=self.spec.kind,
                success=False,
                error=f"log source path is not a directory: {path}",
                metadata={"path": str(path), "glob": self.spec.glob},
            )
        candidates = [
            item
            for item in path.glob(self.spec.glob)
            if item.is_file()
        ]
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        selected = candidates[: max(int(self.spec.max_files), 1)]
        if not selected:
            return LogReadResult(
                name=self.spec.name,
                kind=self.spec.kind,
                success=False,
                error=f"no log files matched {self.spec.glob} under {path}",
                metadata={"path": str(path), "glob": self.spec.glob},
            )

        chunks: List[str] = []
        file_metadata: List[Dict[str, Any]] = []
        for file_path in selected:
            text = _read_tail(file_path, self.spec.tail_bytes)
            chunks.append(f"== {file_path.name} ==\n{text}")
            file_metadata.append(
                {
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                    "mtime": file_path.stat().st_mtime,
                }
            )
        return LogReadResult(
            name=self.spec.name,
            kind=self.spec.kind,
            success=True,
            text="\n\n".join(chunks),
            metadata={
                "path": str(path),
                "glob": self.spec.glob,
                "max_files": int(self.spec.max_files),
                "files": file_metadata,
            },
        )


class AgentTrajectoryLogSource:
    """Expose harness-owned planner/tool/observation history as a log source."""

    spec = LogSourceSpec(
        name="agent_trajectory",
        kind="agent_trajectory",
        description=(
            "GBQA harness planner/tool/observation trajectory grouped by "
            "environment, code, log, and other tool interactions."
        ),
    )

    def read(self, runtime_context: Dict[str, Any] | None = None) -> LogReadResult:
        runtime_context = runtime_context or {}
        steps = runtime_context.get("steps") or runtime_context.get("history") or []
        lifecycle_events = runtime_context.get("lifecycle_events", [])
        commands: List[Dict[str, Any]] = []
        groups: Dict[str, List[Dict[str, Any]]] = {
            "environment_interactions": [],
            "code_tool_interactions": [],
            "log_tool_interactions": [],
            "other_tool_interactions": [],
        }
        for record in steps:
            if not isinstance(record, StepRecord):
                continue
            category = _agent_trajectory_category(record.action.tool)
            command = {
                "step": record.step,
                "tool": record.action.tool,
                "category": category,
                "command": record.action.command,
                "response": {
                    "success": record.observation.success,
                    "message": record.observation.summary
                    or record.observation.message,
                    "terminal": record.observation.terminal,
                },
                "state_snapshot": record.observation.env_state
                or record.observation.state,
                "execution": record.observation.execution,
            }
            commands.append(command)
            groups[category].append(command)
        category_counts = {
            category: len(items)
            for category, items in groups.items()
        }
        lifecycle_payload = [
            _lifecycle_event_payload(event)
            for event in lifecycle_events
            if isinstance(event, LifecycleEvent) or isinstance(event, dict)
        ]
        return LogReadResult(
            name=self.spec.name,
            kind=self.spec.kind,
            success=True,
            session={
                "commands": commands,
                "lifecycle_events": lifecycle_payload,
                "groups": groups,
                "category_counts": category_counts,
                "total_steps": len(commands),
            },
            metadata={
                "step_count": len(commands),
                "lifecycle_event_count": len(lifecycle_payload),
                "category_counts": category_counts,
            },
        )


def build_log_sources(configured_sources: List[Dict[str, Any]]) -> List[LogSource]:
    """Build supported target runtime log sources from config."""
    sources: List[LogSource] = []
    for payload in configured_sources:
        if not isinstance(payload, dict) or payload.get("enabled", True) is False:
            continue
        spec = LogSourceSpec(
            name=str(payload.get("name") or "").strip(),
            kind=str(payload.get("kind") or payload.get("type") or "").strip(),
            path=str(payload.get("path") or "").strip(),
            glob=str(payload.get("glob") or "*").strip(),
            description=str(payload.get("description") or "").strip(),
            enabled=bool(payload.get("enabled", True)),
            tail_bytes=int(payload.get("tail_bytes", 200_000)),
            max_files=int(payload.get("max_files", 5)),
        )
        if not spec.name or not spec.kind:
            continue
        if spec.kind == "file":
            sources.append(FileRuntimeLogSource(spec))
        elif spec.kind == "file_directory":
            sources.append(FileDirectoryRuntimeLogSource(spec))
    return sources


def _agent_trajectory_category(tool_name: str) -> str:
    tool_name = str(tool_name).strip()
    if tool_name == "environment_action":
        return "environment_interactions"
    if tool_name.startswith("code_"):
        return "code_tool_interactions"
    if tool_name.startswith("log_"):
        return "log_tool_interactions"
    return "other_tool_interactions"


def _lifecycle_event_payload(event: LifecycleEvent | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(event, LifecycleEvent):
        return asdict(event)
    return dict(event)


def _read_tail(path: Path, tail_bytes: int) -> str:
    tail_bytes = max(int(tail_bytes), 0)
    with path.open("rb") as handle:
        if tail_bytes:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(size - tail_bytes, 0))
        payload = handle.read()
    return payload.decode("utf-8", errors="replace")
