"""Smoke test for planner multimodal input with screenshot artifacts."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

from camel.messages import BaseMessage

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.planner import ActionPlanner
from src.prompts import PromptBundle
from src.structured_outputs import PlannerDecision


class AgentStub:
    def __init__(self) -> None:
        self.last_prompt = None

    def run(self, prompt, response_format=None):  # noqa: ANN001
        self.last_prompt = prompt
        assert response_format is PlannerDecision
        return type(
            "Response",
            (),
            {
                "parsed": PlannerDecision(command="look"),
                "content": '{"command":"look"}',
                "error": "",
            },
        )()


class LlmClientStub:
    def __init__(self) -> None:
        self.agent = AgentStub()

    def create_task_agent(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self.agent


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        screenshot_path = Path(tmpdir) / "observation.png"
        screenshot_path.write_bytes(b"fake-image")

        llm_client = LlmClientStub()
        planner = ActionPlanner(
            llm_client,
            PromptBundle(
                system="system",
                planner="Observation: {current_observation}\nArtifacts: {current_artifacts}",
                reflection="",
                summary="",
                operator="",
            ),
        )
        planner.plan(
            {
                "current_observation": "A screenshot was captured.",
                "current_artifacts": "Attached screenshots: current page",
                "observation_images": [str(screenshot_path)],
            }
        )

        prompt = llm_client.agent.last_prompt
        assert isinstance(prompt, BaseMessage)
        assert prompt.image_list == [str(screenshot_path)]
        assert "Attached screenshots" in (prompt.content or "")
        print("planner multimodal smoke test passed")


if __name__ == "__main__":
    main()
