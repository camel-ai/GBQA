"""Smoke test for the new planner -> operator -> backend loop on game_client."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.execution_backends import GameClientExecutionBackend
from src.operator import Operator
from src.orchestrator import Orchestrator
from src.types import Action


class FakeGameClient:
    def __init__(self) -> None:
        self.sent_commands = []

    def new_game(self):
        return {
            "game_id": "fake-session",
            "success": True,
            "message": "You are standing in the hall.",
            "state": {"room": {"name": "Hall", "exits": ["north"]}, "inventory": []},
            "turn": 0,
        }

    def send_command(self, game_id, command):  # noqa: ANN001
        self.sent_commands.append((game_id, command))
        return {
            "success": True,
            "message": "You take a careful look around the hall.",
            "state": {"room": {"name": "Hall", "exits": ["north"]}, "inventory": []},
            "turn": 1,
            "game_over": False,
        }

    def get_state(self, game_id):  # noqa: ANN001
        raise AssertionError("get_state should not be called in this smoke test")

    def close(self) -> None:
        return None


class PlannerStub:
    def plan(self, context):  # noqa: ANN001
        del context
        return type(
            "PlanResult",
            (),
            {
                "action": Action(command="look"),
                "prompt": "planner prompt",
                "output": '{"command": "look"}',
                "error": "",
            },
        )()


class DummyAgent:
    def run(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("operator LLM should not run for transparent_command mode")


class DummyLlmClient:
    def create_task_agent(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return DummyAgent()


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
        raise AssertionError("no bugs expected")

    def force_summarize(self, step):  # noqa: ANN001
        return None

    def maybe_summarize(self, step):  # noqa: ANN001
        return None


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
    client = FakeGameClient()
    backend = GameClientExecutionBackend(client)
    operator = Operator(DummyLlmClient(), "unused prompt", max_retries=1)
    memory = MemoryStub()
    orchestrator = Orchestrator(
        game_id="dark-castle",
        execution_backend=backend,
        operator=operator,
        planner=PlannerStub(),
        memory=memory,
        detector=None,
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
    assert client.sent_commands == [("fake-session", "look")]
    assert report.steps[0].observation.summary
    assert memory.steps[0].observation.summary.startswith("You take a careful look")
    print("game_client backend loop smoke test passed")


if __name__ == "__main__":
    main()
