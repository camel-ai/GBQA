"""Operator layer between planner and execution backends."""

from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any, Dict, List

from .execution_backends import ExecutionBackend
from .llm_client import LlmClient
from .prompts import render_prompt
from .structured_outputs import OperatorDecision
from .types import (
    Action,
    BackendExecutionResult,
    CapabilityDescriptor,
    ExecutionAttempt,
    ExecutionCall,
    ExecutionRequest,
    Observation,
    SessionHandle,
)


class Operator:
    """Translate planner actions into backend execution requests."""

    def __init__(
        self,
        llm_client: LlmClient,
        prompt: str,
        *,
        max_retries: int = 2,
        retryable_error_kinds: List[str] | None = None,
    ) -> None:
        self._prompt = prompt
        self._max_retries = max(0, max_retries)
        self._retryable_error_kinds = set(
            retryable_error_kinds
            or ["tool_not_found", "element_not_found", "timeout", "not_visible"]
        )
        self._agent = llm_client.create_task_agent(
            system_prompt="You are an operator translating semantic actions into executable backend calls.",
            agent_id="operator",
        )

    def execute(
        self,
        *,
        action: Action,
        current_observation: Observation,
        capability: CapabilityDescriptor,
        session: SessionHandle,
        backend: ExecutionBackend,
    ) -> BackendExecutionResult:
        if action.command.strip() == "describe_capabilities":
            return self._describe_capabilities(
                capability=backend.describe_capabilities(session, refresh=True)
            )

        attempts: List[ExecutionAttempt] = []
        retry_reason = ""
        for operator_attempt in range(1, self._max_retries + 2):
            try:
                request = self._build_request(
                    action=action,
                    current_observation=current_observation,
                    capability=capability,
                    retry_reason=retry_reason,
                )
            except OperatorTranslationError as exc:
                attempts.append(
                    self._translation_attempt(
                        operator_attempt=operator_attempt,
                        retry_reason=retry_reason,
                        error_text=str(exc),
                    )
                )
                return self._merge_attempts(
                    self._translation_failure_result(str(exc)),
                    attempts,
                )
            result = backend.execute(session, request)
            attempt = self._coerce_attempt(
                request=request,
                result=result,
                operator_attempt=operator_attempt,
                retry_reason=retry_reason,
            )
            attempts.append(attempt)
            if result.observation.success or not self._should_retry(result):
                return self._merge_attempts(result, attempts)
            retry_reason = self._retry_reason(result)

        return self._merge_attempts(result, attempts)

    def _build_request(
        self,
        *,
        action: Action,
        current_observation: Observation,
        capability: CapabilityDescriptor,
        retry_reason: str,
    ) -> ExecutionRequest:
        translation_mode = str(
            capability.operator_context.get("translation_mode", "")
        ).strip()
        if translation_mode == "transparent_command":
            return ExecutionRequest(
                planner_action=action.command,
                calls=[ExecutionCall(kind="send_game_command", text=action.command)],
                metadata={"translation_mode": translation_mode},
            )

        calls = self._llm_translate(
            planner_action=action.command,
            current_observation=current_observation,
            capability=capability,
            retry_reason=retry_reason,
        )
        if retry_reason and calls and calls[0].kind != "wait":
            calls = [ExecutionCall(kind="wait", duration_ms=500)] + calls
        return ExecutionRequest(
            planner_action=action.command,
            calls=calls,
            metadata={"translation_mode": translation_mode or "llm_first"},
        )

    def _llm_translate(
        self,
        *,
        planner_action: str,
        current_observation: Observation,
        capability: CapabilityDescriptor,
        retry_reason: str,
    ) -> List[ExecutionCall]:
        variables = {
            "planner_action": planner_action,
            "current_observation": current_observation.summary or current_observation.message,
            "operator_context": json.dumps(
                self._build_operator_context(
                    capability=capability,
                    current_observation=current_observation,
                    retry_reason=retry_reason,
                ),
                ensure_ascii=False,
                indent=2,
            ),
        }
        prompt = render_prompt(self._prompt, variables)
        response = self._agent.run(prompt, response_format=OperatorDecision)
        if response.parsed and response.parsed.calls:
            calls = [
                ExecutionCall(
                    kind=item.kind.strip(),
                    ref=item.ref.strip(),
                    target=item.target.strip(),
                    text=item.text.strip(),
                    url=item.url.strip(),
                    duration_ms=int(item.duration_ms),
                )
                for item in response.parsed.calls
            ]
            required_ref_kinds = set(
                capability.operator_context.get("requires_ref_for_kinds", [])
            )
            missing_ref_kinds = [
                item.kind
                for item in calls
                if item.kind in required_ref_kinds and not item.ref.strip()
            ]
            if missing_ref_kinds:
                raise OperatorTranslationError(
                    "Operator translation omitted required refs for call kinds: "
                    + ", ".join(missing_ref_kinds)
                )
            if calls:
                return calls
        error_text = response.error or "invalid_operator_translation"
        raise OperatorTranslationError(
            f"Operator failed to translate planner action '{planner_action}': {error_text}"
        )

    @staticmethod
    def _build_operator_context(
        *,
        capability: CapabilityDescriptor,
        current_observation: Observation,
        retry_reason: str,
    ) -> Dict[str, Any]:
        env_state = current_observation.env_state or {}
        return {
            **capability.operator_context,
            "retry_reason": retry_reason,
            "current_env_state": {
                "status_bar": env_state.get("status_bar", {}),
                "input_enabled": env_state.get("input_enabled", False),
                "actionable_elements": env_state.get("actionable_elements", []),
            },
        }

    def _should_retry(self, result: BackendExecutionResult) -> bool:
        execution = result.observation.execution or {}
        if execution.get("suspected_origin") != "execution":
            return False
        error_kind = self._retry_reason(result)
        return error_kind in self._retryable_error_kinds

    @staticmethod
    def _retry_reason(result: BackendExecutionResult) -> str:
        execution = result.observation.execution or {}
        diagnostics = execution.get("diagnostics", {})
        return str(diagnostics.get("error_kind") or diagnostics.get("error") or "").strip()

    @staticmethod
    def _coerce_attempt(
        *,
        request: ExecutionRequest,
        result: BackendExecutionResult,
        operator_attempt: int,
        retry_reason: str,
    ) -> ExecutionAttempt:
        if result.attempts:
            attempt = result.attempts[0]
            attempt.attempt = operator_attempt
            if retry_reason and not attempt.retry_reason:
                attempt.retry_reason = retry_reason
            return attempt
        observation = result.observation
        execution = observation.execution or {}
        diagnostics = execution.get("diagnostics", {})
        return ExecutionAttempt(
            attempt=operator_attempt,
            translated_calls=request.calls,
            retry_reason=retry_reason,
            success=observation.success,
            final_status="completed" if observation.success else "failed",
            suspected_origin=str(execution.get("suspected_origin", "ambiguous")),
            error=str(diagnostics.get("error", "")),
        )

    def _merge_attempts(
        self,
        result: BackendExecutionResult,
        attempts: List[ExecutionAttempt],
    ) -> BackendExecutionResult:
        result.attempts = attempts
        execution = dict(result.observation.execution or {})
        execution["attempts"] = [self._attempt_to_dict(item) for item in attempts]
        diagnostics = dict(execution.get("diagnostics", {}))
        diagnostics["attempt_count"] = len(attempts)
        execution["diagnostics"] = diagnostics
        if attempts:
            execution["suspected_origin"] = attempts[-1].suspected_origin
        result.observation.execution = execution
        return result

    @staticmethod
    def _translation_attempt(
        *,
        operator_attempt: int,
        retry_reason: str,
        error_text: str,
    ) -> ExecutionAttempt:
        return ExecutionAttempt(
            attempt=operator_attempt,
            translated_calls=[],
            retry_reason=retry_reason,
            success=False,
            final_status="translation_failed",
            suspected_origin="execution",
            error=error_text,
        )

    @staticmethod
    def _translation_failure_result(error_text: str) -> BackendExecutionResult:
        observation = Observation(
            success=False,
            message=error_text,
            state={},
            summary=f"Operator translation failure: {error_text}",
            env_state={},
            artifacts={},
            execution={
                "attempts": [],
                "diagnostics": {
                    "error": error_text,
                    "error_kind": "translation_error",
                },
                "suspected_origin": "execution",
            },
        )
        return BackendExecutionResult(
            observation=observation,
            attempts=[],
            diagnostics={
                "error": error_text,
                "error_kind": "translation_error",
            },
        )

    @staticmethod
    def _describe_capabilities(
        capability: CapabilityDescriptor,
    ) -> BackendExecutionResult:
        observation = Observation(
            success=True,
            message=capability.planner_summary,
            state={},
            summary=capability.planner_summary,
            env_state={},
            artifacts={},
            execution={
                "attempts": [],
                "diagnostics": {"source": "describe_capabilities"},
                "suspected_origin": "environment",
            },
        )
        return BackendExecutionResult(
            observation=observation,
            attempts=[],
            diagnostics={"source": "describe_capabilities"},
            refreshed_capability=capability,
        )

    @staticmethod
    def _attempt_to_dict(attempt: ExecutionAttempt) -> Dict[str, Any]:
        payload = asdict(attempt)
        payload["translated_calls"] = [asdict(item) for item in attempt.translated_calls]
        return payload


class OperatorTranslationError(RuntimeError):
    """Raised when the operator cannot translate a semantic action."""
