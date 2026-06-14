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
                "step": 1,
                "command": "look",
                "response": {"success": False, "message": "fail one"},
                "timestamp": "2026-04-13T12:00:00",
                "state_snapshot": {"inventory": ["torch"], "room": "Hall"},
            },
            {
                "step": 2,
                "command": "look",
                "response": {"success": False, "message": "fail two"},
                "timestamp": "2026-04-13T12:00:01",
                "state_snapshot": {"inventory": ["torch"], "room": "Hall"},
            },
            {
                "step": 3,
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
            session={"commands": commands, "total_steps": 3, "result": "in_progress"},
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
    result = registry.invoke_internal(
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

    registry.invoke("use_skill", {"skill": "logs"}, {})
    result = registry.invoke("log_list", {}, {})

    assert result.observation.success is True
    assert "stdout_stderr" in result.observation.summary
    assert "software_session_logs" in result.observation.summary


def test_log_skill_uses_progressive_disclosure() -> None:
    registry = ToolRegistry()
    register_environment_action_tool(
        registry,
        lambda payload, runtime: ToolInvocationResult(  # noqa: ARG005
            observation=Observation(
                success=True,
                message="ok",
                state={},
                summary="ok",
                env_state={},
            )
        ),
    )
    register_log_tools(registry, [AgentTrajectoryLogSource()], LogAnalyzer())

    initial_prompt = registry.render_prompt_section()

    assert "environment_action" in initial_prompt
    assert "use_skill" in initial_prompt
    assert "Available Skills" in initial_prompt
    assert "- logs:" in initial_prompt
    assert "SKILL.md:" in initial_prompt
    assert "log_analyze" not in initial_prompt
    assert "Available log sources may include" not in initial_prompt

    try:
        registry.parse_action("log_analyze", "analyze")
    except KeyError as exc:
        assert "not currently visible" in str(exc)
    else:
        raise AssertionError("log_analyze should be hidden until logs skill is opened")

    opened = registry.invoke("use_skill", {"skill": "logs"}, {})

    assert opened.observation.success is True
    assert "logs" in opened.observation.summary
    assert "SKILL.md instructions" in opened.observation.summary
    expanded_prompt = registry.render_prompt_section()
    assert "log_list" in expanded_prompt
    assert "log_read" in expanded_prompt
    assert "log_analyze" in expanded_prompt
    assert "Activated Skill Instructions" in expanded_prompt
    assert "Available log sources may include" in expanded_prompt
    assert registry.parse_action("log_analyze", "analyze") == {
        "include_debug_output": True
    }


def test_disabled_skill_tools_are_never_visible() -> None:
    registry = ToolRegistry()
    register_environment_action_tool(
        registry,
        lambda payload, runtime: ToolInvocationResult(  # noqa: ARG005
            observation=Observation(
                success=True,
                message="ok",
                state={},
                summary="ok",
                env_state={},
            )
        ),
    )

    prompt = registry.render_prompt_section()

    assert "Available Skills" not in prompt
    assert "code:" not in prompt
    assert "code_search" not in prompt


def test_code_skill_uses_progressive_disclosure() -> None:
    registry = ToolRegistry()
    register_code_tools(registry, CodeToolAdapterStub())

    initial_prompt = registry.render_prompt_section()

    assert "use_skill" in initial_prompt
    assert "- code:" in initial_prompt
    assert "code_search" not in initial_prompt
    assert "Prefer read-only actions first" not in initial_prompt

    registry.invoke("use_skill", {"skill": "code"}, {})
    expanded_prompt = registry.render_prompt_section()

    assert "code_list_files" in expanded_prompt
    assert "code_read_file" in expanded_prompt
    assert "code_search" in expanded_prompt
    assert "Prefer read-only actions first" in expanded_prompt


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
    assert "1-step session" in report.steps[0].notes


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
    test_log_skill_uses_progressive_disclosure()
    test_disabled_skill_tools_are_never_visible()
    test_code_skill_uses_progressive_disclosure()
    test_auto_log_analysis_receives_agent_steps_for_non_api_backend()

    class ExplicitPlanner:
        def __init__(self) -> None:
            self.calls = 0

        def plan(self, context):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                assert "log_analyze" not in context["available_tools_prompt_section"]
                return type(
                    "PlanResult",
                    (),
                    {
                        "action": Action(tool="use_skill", command="logs"),
                        "prompt": "planner prompt",
                        "output": '{"tool":"use_skill","action":"logs"}',
                        "error": "",
                    },
                )()
            assert "log_analyze" in context["available_tools_prompt_section"]
            return type(
                "PlanResult",
                (),
                {
                    "action": Action(tool="log_analyze", command="failures"),
                    "prompt": "planner prompt",
                    "output": '{"tool":"log_analyze","action":"failures"}',
                    "error": "",
                },
            )()

    explicit_report = _run(ExplicitPlanner(), max_steps=2)
    explicit_summary = explicit_report.steps[1].observation.summary
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
