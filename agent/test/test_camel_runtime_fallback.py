"""Smoke test for CAMEL structured output fallback parsing."""

from __future__ import annotations

import logging
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.camel_runtime import CamelRuntimeConfig, CamelTaskAgent
from src.structured_outputs import PlannerDecision

logging.getLogger("src.camel_runtime").setLevel(logging.CRITICAL + 1)


class FakeMessage:
    def __init__(self, content: str, parsed=None) -> None:  # noqa: ANN001
        self.content = content
        self.parsed = parsed


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.msgs = [FakeMessage(content)]
        self.info = {}


class FakeChatAgent:
    def __init__(self) -> None:
        self.calls = []
        self.reset_count = 0

    def reset(self) -> None:
        self.reset_count += 1

    def step(self, prompt: str, response_format=None):  # noqa: ANN001
        self.calls.append({"prompt": prompt, "response_format": response_format})
        if response_format is not None:
            raise TypeError("'NoneType' object is not iterable")
        return FakeResponse(
            """```json
{
  "rationale": "Refresh the room description.",
  "command": "look",
  "expected_outcome": "See the latest room state.",
  "bug_exist": false,
  "bug_confidence": 0.0,
  "bug_explanation": ""
}
```"""
        )


def main() -> None:
    agent = CamelTaskAgent.__new__(CamelTaskAgent)
    agent._config = CamelRuntimeConfig(model="demo", api_key="demo-key")
    agent._agent = FakeChatAgent()

    result = agent.run("Plan the next step.", response_format=PlannerDecision)

    assert result.error == ""
    assert result.parsed is not None
    assert result.parsed.command == "look"
    assert result.info.get("structured_output_fallback") is True
    assert agent._agent.reset_count == 2
    print("camel runtime fallback smoke test passed")


if __name__ == "__main__":
    main()
