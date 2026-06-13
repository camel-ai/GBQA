"""Smoke tests for isolated QA worker subagents."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.structured_outputs import ExplorerWorkerDecision
from src.subagents import SubagentManager, normalize_subagent_policy


class AgentStub:
    def __init__(self, owner, agent_id):  # noqa: ANN001
        self._owner = owner
        self._agent_id = agent_id

    def run(self, prompt, response_format=None):  # noqa: ANN001
        self._owner.prompts.append(prompt)
        assert response_format is ExplorerWorkerDecision
        decision = ExplorerWorkerDecision(
            summary="Explore the locked hallway.",
            coverage_gaps=["locked hallway"],
            suggested_actions=["inspect lock"],
            rationale="The state frontier has an untested locked object.",
        )
        return type(
            "Response",
            (),
            {
                "parsed": decision,
                "content": decision.model_dump_json(),
                "error": "",
            },
        )()


class LlmClientStub:
    def __init__(self) -> None:
        self.agent_ids = []
        self.prompts = []

    def create_task_agent(self, system_prompt, *, agent_id=None, **kwargs):  # noqa: ANN001, ANN003
        del system_prompt, kwargs
        self.agent_ids.append(agent_id)
        return AgentStub(self, agent_id)


def test_subagent_manager_uses_fresh_isolated_worker_contexts() -> None:
    llm = LlmClientStub()
    manager = SubagentManager(
        llm_client=llm,
        policy=normalize_subagent_policy(
            {
                "enabled": True,
                "max_prompt_chars": 200,
                "explorer": {"enabled": True, "interval_steps": 1},
                "reproducer": {"enabled": False},
                "log_analyst": {"enabled": False},
                "code_localizer": {"enabled": False},
            },
            harness_mode="full",
        ),
    )

    first = manager.explore(
        coverage_summary="Observed states: 1",
        observation_summary="A locked hallway is visible.",
    )
    second = manager.explore(
        coverage_summary="Observed states: 2",
        observation_summary="The lock is still untested.",
    )

    assert first.worker == "ExplorerAgent"
    assert first.summary == "Explore the locked hallway."
    assert "inspect lock" in first.suggestions
    assert llm.agent_ids == ["subagent.explorer.1", "subagent.explorer.2"]
    assert len(llm.prompts) == 2
    assert second.prompt != first.prompt


def test_minimal_policy_disables_all_subagents() -> None:
    policy = normalize_subagent_policy({"enabled": False}, harness_mode="minimal")

    assert policy["enabled"] is False
    assert policy["explorer"]["enabled"] is False
    assert policy["reproducer"]["enabled"] is False
    assert policy["log_analyst"]["enabled"] is False
    assert policy["code_localizer"]["enabled"] is False


def main() -> None:
    test_subagent_manager_uses_fresh_isolated_worker_contexts()
    test_minimal_policy_disables_all_subagents()
    print("subagent tests passed")


if __name__ == "__main__":
    main()
