"""Smoke tests for log-analysis tool registration and auto-triggering."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.log_analyzer import LogAnalyzer
from src.log_sources import (
    AgentTrajectoryLogSource,
    FileDirectoryRuntimeLogSource,
    FileRuntimeLogSource,
    LogReadResult,
    LogSourceSpec,
)
from src.orchestrator import Orchestrator
from src.tool_registry import (
    ToolInvocationResult,
    ToolRegistry,
    register_code_tools,
    register_environment_action_tool,
    register_log_tools,
)
from src.types import Action, CapabilityDescriptor, Observation, SessionHandle, StepRecord


class BackendStub:
    backend_type = "api"

    def start_session(self, run_context):  # noqa: ANN001
        del run_context
        return SessionHandle(
            session_id="session-123",
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
            planner_summary="Use environment_action or log_analyze.",
            operator_context={},
        )

    def close_session(self, session):  # noqa: ANN001
        del session
        return None


class SessionLogSourceStub:
    spec = LogSourceSpec(
        name="test_session_log",
        kind="test",
        description="Static session log for log-analysis tests.",
    )

    def read(self, runtime_context=None):  # noqa: ANN001
        del runtime_context
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
        return LogReadResult(
            name=self.spec.name,
            kind=self.spec.kind,
            success=True,
            text="[12:00:00.000] ERROR simulated server failure",
            session={"commands": commands, "total_turns": 3, "result": "in_progress"},
        )


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


class CodeToolAdapterStub:
    def list_code_files(self):
        return {"success": True, "files": [{"path": "app.py"}]}

    def read_code_file(self, path, start_line=0, end_line=0):  # noqa: ANN001
        return {"success": True, "path": path, "content": "print('ok')"}

    def search_code(self, pattern):  # noqa: ANN001
        return {"success": True, "matches": [{"path": "app.py", "line": 1, "text": pattern}]}

    def write_code_file(self, path, content="", patch=None):  # noqa: ANN001
        return {"success": True, "path": path, "message": "written"}

    def restore_code_file(self, path):  # noqa: ANN001
        return {"success": True, "path": path, "message": "restored"}


def _build_registry():
    registry = ToolRegistry()

    def environment_action_handler(payload, runtime_context):  # noqa: ANN001
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

    register_environment_action_tool(registry, environment_action_handler)
    register_log_tools(registry, [SessionLogSourceStub()], LogAnalyzer())
    return registry


def test_log_analyze_works_from_agent_trajectory_without_api_adapter() -> None:
    registry = ToolRegistry()
    register_log_tools(registry, [AgentTrajectoryLogSource()], LogAnalyzer())

    steps = [
        StepRecord(
            step=1,
            action=Action(tool="environment_action", command="look"),
            observation=Observation(
                success=False,
                message="fail one",
                state={},
                summary="fail one",
                env_state={},
            ),
        )
    ]
    result = registry.invoke(
        "log_analyze",
        {"include_debug_output": True},
        {"steps": steps},
    )

    assert result.observation.success is True
    assert "Log analysis result:" in result.observation.summary


def test_log_list_reports_named_runtime_sources() -> None:
    registry = ToolRegistry()
    register_log_tools(
        registry,
        [
            AgentTrajectoryLogSource(),
            FileRuntimeLogSource(
                LogSourceSpec(
                    name="stdout_stderr",
                    kind="file",
                    path="/logs/runtime/dark-castle-server.log",
                    description="Dark Castle backend stdout/stderr.",
                )
            ),
            FileDirectoryRuntimeLogSource(
                LogSourceSpec(
                    name="software_session_logs",
                    kind="file_directory",
                    path="/sandbox/software/dark-castle/.cache/log",
                    glob="game_*.json",
                    description="Dark Castle software-owned per-session JSON logs.",
                )
            ),
        ],
        LogAnalyzer(),
    )

    result = registry.invoke("log_list", {}, {})

    assert result.observation.success is True
    assert "stdout_stderr" in result.observation.summary
    assert "software_session_logs" in result.observation.summary


def test_auto_log_analysis_receives_agent_steps_for_non_api_backend() -> None:
    class NonApiBackendStub(BackendStub):
        backend_type = "computer_use"

    registry = ToolRegistry()

    def environment_action_handler(payload, runtime_context):  # noqa: ANN001
        del payload, runtime_context
        return ToolInvocationResult(
            observation=Observation(
                success=False,
                message="click failed",
                state={},
                summary="click failed",
                env_state={},
            )
        )

    register_environment_action_tool(registry, environment_action_handler)
    register_log_tools(registry, [AgentTrajectoryLogSource()], LogAnalyzer())

    planner = type(
        "PlannerStub",
        (),
        {
            "plan": lambda self, context: type(  # noqa: ARG005
                "PlanResult",
                (),
                {
                    "action": Action(tool="environment_action", command="click start"),
                    "prompt": "planner prompt",
                    "output": '{"tool":"environment_action","action":"click start"}',
                    "error": "",
                },
            )(),
        },
    )()

    orchestrator = Orchestrator(
        task_id="dark-castle",
        execution_backend=NonApiBackendStub(),
        operator=None,
        tool_registry=registry,
        planner=planner,
        memory=MemoryStub(),
        detector=DetectorStub(),
        reporter=ReporterStub(),
        evaluator=None,
        max_steps=1,
        reflection_analyzer=None,
        reflection_threshold=3,
        max_consecutive_failures=2,
        confidence_threshold=0.7,
        reflection_interval=10,
        log_analysis_interval=1,
        summary_interval=40,
    )

    report = orchestrator.run("Desktop QA")

    assert "[Auto log analysis]" in report.steps[0].notes
    assert "1-turn session" in report.steps[0].notes


def _run(planner, *, log_analysis_interval=0, max_steps=1):
    orchestrator = Orchestrator(
        task_id="dark-castle",
        execution_backend=BackendStub(),
        operator=None,
        tool_registry=_build_registry(),
        planner=planner,
        memory=MemoryStub(),
        detector=DetectorStub(),
        reporter=ReporterStub(),
        evaluator=None,
        max_steps=max_steps,
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
    test_log_analyze_works_from_agent_trajectory_without_api_adapter()
    test_log_list_reports_named_runtime_sources()
    test_auto_log_analysis_receives_agent_steps_for_non_api_backend()

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
                    "action": Action(tool="environment_action", command="look"),
                    "prompt": "planner prompt",
                    "output": '{"tool":"environment_action","action":"look"}',
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
