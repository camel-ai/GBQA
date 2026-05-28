"""Smoke tests for provider-neutral LLM reasoning request settings."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.llm_client import DEFAULT_BASE_URL, LlmClient


def main() -> None:
    client = LlmClient(
        {
            "api_key": "test-key",
            "model": "reasoning-model",
            "reasoning": {
                "mode": "enabled",
                "effort": "high",
                "max_tokens": 2048,
            },
        }
    )
    assert client.runtime_config.base_url == DEFAULT_BASE_URL
    assert client.runtime_config.reasoning.mode == "enabled"
    assert client.runtime_config.reasoning.effort == "high"
    assert client.runtime_config.reasoning.max_tokens == 2048

    agent = client.create_task_agent("You are a test agent.")
    request_config = agent._agent.model_backend.model_config_dict
    assert request_config["reasoning_effort"] == "high"
    assert request_config["reasoning"] == {"effort": "high", "max_tokens": 2048}

    no_reasoning = LlmClient(
        {
            "api_key": "test-key",
            "model": "non-reasoning-model",
            "reasoning": {"mode": "disabled"},
        }
    )
    no_reasoning_agent = no_reasoning.create_task_agent("You are a test agent.")
    no_reasoning_config = no_reasoning_agent._agent.model_backend.model_config_dict
    assert "reasoning_effort" not in no_reasoning_config
    assert no_reasoning_config["reasoning"] == {"enabled": False}

    print("llm reasoning config smoke test passed")


if __name__ == "__main__":
    main()
