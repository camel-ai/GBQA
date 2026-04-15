"""Smoke tests for log-analysis tool registration and auto-triggering."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.log_analyzer import LogAnalyzer
from src.orchestrator import Orchestrator
from src.tool_registry import (
    ToolInvocationResult,
    ToolRegistry,
    register_game_action_tool,
    register_log_analysis_tool,
)
from src.types import Action, CapabilityDescriptor, Observation, SessionHandle


class BackendStub:
    backend_type = "game_client"

    def start_session(self, run_context):  # noqa: ANN001
        del run_context
        return SessionHandle(
            session_id="game-123",
            backend_type=self.backend_type,
            initial_observation=Observation(
                success=True,
                message="Initial observation",
                state={},
                summary="Initial observation",
                env_state={},
            ),
        )

    def describe_capabilities(self, session, refresh=False):  # noqa: ANN001
        del session, refresh
        return CapabilityDescriptor(
            planner_summary="Use game_action or log_analyze.",
            operator_context={},
        )

    def close_session(self, session):  # noqa: ANN001
        del session
        return None


class RuntimeLogProviderStub:
    def read_debug_logs(self, game_id, clear=False):  # noqa: ANN001
        if clear:
            return {"success": True, "game_id": game_id, "logs": ""}
        return {
            "success": True,
            "game_id": game_id,
            "logs": "[12:00:00.000] ERROR simulated server failure",
        }

    def read_session_log(self, game_id):  # noqa: ANN001
        commands = [
            {
                "turn": 1,
                "command": "look",
                "response": {"success": False, "message": "fail one"},
                "timestamp": "2026-04-13T12:00:00",
                "state_snapshot": {"inventory": ["torch"], "room": "Hall"},
            },
            {
                "turn": 2,
                "command": "look",
                "response": {"success": False, "message": "fail two"},
                "timestamp": "2026-04-13T12:00:01",
                "state_snapshot": {"inventory": ["torch"], "room": "Hall"},
            },
            {
                "turn": 3,
                "command": "look",
                "response": {"success": False, "message": "fail three"},
                "timestamp": "2026-04-13T12:00:02",
                "state_snapshot": {"inventory": ["torch"], "room": "Hall"},
            },
        ]
        return {
            "success": True,
            "game_id": game_id,
            "data": {"commands": commands, "total_turns": 3, "result": "in_progress"},
        }


class MemoryStub:
    def __init__(self) -> None:
        self.steps = []

    def get_long_term_summary(self) -> str:
        return ""

    def get_cross_session_memories(self, query):  # noqa: ANN001
        return []

    def get_recent_trace(self) -> str:
        return ""

    def record_step(self, record):  # noqa: ANN001
        self.steps.append(record)

    def record_bug(self, bug, step):  # noqa: ANN001
        raise AssertionError("log-analysis smoke tests should not promote bugs")

    def force_summarize(self, step):  # noqa: ANN001
        return None

    def maybe_summarize(self, step):  # noqa: ANN001
        return None


class DetectorStub:
    def inspect(self, action, observation):  # noqa: ANN001
        return []

    def is_benign_failure(self, observation):  # noqa: ANN001
        return False


class ReporterStub:
    def log_step(self, record):  # noqa: ANN001
        return None

    def log_bug(self, bug, step):  # noqa: ANN001
        raise AssertionError("no bug logging expected")

    def log_summary(self, summary, step):  # noqa: ANN001
        raise AssertionError("no summary expected")

    def write_report(self, report):  # noqa: ANN001
        return {}


def _build_registry():
    registry = ToolRegistry()

    def game_action_handler(payload, runtime_context):  # noqa: ANN001
        del runtime_context
        action_text = payload["action"]
        return ToolInvocationResult(
            observation=Observation(
                success=True,
                message=f"Executed {action_text}",
                state={},
                summary=f"Executed {action_text}",
                env_state={},
            )
        )

    register_game_action_tool(registry, game_action_handler)
    register_log_analysis_tool(registry, RuntimeLogProviderStub(), LogAnalyzer())
    return registry


def _run(planner, *, log_analysis_interval=0):
    orchestrator = Orchestrator(
        game_id="dark-castle",
        execution_backend=BackendStub(),
        operator=None,
        tool_registry=_build_registry(),
        planner=planner,
        memory=MemoryStub(),
        detector=DetectorStub(),
        reporter=ReporterStub(),
        evaluator=None,
        max_steps=1,
        reflection_analyzer=None,
        reflection_threshold=3,
        max_consecutive_failures=5,
        confidence_threshold=0.7,
        reflection_interval=10,
        log_analysis_interval=log_analysis_interval,
        summary_interval=40,
    )
    return orchestrator.run("Text adventure")


def main() -> None:
    explicit_planner = type(
        "PlannerStub",
        (),
        {
            "plan": lambda self, context: type(  # noqa: ARG005
                "PlanResult",
                (),
                {
                    "action": Action(tool="log_analyze", command="failures"),
                    "prompt": "planner prompt",
                    "output": '{"tool":"log_analyze","action":"failures"}',
                    "error": "",
                },
            )(),
        },
    )()
    explicit_report = _run(explicit_planner)
    explicit_summary = explicit_report.steps[0].observation.summary
    assert "Log analysis result:" in explicit_summary
    assert "Filtered commands" in explicit_summary

    auto_planner = type(
        "PlannerStub",
        (),
        {
            "plan": lambda self, context: type(  # noqa: ARG005
                "PlanResult",
                (),
                {
                    "action": Action(tool="game_action", command="look"),
                    "prompt": "planner prompt",
                    "output": '{"tool":"game_action","action":"look"}',
                    "error": "",
                },
            )(),
        },
    )()
    auto_report = _run(auto_planner, log_analysis_interval=1)
    assert "[Auto log analysis]" in auto_report.steps[0].notes
    assert "Log analysis result:" in auto_report.steps[0].notes
    print("log analysis smoke tests passed")


if __name__ == "__main__":
    main()
