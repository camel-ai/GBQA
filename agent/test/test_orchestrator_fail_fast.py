"""Smoke test for fail-fast planner error handling."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.orchestrator import Orchestrator
from src.types import Action


class PlannerStub:
    def plan(self, context):  # noqa: ANN001
        return type(
            "PlanResult",
            (),
            {
                "action": Action(command="look"),
                "prompt": "planner prompt",
                "output": "",
                "error": "invalid_structured_output",
            },
        )()


class ToolRegistryStub:
    def __init__(self) -> None:
        self.calls = []

    def invoke(self, name, payload):  # noqa: ANN001
        self.calls.append((name, payload))
        if name == "game_new":
            return {
                "game_id": "test-session",
                "success": True,
                "message": "Initial room description",
                "state": {},
            }
        raise AssertionError("game_command should not be invoked after planner error")


class MemoryStub:
    def get_long_term_summary(self) -> str:
        return ""

    def get_cross_session_memories(self, query):  # noqa: ANN001
        return []

    def get_recent_trace(self) -> str:
        return ""


class ReporterStub:
    def log_step(self, record):  # noqa: ANN001
        raise AssertionError("No step should be logged after planner error")

    def log_bug(self, bug, step):  # noqa: ANN001
        raise AssertionError("No bug should be logged after planner error")

    def log_summary(self, summary, step):  # noqa: ANN001
        raise AssertionError("No summary should be logged after planner error")

    def write_report(self, report):  # noqa: ANN001
        return {}


def main() -> None:
    orchestrator = Orchestrator(
        game_id="dark-castle",
        tool_registry=ToolRegistryStub(),
        planner=PlannerStub(),
        memory=MemoryStub(),
        detector=None,
        reporter=ReporterStub(),
        evaluator=None,
        max_steps=5,
        reflection_analyzer=None,
        reflection_threshold=3,
        max_consecutive_failures=5,
        confidence_threshold=0.7,
        reflection_interval=10,
        summary_interval=40,
    )

    report = orchestrator.run("Text adventure test profile")

    assert report.metadata["early_stop_reason"] == "planner_error"
    assert report.metadata["failed_stage"] == "planner"
    assert report.metadata["failed_step"] == 1
    assert report.metadata["llm_error"] == "invalid_structured_output"
    assert report.steps == []
    print("orchestrator fail-fast smoke test passed")


if __name__ == "__main__":
    main()
