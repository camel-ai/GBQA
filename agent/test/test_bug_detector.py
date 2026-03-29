"""Smoke tests for bug detector failure classification."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.bug_detector import BugDetector
from src.types import Action, Observation


class DummyLlmClient:
    """Placeholder client for detector tests."""

    def create_task_agent(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("LLM analysis should be disabled in this smoke test")


def main() -> None:
    detector = BugDetector(
        llm_client=DummyLlmClient(),
        enable_llm_analysis=False,
        auto_confirm_threshold=0.8,
        rules=["error_message"],
    )

    benign_findings = detector.inspect(
        Action(command="go up"),
        Observation(
            success=False,
            message="The trapdoor is too high to reach. You need something to climb on first.",
            state={},
        ),
    )
    suspicious_findings = detector.inspect(
        Action(command="look"),
        Observation(
            success=False,
            message="Internal server error: undefined room state.",
            state={},
        ),
    )
    empty_message_findings = detector.inspect(
        Action(command="take key"),
        Observation(success=False, message="", state={}),
    )

    assert benign_findings == []
    assert len(suspicious_findings) == 1
    assert suspicious_findings[0].title == "Command triggered system-like failure"
    assert len(empty_message_findings) == 1
    assert empty_message_findings[0].title == "Command failed without explanation"
    print("bug detector smoke test passed")


if __name__ == "__main__":
    main()
