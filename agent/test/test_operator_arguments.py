"""Smoke tests for operator call arguments."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.operator import Operator
from src.structured_outputs import OperatorCallDecision, OperatorDecision
from src.types import (
    Action,
    BackendExecutionResult,
    CapabilityDescriptor,
    Observation,
    SessionHandle,
)


class AgentStub:
    def __init__(self, decision: OperatorDecision) -> None:
        self._decision = decision

    def run(self, prompt, response_format=None):  # noqa: ANN001
        return type(
            "Response",
            (),
            {
                "parsed": self._decision,
                "content": self._decision.model_dump_json(),
                "error": "",
            },
        )()


class LlmClientStub:
    def __init__(self, decision: OperatorDecision) -> None:
        self._agent = AgentStub(decision)

    def create_task_agent(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self._agent


class BackendStub:
    backend_type = "computer_use"

    def __init__(self) -> None:
        self.calls = []

    def describe_capabilities(self, session, refresh=False):  # noqa: ANN001
        return CapabilityDescriptor(planner_summary="", operator_context={})

    def execute(self, session, request):  # noqa: ANN001
        self.calls = request.calls
        return BackendExecutionResult(
            observation=Observation(
                success=True,
                message="ok",
                state={},
                summary="ok",
                env_state={},
            )
        )


def _capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        planner_summary="",
        operator_context={
            "translation_mode": "llm_first",
            "supported_call_kinds": ["click"],
            "requires_arguments_for_kinds": {"click": ["x", "y"]},
        },
    )


def main() -> None:
    decision = OperatorDecision(
        calls=[OperatorCallDecision(kind="click", arguments={"x": 10, "y": 20})]
    )
    operator = Operator(LlmClientStub(decision), "{planner_action}\n{operator_context}")
    backend = BackendStub()
    result = operator.execute(
        action=Action(command="click the start button"),
        current_observation=Observation(
            success=True,
            message="screen",
            state={},
            summary="screen",
            env_state={},
        ),
        capability=_capability(),
        session=SessionHandle(session_id="s", backend_type="computer_use"),
        backend=backend,
    )
    assert result.observation.success is True
    assert backend.calls[0].arguments == {"x": 10, "y": 20}

    missing = OperatorDecision(calls=[OperatorCallDecision(kind="click")])
    operator = Operator(LlmClientStub(missing), "{planner_action}\n{operator_context}")
    result = operator.execute(
        action=Action(command="click the start button"),
        current_observation=Observation(
            success=True,
            message="screen",
            state={},
            summary="screen",
            env_state={},
        ),
        capability=_capability(),
        session=SessionHandle(session_id="s", backend_type="computer_use"),
        backend=BackendStub(),
    )
    assert result.observation.success is False
    assert "click.x" in result.observation.message
    assert "click.y" in result.observation.message
    print("operator argument smoke test passed")


if __name__ == "__main__":
    main()
