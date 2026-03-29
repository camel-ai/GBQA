"""Offline smoke test for CAMEL-backed session memory."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.llm_client import LlmClient
from src.memory import MemoryManager
from src.types import Action, Observation, StepRecord


def main() -> None:
    temp_root = Path(ROOT_DIR) / "test" / "_tmp_memory"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    long_term_path = temp_root / "dark-castle" / "long_term.json"
    long_term_path.parent.mkdir(parents=True, exist_ok=True)
    long_term_path.write_text(
        '["stale summary that should not be loaded by default"]',
        encoding="utf-8",
    )

    llm_client = LlmClient(
        {
            "api_key": "test-key",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "reset_between_turns": True,
        }
    )

    memory = MemoryManager(
        max_short_term=5,
        long_term_path=str(long_term_path),
        llm_client=llm_client,
        auto_summarize=False,
        summary_threshold=3,
        summary_prompt="Summary: {trace}",
        game_id="dark-castle",
        session_id="test-session",
        memory_dir=str(temp_root),
        session_metadata={"test": True},
        cross_session_enabled=False,
        cross_session_top_k=3,
        cross_session_similarity=0.2,
        load_persistent_long_term=False,
    )

    memory.record_step(
        StepRecord(
            step=1,
            action=Action(command="look"),
            observation=Observation(
                success=True,
                message="You are in the hall.",
                state={"room": {"name": "Hall"}},
            ),
        )
    )
    trace = memory.get_recent_trace()
    assert "Step 1: look -> You are in the hall." in trace
    assert memory.get_long_term_summary() == ""
    assert memory.chat_history_path.exists()

    shutil.rmtree(temp_root, ignore_errors=True)
    print("memory smoke test passed")


if __name__ == "__main__":
    main()
