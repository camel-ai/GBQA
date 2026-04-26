"""Evaluate reports against ground truth."""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List

import dotenv

from src.config import load_config
from src.evaluator import Evaluator
from src.ground_truth import resolve_ground_truth_path
from src.llm_client import LlmClient
from src.types import BugFinding


def parse_report_bugs(report_path: str) -> List[BugFinding]:
    """Extract bug title and description pairs from ``report.md`` or ``report.json``."""
    bugs: List[BugFinding] = []

    # Handle JSON report files
    if report_path.endswith(".json"):
        with open(report_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        for bug in data.get("bugs", []):
            bugs.append(
                BugFinding(
                    title=bug.get("title", ""),
                    description=bug.get("description", ""),
                    confidence=bug.get("confidence", 0.0),
                )
            )
        return bugs

    # Handle Markdown report files
    current: Dict[str, str] = {}
    in_bugs = False
    with open(report_path, "r", encoding="utf-8") as file_handle:
        for line in file_handle:
            text = line.strip()
            if text.startswith("## Bugs"):
                in_bugs = True
                continue
            if in_bugs and text.startswith("## "):
                break
            if not in_bugs:
                continue
            if text.startswith("### "):
                if current:
                    bugs.append(
                        BugFinding(
                            title=current.get("title", ""),
                            description=current.get("description", ""),
                            confidence=0.0,
                        )
                    )
                current = {"title": text.replace("### ", "", 1).strip(), "description": ""}
                continue
            if text.startswith("- Description:"):
                current["description"] = text.replace("- Description:", "", 1).strip()
    if current:
        bugs.append(
            BugFinding(
                title=current.get("title", ""),
                description=current.get("description", ""),
                confidence=0.0,
            )
        )
    return bugs


def main() -> None:
    dotenv.load_dotenv()
    parser = argparse.ArgumentParser(description="Evaluator for reports")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"),
    )
    parser.add_argument("--report", required=True)
    parser.add_argument("--game", default="dark-castle")
    parser.add_argument("--ground-truth", default=None)
    parser.add_argument("--threshold", type=float, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    llm_config = config.get_section("llm")
    api_key = llm_config.get("api_key") or os.getenv("OPENAI_API_KEY")
    llm_base_url = llm_config.get("base_url") or os.getenv("OPENAI_BASE_URL")
    model = llm_config.get("model") or os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        raise RuntimeError("Missing OPENAI_API_KEY or OPENAI_MODEL")
    llm_client = LlmClient(
        {
            **llm_config,
            "api_key": api_key,
            "base_url": llm_base_url,
            "model": model,
        }
    )

    evaluator = Evaluator(
        ground_truth_path=resolve_ground_truth_path(config, args.game, args.ground_truth),
        match_threshold=(
            args.threshold
            if args.threshold is not None
            else config.get_section("evaluation").get("llm_threshold", 0.6)
        ),
        llm_client=llm_client,
    )

    result = evaluator.evaluate(parse_report_bugs(args.report))
    print(
        json.dumps(
            {
                "precision": result.precision,
                "recall": result.recall,
                "matched": result.matched,
                "predicted_total": result.total_predicted,
                "ground_truth_total": result.total_ground_truth,
                "details": [detail.__dict__ for detail in result.details],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
