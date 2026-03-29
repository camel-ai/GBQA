"""Smoke test for the CAMEL-backed LLM client."""

from __future__ import annotations

import os
import sys

import dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.llm_client import LlmClient


def main() -> None:
    dotenv.load_dotenv()
    client = LlmClient(
        {
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "base_url": os.getenv("OPENAI_BASE_URL", ""),
            "model": os.getenv("OPENAI_MODEL", ""),
        }
    )
    response = client.complete(
        system_prompt="You are a helpful assistant.",
        user_prompt="hello",
        agent_key="api_call_smoke_test",
    )
    print(response.content)


if __name__ == "__main__":
    main()
