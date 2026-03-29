"""Smoke test for evaluator similarity fallback after model failure."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.evaluator import Evaluator
from src.types import BugFinding


class FailingMatchAgent:
    """Simulates a provider-side structured output failure."""

    def run(self, prompt: str, response_format=None):  # noqa: ANN001
        return type(
            "FailingResponse",
            (),
            {"parsed": None, "error": "'NoneType' object is not iterable"},
        )()


def main() -> None:
    temp_root = Path(ROOT_DIR) / "test" / "_tmp_evaluator_fallback"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    truth_path = temp_root / "dark-castle.json"
    truth_path.write_text(
        json.dumps(
            {
                "game_name": "dark-castle",
                "bugs": [
                    {
                        "id": "BUG-001",
                        "bug_type": "logic error",
                        "difficulty": "easy",
                        "minimal_reproduction": [
                            "Collect any two key fragments.",
                            "Execute `combine`.",
                        ],
                        "observed_fault": (
                            "The player can assemble the complete key with only "
                            "two fragments instead of all three."
                        ),
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    evaluator = Evaluator(str(truth_path), match_threshold=0.1, llm_client=None)
    evaluator._match_agent = FailingMatchAgent()
    result = evaluator.evaluate(
        [
            BugFinding(
                title="Key assembles with only two fragments",
                description=(
                    "Running `combine` after collecting two key fragments produces "
                    "the full key instead of requiring all three fragments."
                ),
                confidence=0.9,
            )
        ]
    )

    assert result.matched == 1
    assert result.details[0].matched is True
    assert result.details[0].rationale.startswith("similarity_fallback:")

    shutil.rmtree(temp_root, ignore_errors=True)
    print("evaluator fallback smoke test passed")


if __name__ == "__main__":
    main()
