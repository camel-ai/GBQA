"""Smoke tests for QA hypothesis, coverage, and tool policy state."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.qa_state import CoverageState, HypothesisManager
from src.tool_registry import ToolRegistry, register_environment_action_tool, register_lifecycle_tools
from src.types import Action, BugFinding, Observation


def test_coverage_tracks_state_frontier() -> None:
    coverage = CoverageState()
    coverage.record(
        step=1,
        action=Action(command="look"),
        observation=Observation(
            success=True,
            message="Hall",
            state={"room": "hall"},
            summary="Hall",
        ),
        session_id="s1",
    )
    coverage.record(
        step=2,
        action=Action(command="open door"),
        observation=Observation(
            success=False,
            message="It is locked.",
            state={"room": "hall"},
            summary="It is locked.",
        ),
        session_id="s1",
    )

    payload = coverage.to_dict()
    assert payload["unique_state_count"] == 1
    assert payload["recorded_action_count"] == 2
    assert payload["recent_failures"][0]["action"] == "open door"
    assert "Observed states: 1" in coverage.summary()


def test_hypothesis_manager_deduplicates_similar_findings() -> None:
    manager = HypothesisManager(confidence_threshold=0.7)
    action = Action(command="look")
    observation = Observation(success=True, message="Hidden key is visible.", state={})
    first = manager.add_from_finding(
        finding=BugFinding(
            title="Hidden key leaked",
            description="The room description leaks a hidden key before opening the drawer.",
            confidence=0.8,
        ),
        step=3,
        action=action,
        observation=observation,
        source="detector",
    )
    second = manager.add_from_finding(
        finding=BugFinding(
            title="Hidden key leaked",
            description="Room text leaks a hidden key before the drawer is opened.",
            confidence=0.9,
        ),
        step=4,
        action=action,
        observation=observation,
        source="reflection",
    )

    assert first.hypothesis_id == second.hypothesis_id
    assert first.status == "reproduced"
    assert len(manager.to_dict()["hypotheses"]) == 1


def test_tool_registry_exports_structured_policy() -> None:
    registry = ToolRegistry()
    register_environment_action_tool(
        registry,
        lambda payload, runtime: (_ for _ in ()).throw(AssertionError()),
    )
    register_lifecycle_tools(registry)
    policy = registry.describe_policy()
    tools = {item["name"]: item for item in policy["tools"]}

    assert tools["environment_action"]["input_schema"]["required"] == ["action"]
    assert tools["environment_action"]["side_effect"] == "environment"
    assert tools["end_task"]["visible"] is True
    assert any(skill["name"] == "lifecycle" and skill["activated"] for skill in policy["skills"])


def main() -> None:
    test_coverage_tracks_state_frontier()
    test_hypothesis_manager_deduplicates_similar_findings()
    test_tool_registry_exports_structured_policy()
    print("qa strategy state tests passed")


if __name__ == "__main__":
    main()
