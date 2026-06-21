"""Execution backend abstractions and built-in implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Protocol
from uuid import uuid4

from .interaction_modes import (
    backend_type_for_interaction_mode,
    interaction_mode_for_backend_type,
    normalize_interaction_mode,
)

from .config import Config
from .environment_clients import (
    EnvironmentActionClient,
    EnvironmentClientConfig,
    create_http_environment_action_client,
)
from .observer import ObservationParser
from .types import (
    BackendExecutionResult,
    CapabilityDescriptor,
    ExecutionAttempt,
    ExecutionRequest,
    Observation,
    SessionHandle,
)


class ExecutionBackend(Protocol):
    """Unified backend contract for environment execution."""

    backend_type: str

    def start_session(self, run_context: Dict[str, Any]) -> SessionHandle:
        """Create a run-bound session."""

    def describe_capabilities(
        self,
        session: SessionHandle,
        refresh: bool = False,
    ) -> CapabilityDescriptor:
        """Return planner/operator-facing capability metadata."""

    def execute(
        self,
        session: SessionHandle,
        request: ExecutionRequest,
    ) -> BackendExecutionResult:
        """Execute a normalized operator request."""

    def close_session(self, session: SessionHandle) -> None:
        """Close resources for the given session."""


@dataclass(frozen=True)
class ExecutionBackendSpec:
    """Resolved backend construction metadata."""

    backend_type: str
    settings: Dict[str, Any]
    adapters: Dict[str, Any]
    interaction_profile: str = ""
    primary_mode: str = ""
    enabled_modes: list[str] = field(default_factory=list)
    enabled_backends: list[str] = field(default_factory=list)


class MultiModeExecutionBackend:
    """Lazy execution backend that can route one run across interaction modes."""

    backend_type = "multi_mode"

    def __init__(
        self,
        *,
        primary_mode: str,
        backends_by_mode: Dict[str, ExecutionBackend],
    ) -> None:
        if primary_mode not in backends_by_mode:
            raise ValueError("Multi-mode backend requires a primary mode backend")
        self.primary_mode = primary_mode
        self.enabled_modes = list(backends_by_mode)
        self._backends_by_mode = dict(backends_by_mode)

    def backend_for_mode(self, mode: str) -> ExecutionBackend:
        normalized = normalize_interaction_mode(mode)
        if normalized not in self._backends_by_mode:
            raise ValueError(f"Interaction mode is not enabled: {mode}")
        return self._backends_by_mode[normalized]

    def start_session(self, run_context: Dict[str, Any]) -> SessionHandle:
        parent = SessionHandle(
            session_id=str(uuid4()),
            backend_type=self.backend_type,
            raw={"child_sessions": {}, "run_context": dict(run_context)},
            metadata={
                "primary_mode": self.primary_mode,
                "enabled_modes": list(self.enabled_modes),
            },
        )
        primary_session = self.ensure_mode_session(parent, self.primary_mode)
        parent.initial_observation = primary_session.initial_observation
        parent.metadata["active_mode"] = self.primary_mode
        parent.metadata["child_session_ids"] = self._child_session_ids(parent)
        return parent

    def ensure_mode_session(
        self,
        session: SessionHandle,
        mode: str,
    ) -> SessionHandle:
        normalized = normalize_interaction_mode(mode)
        backend = self.backend_for_mode(normalized)
        child_sessions = session.raw.setdefault("child_sessions", {})
        if not isinstance(child_sessions, dict):
            child_sessions = {}
            session.raw["child_sessions"] = child_sessions
        child = child_sessions.get(normalized)
        if isinstance(child, SessionHandle):
            session.metadata["active_mode"] = normalized
            session.metadata["child_session_ids"] = self._child_session_ids(session)
            return child
        child = backend.start_session(dict(session.raw.get("run_context", {})))
        child_sessions[normalized] = child
        session.metadata["active_mode"] = normalized
        session.metadata["child_session_ids"] = self._child_session_ids(session)
        return child

    def describe_capabilities(
        self,
        session: SessionHandle,
        refresh: bool = False,
    ) -> CapabilityDescriptor:
        return self.describe_mode_capabilities(session, self.primary_mode, refresh=refresh)

    def describe_mode_capabilities(
        self,
        session: SessionHandle,
        mode: str,
        refresh: bool = False,
    ) -> CapabilityDescriptor:
        normalized = normalize_interaction_mode(mode)
        child = self.ensure_mode_session(session, normalized)
        backend = self.backend_for_mode(normalized)
        capability = backend.describe_capabilities(child, refresh=refresh)
        summary = (
            f"Interaction mode: {normalized}. "
            f"Backend: {backend.backend_type}.\n{capability.planner_summary}"
        )
        return CapabilityDescriptor(
            planner_summary=summary,
            operator_context={
                **capability.operator_context,
                "interaction_mode": normalized,
                "backend_type": backend.backend_type,
            },
            raw={
                **capability.raw,
                "interaction_mode": normalized,
                "backend_type": backend.backend_type,
            },
        )

    def execute(
        self,
        session: SessionHandle,
        request: ExecutionRequest,
    ) -> BackendExecutionResult:
        mode = normalize_interaction_mode(
            request.metadata.get("interaction_mode")
            or session.metadata.get("active_mode")
            or self.primary_mode
        )
        child = self.ensure_mode_session(session, mode)
        backend = self.backend_for_mode(mode)
        return backend.execute(child, request)

    def close_session(self, session: SessionHandle) -> None:
        child_sessions = session.raw.get("child_sessions", {})
        if not isinstance(child_sessions, dict):
            return
        for mode, child in list(child_sessions.items()):
            if not isinstance(child, SessionHandle):
                continue
            try:
                self.backend_for_mode(str(mode)).close_session(child)
            finally:
                child_sessions.pop(mode, None)
        session.metadata["child_session_ids"] = {}

    @staticmethod
    def _child_session_ids(session: SessionHandle) -> Dict[str, str]:
        child_sessions = session.raw.get("child_sessions", {})
        if not isinstance(child_sessions, dict):
            return {}
        return {
            str(mode): child.session_id
            for mode, child in child_sessions.items()
            if isinstance(child, SessionHandle)
        }


class ApiExecutionBackend:
    """ExecutionBackend adapter for command-style HTTP APIs."""

    backend_type = "api"

    def __init__(self, client: EnvironmentActionClient) -> None:
        self._client = client
        self._parser = ObservationParser()

    def start_session(self, run_context: Dict[str, Any]) -> SessionHandle:
        payload = self._client.start_session()
        normalized = self._normalize_payload(
            payload,
            execution={
                "attempts": [],
                "diagnostics": {"backend_type": self.backend_type},
            },
        )
        return SessionHandle(
            session_id=str(payload.get("session_id", "")) or str(uuid4()),
            backend_type=self.backend_type,
            raw={"initial_payload": payload},
            metadata={"initial_message": normalized.summary},
            initial_observation=normalized,
        )

    def describe_capabilities(
        self,
        session: SessionHandle,
        refresh: bool = False,
    ) -> CapabilityDescriptor:
        del session, refresh
        planner_summary = (
            "You are operating a text-command environment backend. "
            "You can send one natural-language environment command per step, "
            "request describe_capabilities to see this summary again, "
            "and inspect the returned text/state summary after each command."
        )
        return CapabilityDescriptor(
            planner_summary=planner_summary,
            operator_context={
                "translation_mode": "transparent_command",
                "supported_call_kinds": ["send_command"],
            },
            raw={"backend_type": self.backend_type},
        )

    def execute(
        self,
        session: SessionHandle,
        request: ExecutionRequest,
    ) -> BackendExecutionResult:
        attempt = ExecutionAttempt(
            attempt=1,
            translated_calls=request.calls,
            final_status="failed",
        )
        if not request.calls:
            observation = Observation(
                success=False,
                message="Operator produced no executable calls.",
                state={},
                summary="No executable calls were produced for this step.",
                env_state={},
                execution={
                    "attempts": [self._attempt_to_dict(attempt)],
                    "diagnostics": {"error": "empty_execution_request"},
                    "suspected_origin": "execution",
                },
            )
            attempt.error = "empty_execution_request"
            attempt.suspected_origin = "execution"
            return BackendExecutionResult(
                observation=observation,
                attempts=[attempt],
                diagnostics={"error": "empty_execution_request"},
            )

        call = request.calls[0]
        try:
            payload = self._client.send_command(session.session_id, call.text)
        except Exception as exc:  # noqa: BLE001
            attempt.error = str(exc)
            attempt.suspected_origin = "execution"
            observation = Observation(
                success=False,
                message=str(exc),
                state={},
                summary=f"Execution failure while sending command: {exc}",
                env_state={},
                execution={
                    "attempts": [self._attempt_to_dict(attempt)],
                    "diagnostics": {"error": str(exc), "backend_type": self.backend_type},
                    "suspected_origin": "execution",
                },
            )
            return BackendExecutionResult(
                observation=observation,
                attempts=[attempt],
                diagnostics={"error": str(exc), "backend_type": self.backend_type},
            )

        attempt.per_call_results = [{"kind": call.kind, "success": True}]
        attempt.success = bool(payload.get("success", False))
        attempt.final_status = "completed" if attempt.success else "environment_failure"
        if not attempt.success:
            attempt.suspected_origin = "environment"
        normalized = self._normalize_payload(
            payload,
            execution={
                "attempts": [self._attempt_to_dict(attempt)],
                "diagnostics": {
                    "backend_type": self.backend_type,
                    "request_type": request.request_type,
                },
                **(
                    {"suspected_origin": "environment"}
                    if not attempt.success
                    else {}
                ),
            },
        )
        return BackendExecutionResult(
            observation=normalized,
            attempts=[attempt],
            diagnostics={"backend_type": self.backend_type},
        )

    def close_session(self, session: SessionHandle) -> None:
        del session
        self._client.close()

    def _normalize_payload(
        self,
        payload: Dict[str, Any],
        *,
        execution: Dict[str, Any],
    ) -> Observation:
        enriched = dict(payload)
        enriched["summary"] = ObservationParser.build_api_summary(payload)
        enriched["env_state"] = payload.get("state") or {}
        enriched["execution"] = execution
        return self._parser.parse(enriched)

    @staticmethod
    def _attempt_to_dict(attempt: ExecutionAttempt) -> Dict[str, Any]:
        payload = {
            "attempt": attempt.attempt,
            "translated_calls": [
                {
                    "kind": call.kind,
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


def resolve_backend_spec(config: Config) -> ExecutionBackendSpec:
    """Resolve the backend type and settings from configuration."""
    section = config.get_section("interaction")
    adapters = section.get("adapters", {})
    if not isinstance(adapters, dict):
        adapters = {}
    backend_type = str(section.get("primary", "api")).strip() or "api"
    primary_mode = normalize_interaction_mode(
        section.get("primary_mode") or interaction_mode_for_backend_type(backend_type)
    )
    if primary_mode == "default":
        primary_mode = interaction_mode_for_backend_type(backend_type)
    enabled_modes_raw = section.get("enabled_modes", [])
    if not isinstance(enabled_modes_raw, list):
        enabled_modes_raw = []
    enabled_modes = [
        normalize_interaction_mode(item)
        for item in enabled_modes_raw
        if normalize_interaction_mode(item) != "default"
    ]
    if not enabled_modes:
        enabled_modes = [primary_mode]
    if primary_mode not in enabled_modes:
        enabled_modes = [primary_mode, *enabled_modes]
    enabled_backends = [
        backend_type_for_interaction_mode(mode)
        for mode in enabled_modes
    ]
    settings = adapters.get(backend_type, {})
    if not isinstance(settings, dict):
        settings = {}
    return ExecutionBackendSpec(
        backend_type=backend_type,
        settings=settings,
        adapters=adapters,
        interaction_profile=str(section.get("profile", "")).strip(),
        primary_mode=primary_mode,
        enabled_modes=enabled_modes,
        enabled_backends=enabled_backends,
    )


def build_execution_backend(
    config: Config,
    task_id: str,
    task_config: Dict[str, Any],
) -> ExecutionBackend:
    """Build the configured execution backend."""
    spec = resolve_backend_spec(config)
    if len(spec.enabled_modes) > 1:
        return MultiModeExecutionBackend(
            primary_mode=spec.primary_mode,
            backends_by_mode={
                mode: _build_single_execution_backend(
                    backend_type_for_interaction_mode(mode),
                    config,
                    task_id,
                    task_config,
                    spec.adapters.get(backend_type_for_interaction_mode(mode), {}),
                )
                for mode in spec.enabled_modes
            },
        )
    return _build_single_execution_backend(
        spec.backend_type,
        config,
        task_id,
        task_config,
        spec.settings,
    )


def _build_single_execution_backend(
    backend_type: str,
    config: Config,
    task_id: str,
    task_config: Dict[str, Any],
    settings: Dict[str, Any],
) -> ExecutionBackend:
    if not isinstance(settings, dict):
        settings = {}
    if backend_type == "api":
        base_url = str(
            task_config.get("base_url") or settings.get("base_url") or ""
        ).strip()
        if not base_url:
            port = task_config.get("port")
            if port is None:
                raise ValueError(
                    f"api backend for '{task_id}' requires either 'base_url' or 'port'"
                )
            base_url = f"http://localhost:{port}/api/agent"
        client = create_http_environment_action_client(
            EnvironmentClientConfig(
                base_url=base_url,
                timeout=int(
                    settings.get(
                        "timeout",
                        config.get_section("llm").get("timeout", 60),
                    )
                ),
                session_id_field=str(
                    task_config.get("session_id_field")
                    or settings.get("session_id_field")
                    or "session_id"
                ),
                terminal_field=str(
                    task_config.get("terminal_field")
                    or settings.get("terminal_field")
                    or "terminal"
                ),
            )
        )
        return ApiExecutionBackend(client)

    if backend_type == "playwright_mcp":
        from .computeruse.playwright_backend import PlaywrightMcpExecutionBackend

        return PlaywrightMcpExecutionBackend.from_config(
            config=config,
            task_id=task_id,
            task_config=task_config,
            backend_settings=settings,
        )

    if backend_type == "computer_use":
        from .computeruse.cua_backend import CuaComputerUseExecutionBackend

        return CuaComputerUseExecutionBackend.from_config(
            config=config,
            task_id=task_id,
            task_config=task_config,
            backend_settings=settings,
        )

    raise ValueError(f"Unsupported execution backend: {backend_type}")
