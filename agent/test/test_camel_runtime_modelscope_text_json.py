"""Smoke test for ModelScope text-JSON structured output coercion."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.camel_runtime import CamelRuntimeConfig, CamelTaskAgent
from src.structured_outputs import PlannerDecision


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
        return FakeResponse(
            """<think>
I should inspect an item first.
</think>
```json
{
  "rationale": "Inspect the available item before moving on.",
  "command": "take matches",
  "expected_outcome": "The inventory should now contain the matches.",
  "bug_exist": false,
  "bug_confidence": 0.0,
  "bug_explanation": ""
}
```"""
        )


def main() -> None:
    agent = CamelTaskAgent.__new__(CamelTaskAgent)
    agent._config = CamelRuntimeConfig(
        model="demo",
        api_key="demo-key",
        model_platform="MODELSCOPE",
        base_url="https://api-inference.modelscope.cn/v1/",
    )
    agent._model_platform = "MODELSCOPE"
    agent._native_structured_output = False
    agent._agent = FakeChatAgent()

    result = agent.run("Plan the next step.", response_format=PlannerDecision)

    assert result.error == ""
    assert result.parsed is not None
    assert result.parsed.command == "take matches"
    assert result.info.get("structured_output_fallback") is True
    assert agent._agent.calls == [
        {"prompt": "Plan the next step.", "response_format": None}
    ]
    assert agent._agent.reset_count == 1
    print("camel runtime modelscope text-json smoke test passed")


if __name__ == "__main__":
    main()
