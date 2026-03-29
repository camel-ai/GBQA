"""Smoke test for promoting high-confidence reflection findings into reports."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.orchestrator import Orchestrator
from src.types import BugFinding, Observation


class ReflectionStub:
    def __init__(self, bug_exist: bool, bug_confidence: float, bug_evidence: str) -> None:
        self.bug_exist = bug_exist
        self.bug_confidence = bug_confidence
        self.bug_evidence = bug_evidence
        self.next_check = "look"


def main() -> None:
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._confidence_threshold = 0.7

    first = orchestrator._promote_reflection_bug(
        reflection=ReflectionStub(
            bug_exist=True,
            bug_confidence=0.9,
            bug_evidence="The room description leaks a hidden key before the drawer is opened.",
        ),
        step=4,
        action_command="look",
        observation=Observation(success=True, message="Bedroom description", state={}),
        existing_bugs=[],
    )
    duplicate = orchestrator._promote_reflection_bug(
        reflection=ReflectionStub(
            bug_exist=True,
            bug_confidence=0.92,
            bug_evidence="The room description leaks a hidden key before the drawer is opened.",
        ),
        step=5,
        action_command="look",
        observation=Observation(success=True, message="Bedroom description", state={}),
        existing_bugs=[
            BugFinding(
                title="Reflection-identified gameplay issue",
                description="The room description leaks a hidden key before the drawer is opened.",
                confidence=0.9,
            )
        ],
    )

    assert first is not None
    assert first.title == "Reflection-identified gameplay issue"
    assert first.tags == ["reflection"]
    assert duplicate is None
    print("orchestrator bug promotion smoke test passed")


if __name__ == "__main__":
    main()
