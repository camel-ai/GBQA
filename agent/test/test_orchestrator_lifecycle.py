"""Smoke tests for task/session lifecycle control."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.orchestrator import Orchestrator
from src.tool_registry import ToolRegistry, register_environment_action_tool
from src.types import Action, CapabilityDescriptor, Observation, SessionHandle


class PlanResult:
    def __init__(self, action: Action) -> None:
        self.action = action
        self.prompt = "planner prompt"
        self.output = "planner output"
        self.error = ""


class PlannerSequence:
    def __init__(self, actions: list[Action]) -> None:
        self._actions = list(actions)

    def plan(self, context):  # noqa: ANN001
        del context
        if self._actions:
            return PlanResult(self._actions.pop(0))
        return PlanResult(Action(command="look"))


class BackendStub:
    backend_type = "api"

    def __init__(self) -> None:
        self.started: list[str] = []
        self.closed: list[str] = []
        self.refreshed: list[str] = []

    def start_session(self, run_context):  # noqa: ANN001
        del run_context
        session_id = f"session-{len(self.started) + 1}"
        self.started.append(session_id)
        return SessionHandle(
            session_id=session_id,
            backend_type=self.backend_type,
            initial_observation=Observation(
                success=True,
                message=f"Initial observation for {session_id}",
                state={},
                summary=f"Initial observation for {session_id}",
            ),
        )

    def close_session(self, session):  # noqa: ANN001
        self.closed.append(session.session_id)

    def describe_capabilities(self, session, refresh: bool = False):  # noqa: ANN001
        if refresh:
            self.refreshed.append(session.session_id)
        return CapabilityDescriptor(
            planner_summary=f"capabilities for {session.session_id}",
        )


class OperatorStub:
    def execute(self, **kwargs):  # noqa: ANN003
        del kwargs
        return type(
            "Result",
            (),
            {
                "observation": Observation(
                    success=True,
                    message="look result",
                    state={},
                    summary="look result",
                )
            },
        )()


class MemoryStub:
    def __init__(self) -> None:
        self.steps = []

    def get_long_term_summary(self) -> str:
        return ""

    def get_recent_trace(self) -> str:
        return ""

    def record_step(self, record):  # noqa: ANN001
        self.steps.append(record)


class ReporterStub:
    def __init__(self) -> None:
        self.steps = []
        self.lifecycle_events = []

    def log_step(self, record):  # noqa: ANN001
        self.steps.append(record)

    def log_lifecycle_event(self, event):  # noqa: ANN001
        self.lifecycle_events.append(event)

    def log_bug(self, bug, step):  # noqa: ANN001
        del bug, step

    def log_summary(self, summary, step):  # noqa: ANN001
        del summary, step

    def write_report(self, report):  # noqa: ANN001
        del report
        return {}


def _run(actions: list[Action], *, max_steps: int):
    registry = ToolRegistry()
    register_environment_action_tool(registry, lambda payload, runtime: None)
    backend = BackendStub()
    reporter = ReporterStub()
    orchestrator = Orchestrator(
        task_id="example-task",
        execution_backend=backend,
        operator=OperatorStub(),
        tool_registry=registry,
        planner=PlannerSequence(actions),
        memory=MemoryStub(),
        detector=None,
        reporter=reporter,
        evaluator=None,
        max_steps=max_steps,
    )
    return orchestrator.run("Generic QA task"), backend, reporter


def test_max_steps_forces_end_task() -> None:
    report, backend, reporter = _run(
        [Action(command="look"), Action(command="look")],
        max_steps=2,
    )

    assert report.metadata["end_trigger"] == "max_steps"
    assert report.metadata["end_reason"] == "max_steps_reached"
    assert backend.started == ["session-1"]
    assert backend.closed == ["session-1"]
    assert report.lifecycle_events[-1].event == "end_task"
    assert report.lifecycle_events[-1].trigger == "max_steps"
    assert reporter.lifecycle_events[-1].event == "end_task"


def test_agent_can_end_task_explicitly() -> None:
    report, backend, _reporter = _run(
        [Action(tool="end_task", command="enough evidence collected")],
        max_steps=5,
    )

    assert report.metadata["end_trigger"] == "agent"
    assert report.metadata["end_reason"] == "enough evidence collected"
    assert backend.closed == ["session-1"]
    assert report.steps[-1].action.tool == "end_task"
    assert report.lifecycle_events[-1].event == "end_task"
    assert report.lifecycle_events[-1].trigger == "agent"


def test_new_session_keeps_previous_session_open() -> None:
    report, backend, _reporter = _run(
        [
            Action(tool="new_session", command="open another exploration path"),
            Action(tool="end_task", command="finished after reset"),
        ],
        max_steps=5,
    )

    assert report.metadata["session_ids"] == ["session-1", "session-2"]
    assert backend.started == ["session-1", "session-2"]
    assert backend.closed == ["session-1", "session-2"]
    assert report.metadata["open_session_ids"] == []
    assert "session-2" in report.steps[0].observation.message
    assert "open_session_ids: ['session-1', 'session-2']" in report.steps[0].observation.message
    assert report.steps[0].observation.state["active_session_id"] == "session-2"
    start_sessions = [
        event for event in report.lifecycle_events if event.event == "start_session"
    ]
    end_sessions = [
        event for event in report.lifecycle_events if event.event == "end_session"
    ]
    assert len(start_sessions) == 2
    assert start_sessions[1].trigger == "agent"
    assert len(end_sessions) == 2
    assert report.metadata["end_trigger"] == "agent"


def test_end_session_only_closes_active_session() -> None:
    report, backend, _reporter = _run(
        [
            Action(tool="new_session", command="open second path"),
            Action(tool="end_session", command="session-1 done with first path"),
            Action(tool="end_task", command="done"),
        ],
        max_steps=5,
    )

    assert backend.started == ["session-1", "session-2"]
    assert backend.closed == ["session-1", "session-2"]
    assert report.metadata["current_session_id"] == ""
    end_sessions = [
        event for event in report.lifecycle_events if event.event == "end_session"
    ]
    assert end_sessions[0].session_id == "session-1"
    assert end_sessions[0].trigger == "agent"


def test_switch_session_changes_active_session() -> None:
    report, backend, _reporter = _run(
        [
            Action(tool="new_session", command="open second path"),
            Action(tool="switch_session", command="session-1"),
            Action(tool="end_task", command="done"),
        ],
        max_steps=5,
    )

    switch_events = [
        event for event in report.lifecycle_events if event.event == "switch_session"
    ]
    assert len(switch_events) == 1
    assert switch_events[0].session_id == "session-1"
    assert "Switched active session to session-1." in report.steps[1].observation.message
    assert "Capability observation:" in report.steps[1].observation.message


def test_refresh_session_records_lifecycle_event() -> None:
    report, backend, _reporter = _run(
        [
            Action(tool="refresh_session", command="session-1"),
            Action(tool="end_task", command="done"),
        ],
        max_steps=5,
    )

    assert backend.refreshed == ["session-1"]
    refresh_events = [
        event for event in report.lifecycle_events if event.event == "refresh_session"
    ]
    assert len(refresh_events) == 1
    assert refresh_events[0].session_id == "session-1"


def test_list_sessions_reports_open_and_active_ids() -> None:
    report, _backend, _reporter = _run(
        [
            Action(tool="new_session", command="open second path"),
            Action(tool="list_sessions", command="check ids"),
            Action(tool="end_task", command="done"),
        ],
        max_steps=5,
    )

    list_step = report.steps[1]
    assert list_step.action.tool == "list_sessions"
    assert list_step.observation.state["active_session_id"] == "session-2"
    assert list_step.observation.state["open_session_ids"] == [
        "session-1",
        "session-2",
    ]
    assert "active_session_id: session-2" in list_step.observation.message


def test_list_sessions_on_first_step_shows_initial_session() -> None:
    report, _backend, _reporter = _run(
        [
            Action(tool="list_sessions", command="inspect"),
            Action(tool="end_task", command="done"),
        ],
        max_steps=5,
    )

    assert report.steps[0].observation.state == {
        "active_session_id": "session-1",
        "open_session_ids": ["session-1"],
    }
    assert "active_session_id: session-1" in report.steps[0].observation.message


def test_lifecycle_skill_is_activated_by_default() -> None:
    registry = ToolRegistry()
    register_environment_action_tool(registry, lambda payload, runtime: None)
    orchestrator = Orchestrator(
        task_id="example-task",
        execution_backend=BackendStub(),
        operator=OperatorStub(),
        tool_registry=registry,
        planner=PlannerSequence([]),
        memory=MemoryStub(),
        detector=None,
        reporter=ReporterStub(),
        evaluator=None,
        max_steps=1,
    )
    orchestrator._ensure_lifecycle_tools()
    visible = {tool.name for tool in registry.list_visible_tools()}
    assert "start_session" in visible
    assert "new_session" in visible
    assert "list_sessions" in visible
    assert "end_task" in visible


def main() -> None:
    test_max_steps_forces_end_task()
    test_agent_can_end_task_explicitly()
    test_new_session_keeps_previous_session_open()
    test_end_session_only_closes_active_session()
    test_switch_session_changes_active_session()
    test_refresh_session_records_lifecycle_event()
    test_list_sessions_reports_open_and_active_ids()
    test_list_sessions_on_first_step_shows_initial_session()
    test_lifecycle_skill_is_activated_by_default()
    print("orchestrator lifecycle tests passed")


if __name__ == "__main__":
    main()
