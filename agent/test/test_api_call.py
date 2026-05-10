"""Smoke test for the CAMEL-backed LLM client."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.llm_client import LlmClient


def main() -> None:
    dotenv.load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")
    if not os.getenv("API_KEY") or not os.getenv("MODEL_NAME"):
        print("skipped api call smoke test: API_KEY and MODEL_NAME are required")
        return
    client = LlmClient(
        {
            "api_key": os.getenv("API_KEY", ""),
            "base_url": os.getenv("BASE_URL", ""),
            "model": os.getenv("MODEL_NAME", ""),
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
