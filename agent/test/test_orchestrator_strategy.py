"""Smoke tests for orchestrator strategy policies."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.orchestrator import Orchestrator
from src.hooks import HookManager
from src.subagents import SubagentResult
from src.tool_registry import ToolRegistry, register_environment_action_tool
from src.types import Action, CapabilityDescriptor, Observation, SessionHandle, SummaryRecord


class PlanResult:
    def __init__(self, action: Action) -> None:
        self.action = action
        self.prompt = "planner prompt"
        self.output = "planner output"
        self.error = ""


class PlannerSequence:
    def __init__(self, actions: list[Action]) -> None:
        self._actions = list(actions)
        self.contexts = []

    def plan(self, context):  # noqa: ANN001
        self.contexts.append(context)
        if self._actions:
            return PlanResult(self._actions.pop(0))
        return PlanResult(Action(command="look"))


class BackendStub:
    backend_type = "api"

    def __init__(self, observations: list[Observation]) -> None:
        self._observations = list(observations)

    def start_session(self, run_context):  # noqa: ANN001
        del run_context
        return SessionHandle(
            session_id="session-1",
            backend_type=self.backend_type,
            initial_observation=Observation(
                success=True,
                message="Initial observation",
                state={},
                summary="Initial observation",
            ),
        )

    def close_session(self, session):  # noqa: ANN001
        del session

    def describe_capabilities(self, session, refresh=False):  # noqa: ANN001
        del session, refresh
        return CapabilityDescriptor(
            planner_summary="command backend",
            operator_context={"translation_mode": "transparent_command"},
        )

    def execute(self, session, request):  # noqa: ANN001
        del session, request
        observation = self._observations.pop(0)
        return type(
            "Result",
            (),
            {
                "observation": observation,
                "refreshed_capability": None,
            },
        )()


class OperatorStub:
    def __init__(self, backend: BackendStub) -> None:
        self._backend = backend

    def execute(self, **kwargs):  # noqa: ANN003
        return self._backend.execute(kwargs["session"], None)


class MemoryStub:
    def __init__(self) -> None:
        self.steps = []
        self.summaries = []

    def get_long_term_summary(self) -> str:
        return ""

    def get_recent_trace(self) -> str:
        return ""

    def record_step(self, record):  # noqa: ANN001
        self.steps.append(record)

    def record_bug(self, bug, step):  # noqa: ANN001
        del bug, step

    def maybe_summarize(self, step):  # noqa: ANN001
        return None

    def force_summarize(self, step):  # noqa: ANN001
        summary = SummaryRecord(step=step, prompt="summary prompt", output=f"summary {step}")
        self.summaries.append(summary)
        return summary


class ReporterStub:
    def __init__(self) -> None:
        self.summaries = []
        self.bugs = []
        self.hooks = []

    def log_step(self, record):  # noqa: ANN001
        del record

    def log_lifecycle_event(self, event):  # noqa: ANN001
        del event

    def log_bug(self, bug, step):  # noqa: ANN001
        self.bugs.append((bug, step))

    def log_summary(self, summary, step):  # noqa: ANN001
        self.summaries.append((summary, step))

    def log_hook_event(self, event):  # noqa: ANN001
        self.hooks.append(event)


class ReflectionResult:
    bug_exist = True
    bug_confidence = 0.9
    bug_evidence = "Inventory duplicates the silver key after taking it once."
    next_check = "look"
    prompt = "reflection prompt"
    output = "reflection output"


class ReflectionAnalyzerStub:
    def reflect(self, context):  # noqa: ANN001
        del context
        return ReflectionResult()

    @staticmethod
    def format_note(result):  # noqa: ANN001
        return result.bug_evidence


class SubagentManagerStub:
    policy = {
        "enabled": True,
        "record_prompts": False,
        "explorer": {"enabled": True, "interval_steps": 1},
        "reproducer": {"enabled": False},
        "log_analyst": {"enabled": False},
        "code_localizer": {"enabled": False},
    }

    def should_run_explorer(self, *, step: int) -> bool:
        return step == 1

    def enabled(self, worker: str) -> bool:
        return False

    def explore(self, *, coverage_summary: str, observation_summary: str):  # noqa: ANN001
        assert "Observed states" in coverage_summary
        assert observation_summary
        return SubagentResult(
            worker="ExplorerAgent",
            summary="Untested locked hallway remains in the frontier.",
            suggestions=["inspect lock"],
            prompt="hidden worker prompt",
            output="hidden worker output",
        )


def _run(
    *,
    actions: list[Action],
    observations: list[Observation],
    max_steps: int = 5,
    reflection_analyzer=None,  # noqa: ANN001
    summary_interval: int = 40,
    max_consecutive_failures: int = 5,
    subagent_manager=None,  # noqa: ANN001
):
    registry = ToolRegistry()
    register_environment_action_tool(registry, lambda payload, runtime: None)
    backend = BackendStub(observations)
    reporter = ReporterStub()
    planner = PlannerSequence(actions)
    orchestrator = Orchestrator(
        task_id="example",
        execution_backend=backend,
        operator=OperatorStub(backend),
        tool_registry=registry,
        planner=planner,
        memory=MemoryStub(),
        detector=None,
        reporter=reporter,
        evaluator=None,
        max_steps=max_steps,
        reflection_analyzer=reflection_analyzer,
        reflection_threshold=3,
        max_consecutive_failures=max_consecutive_failures,
        confidence_threshold=0.7,
        reflection_interval=10,
        summary_interval=summary_interval,
        auto_log_analysis_policy={"enabled": False},
        auto_code_lookup_policy={"enabled": False},
        hook_manager=HookManager(
            {
                "enabled": True,
                "run": True,
                "planner": True,
                "tool_calls": True,
                "steps": True,
                "lifecycle": True,
                "bugs": True,
                "summaries": True,
                "coverage_recording": True,
                "diagnostics": True,
            }
        ),
        subagent_manager=subagent_manager,
    )
    return orchestrator.run("Generic QA task"), planner, reporter


def test_failure_budget_ends_task() -> None:
    report, _planner, _reporter = _run(
        actions=[Action(command="bad one"), Action(command="bad two")],
        observations=[
            Observation(success=False, message="failure one", state={}),
            Observation(success=False, message="failure two", state={}),
        ],
        max_consecutive_failures=2,
    )

    assert report.metadata["end_reason"] == "max_consecutive_failures"
    assert report.metadata["end_trigger"] == "system"
    assert len(report.steps) == 2


def test_summary_interval_records_summary() -> None:
    report, planner, reporter = _run(
        actions=[Action(command="look"), Action(tool="end_task", command="done")],
        observations=[Observation(success=True, message="Hall", state={"room": "hall"})],
        summary_interval=1,
    )

    assert report.summaries
    assert reporter.summaries
    assert "coverage_summary" in planner.contexts[-1]
    assert "hypothesis_summary" in planner.contexts[-1]
    event_types = {event.event_type for event in report.hook_events}
    assert {"RunStarted", "Planned", "Explored", "Lifecycle", "Summarized"} <= event_types
    assert reporter.hooks


def test_reflection_promotes_high_confidence_bug() -> None:
    report, _planner, reporter = _run(
        actions=[
            Action(
                command="take key",
                bug_exist=True,
                confidence=0.9,
                explanation="Taking a key duplicated it.",
            ),
            Action(tool="end_task", command="done"),
        ],
        observations=[
            Observation(
                success=True,
                message="Inventory now contains two silver keys.",
                state={"inventory": ["silver key", "silver key"]},
            )
        ],
        reflection_analyzer=ReflectionAnalyzerStub(),
    )

    assert report.bugs
    assert reporter.bugs
    assert report.metadata["hypotheses"]["hypotheses"]


def test_explorer_subagent_records_isolated_summary() -> None:
    report, planner, _reporter = _run(
        actions=[Action(command="look"), Action(tool="end_task", command="done")],
        observations=[Observation(success=True, message="Hall", state={"room": "hall"})],
        subagent_manager=SubagentManagerStub(),
    )

    assert report.metadata["subagent_results"][0]["worker"] == "ExplorerAgent"
    assert "prompt" not in report.metadata["subagent_results"][0]
    assert "ExplorerAgent" in planner.contexts[-1]["subagent_summary"]
    assert any(
        event.hook == "on_subagent_result"
        and event.metadata["worker"] == "ExplorerAgent"
        for event in report.hook_events
    )


def main() -> None:
    test_failure_budget_ends_task()
    test_summary_interval_records_summary()
    test_reflection_promotes_high_confidence_bug()
    test_explorer_subagent_records_isolated_summary()
    print("orchestrator strategy tests passed")


if __name__ == "__main__":
    main()
