"""Smoke test for code-tool routing through ToolRegistry."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.tool_registry import ToolRegistry, register_code_tools, register_game_action_tool
from src.orchestrator import Orchestrator
from src.types import Action, CapabilityDescriptor, Observation, SessionHandle


class BackendStub:
    backend_type = "playwright_mcp"

    def start_session(self, run_context):  # noqa: ANN001
        del run_context
        return SessionHandle(
            session_id="browser-session",
            backend_type=self.backend_type,
            initial_observation=Observation(
                success=True,
                message="Initial browser observation",
                state={},
                summary="Initial browser observation",
                env_state={},
            ),
        )

    def describe_capabilities(self, session, refresh=False):  # noqa: ANN001
        del session, refresh
        return CapabilityDescriptor(
            planner_summary="Use game_action for gameplay.",
            operator_context={},
        )

    def close_session(self, session):  # noqa: ANN001
        return None


class PlannerStub:
    def plan(self, context):  # noqa: ANN001
        del context
        return type(
            "PlanResult",
            (),
            {
                "action": Action(tool="code_read_file", command="game/actions.py:1-2"),
                "prompt": "planner prompt",
                "output": '{"tool":"code_read_file","action":"game/actions.py:1-2"}',
                "error": "",
            },
        )()


class CodeToolProviderStub:
    def list_code_files(self):
        raise AssertionError("unused")

    def read_code_file(self, path, start_line=0, end_line=0):  # noqa: ANN001
        return {
            "success": True,
            "path": path,
            "content": f"{start_line:>4}  def sample():\n{end_line:>4}      return True",
            "start_line": start_line,
            "end_line": end_line,
        }

    def search_code(self, pattern):  # noqa: ANN001
        raise AssertionError("unused")

    def write_code_file(self, path, content="", patch=None):  # noqa: ANN001
        raise AssertionError("unused")

    def restore_code_file(self, path):  # noqa: ANN001
        raise AssertionError("unused")


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
        raise AssertionError("code-tool step should not promote bugs")

    def force_summarize(self, step):  # noqa: ANN001
        return None

    def maybe_summarize(self, step):  # noqa: ANN001
        return None


class DetectorStub:
    def inspect(self, action, observation):  # noqa: ANN001
        raise AssertionError("bug detector should not run for code-tool steps")

    def is_benign_failure(self, observation):  # noqa: ANN001
        return False


class ReporterStub:
    def log_step(self, record):  # noqa: ANN001
        return None

    def log_bug(self, bug, step):  # noqa: ANN001
        raise AssertionError("no bugs expected")

    def log_summary(self, summary, step):  # noqa: ANN001
        raise AssertionError("no summary expected")

    def write_report(self, report):  # noqa: ANN001
        return {}


def main() -> None:
    registry = ToolRegistry()

    def game_action_handler(payload, runtime_context):  # noqa: ANN001
        raise AssertionError("game_action should not be invoked in this smoke test")

    register_game_action_tool(registry, game_action_handler)
    register_code_tools(registry, CodeToolProviderStub())

    memory = MemoryStub()
    orchestrator = Orchestrator(
        game_id="dark-castle",
        execution_backend=BackendStub(),
        operator=None,
        tool_registry=registry,
        planner=PlannerStub(),
        memory=memory,
        detector=DetectorStub(),
        reporter=ReporterStub(),
        evaluator=None,
        max_steps=1,
        reflection_analyzer=None,
        reflection_threshold=3,
        max_consecutive_failures=5,
        confidence_threshold=0.7,
        reflection_interval=10,
        summary_interval=40,
    )

    report = orchestrator.run("Text adventure")
    assert len(report.steps) == 1
    assert report.steps[0].action.tool == "code_read_file"
    assert "Code tool result" in report.steps[0].observation.summary
    assert report.steps[0].observation.env_state == {}
    print("code tool loop smoke test passed")


if __name__ == "__main__":
    main()
