"""Smoke test for describe_capabilities on the API backend."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.execution_backends import ApiExecutionBackend
from src.operator import Operator
from src.tool_registry import ToolInvocationResult, ToolRegistry, register_environment_action_tool
from src.types import Action, Observation


class FakeEnvironmentClient:
    def __init__(self) -> None:
        self.sent_commands = []

    def start_session(self):
        return {
            "session_id": "fake-session",
            "success": True,
            "message": "Welcome",
            "state": {},
        }

    def send_command(self, session_id, command):  # noqa: ANN001
        self.sent_commands.append((session_id, command))
        raise AssertionError("describe_capabilities should not hit the command API")

    def get_state(self, session_id):  # noqa: ANN001
        del session_id
        raise AssertionError("unused")

    def close(self) -> None:
        return None


class DummyAgent:
    def run(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("operator LLM should not run for describe_capabilities")


class DummyLlmClient:
    def create_task_agent(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return DummyAgent()


def main() -> None:
    backend = ApiExecutionBackend(FakeEnvironmentClient())
    session = backend.start_session({})
    capability = backend.describe_capabilities(session)
    operator = Operator(DummyLlmClient(), "unused prompt")
    registry = ToolRegistry()

    def handle_environment_action(payload, runtime_context):  # noqa: ANN001
        result = operator.execute(
            action=Action(command=payload["action"], tool="environment_action"),
            current_observation=runtime_context["current_observation"],
            capability=runtime_context["capability"],
            session=runtime_context["session"],
            backend=backend,
        )
        return ToolInvocationResult(
            observation=result.observation,
            refreshed_capability=result.refreshed_capability,
        )

    register_environment_action_tool(registry, handle_environment_action)
    result = registry.invoke(
        "environment_action",
        {"action": "describe_capabilities"},
        {
            "current_observation": Observation(
                success=True,
                message="",
                state={},
                summary="",
            ),
            "capability": capability,
            "session": session,
            "planner_action": Action(command="describe_capabilities", tool="environment_action"),
        },
    )

    assert result.observation.success is True
    assert "text-command environment backend" in result.observation.summary
    print("describe_capabilities smoke test passed")


if __name__ == "__main__":
    main()
