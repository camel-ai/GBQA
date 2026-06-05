"""Execution backend abstractions and built-in implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol
from uuid import uuid4

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
    settings = adapters.get(backend_type, {})
    if not isinstance(settings, dict):
        settings = {}
    return ExecutionBackendSpec(
        backend_type=backend_type,
        settings=settings,
        adapters=adapters,
    )


def build_execution_backend(
    config: Config,
    task_id: str,
    task_config: Dict[str, Any],
) -> ExecutionBackend:
    """Build the configured execution backend."""
    spec = resolve_backend_spec(config)
    if spec.backend_type == "api":
        base_url = str(
            task_config.get("base_url") or spec.settings.get("base_url") or ""
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
                    spec.settings.get(
                        "timeout",
                        config.get_section("llm").get("timeout", 60),
                    )
                ),
                session_id_field=str(
                    task_config.get("session_id_field")
                    or spec.settings.get("session_id_field")
                    or "session_id"
                ),
                terminal_field=str(
                    task_config.get("terminal_field")
                    or spec.settings.get("terminal_field")
                    or "terminal"
                ),
            )
        )
        return ApiExecutionBackend(client)

    if spec.backend_type == "playwright_mcp":
        from .computeruse.playwright_backend import PlaywrightMcpExecutionBackend

        return PlaywrightMcpExecutionBackend.from_config(
            config=config,
            task_id=task_id,
            task_config=task_config,
            backend_settings=spec.settings,
        )

    if spec.backend_type == "computer_use":
        from .computeruse.cua_backend import CuaComputerUseExecutionBackend

        return CuaComputerUseExecutionBackend.from_config(
            config=config,
            task_id=task_id,
            task_config=task_config,
            backend_settings=spec.settings,
        )

    raise ValueError(f"Unsupported execution backend: {spec.backend_type}")
