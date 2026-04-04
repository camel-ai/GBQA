"""Execution backend abstractions and built-in implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol
from uuid import uuid4

from .config import Config
from .game_clients import GameClient, GameClientConfig, create_http_game_client
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
        """Create a run-bound backend session."""

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
        """Close backend resources for the given session."""


@dataclass(frozen=True)
class ExecutionBackendSpec:
    """Resolved backend construction metadata."""

    backend_type: str
    settings: Dict[str, Any]


class GameClientExecutionBackend:
    """ExecutionBackend adapter for the legacy HTTP GameClient."""

    backend_type = "game_client"

    def __init__(self, client: GameClient) -> None:
        self._client = client
        self._parser = ObservationParser()

    def start_session(self, run_context: Dict[str, Any]) -> SessionHandle:
        payload = self._client.new_game()
        normalized = self._normalize_payload(
            payload,
            execution={
                "attempts": [],
                "diagnostics": {"backend_type": self.backend_type},
                "suspected_origin": "environment",
            },
        )
        return SessionHandle(
            session_id=str(payload.get("game_id", "")) or str(uuid4()),
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
            "You are operating a text-command game backend. "
            "You can send one natural-language game command per step, "
            "request describe_capabilities to see this summary again, "
            "and inspect the returned text/state summary after each command."
        )
        return CapabilityDescriptor(
            planner_summary=planner_summary,
            operator_context={
                "translation_mode": "transparent_command",
                "supported_call_kinds": ["send_game_command"],
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
                    "attempts": [attempt.__dict__],
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
                    "attempts": [attempt.__dict__],
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
        attempt.suspected_origin = "environment"
        normalized = self._normalize_payload(
            payload,
            execution={
                "attempts": [self._attempt_to_dict(attempt)],
                "diagnostics": {
                    "backend_type": self.backend_type,
                    "request_type": request.request_type,
                },
                "suspected_origin": "environment",
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
        enriched["summary"] = ObservationParser.build_game_client_summary(payload)
        enriched["env_state"] = payload.get("state") or {}
        enriched["execution"] = execution
        return self._parser.parse(enriched)

    @staticmethod
    def _attempt_to_dict(attempt: ExecutionAttempt) -> Dict[str, Any]:
        return {
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
            "suspected_origin": attempt.suspected_origin,
            "error": attempt.error,
        }


def resolve_backend_spec(config: Config) -> ExecutionBackendSpec:
    """Resolve the backend type and settings from configuration."""
    section = config.get_section("execution_backend")
    backend_type = str(section.get("type", "game_client")).strip() or "game_client"
    settings = section.get(backend_type, {})
    if not isinstance(settings, dict):
        settings = {}
    return ExecutionBackendSpec(backend_type=backend_type, settings=settings)


def build_execution_backend(
    config: Config,
    game_id: str,
    game_config: Dict[str, Any],
) -> ExecutionBackend:
    """Build the configured execution backend."""
    spec = resolve_backend_spec(config)
    if spec.backend_type == "game_client":
        base_url = game_config.get("base_url") or f"http://localhost:{game_config['port']}/api"
        client = create_http_game_client(
            GameClientConfig(
                base_url=base_url,
                timeout=config.get_section("llm").get("timeout", 60),
            )
        )
        return GameClientExecutionBackend(client)

    if spec.backend_type == "playwright_mcp":
        from .computeruse.playwright_backend import PlaywrightMcpExecutionBackend

        return PlaywrightMcpExecutionBackend.from_config(
            config=config,
            game_id=game_id,
            game_config=game_config,
            backend_settings=spec.settings,
        )

    raise ValueError(f"Unsupported execution backend: {spec.backend_type}")
