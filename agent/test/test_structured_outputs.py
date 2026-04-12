"""Regression checks for structured output coercion."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.structured_outputs import OperatorDecision, PlannerDecision, ReflectionDecision


def main() -> None:
    planner = PlannerDecision.model_validate(
        {
            "action": "look",
            "bug_confidence": "",
        }
    )
    reflection = ReflectionDecision.model_validate(
        {
            "bug_exist": False,
            "bug_confidence": None,
            "bug_evidence": "",
            "next_check": "",
        }
    )
    operator = OperatorDecision.model_validate(
        {
            "calls": [
                {
                    "kind": "click",
                    "ref": "e58",
                    "target": "Start New Game",
                }
            ]
        }
    )

    assert planner.action == "look"
    assert planner.bug_confidence == 0.0
    assert reflection.bug_confidence == 0.0
    assert operator.calls[0].kind == "click"
    assert operator.calls[0].ref == "e58"
    print("structured output coercion smoke test passed")


if __name__ == "__main__":
    main()
