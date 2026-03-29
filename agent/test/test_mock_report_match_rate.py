"""Print the offline similarity baseline for the mock Dark Castle report."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.evaluator import Evaluator
from src.types import BugFinding


def load_bug_findings(report_path: Path) -> list[BugFinding]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    findings = []
    for item in payload.get("bugs", []):
        findings.append(
            BugFinding(
                title=str(item.get("title", "")).strip(),
                description=str(item.get("description", "")).strip(),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                evidence=item.get("evidence", {}) or {},
                tags=item.get("tags", []) or [],
            )
        )
    return findings


def main() -> None:
    report_path = (
        Path(ROOT_DIR) / "test" / "mock_reports" / "dark-castle" / "report.json"
    )
    ground_truth_path = (
        Path(ROOT_DIR)
        / ".."
        / "hub"
        / "dark-castle"
        / "bugs"
        / "dark-castle.json"
    ).resolve()

    evaluator = Evaluator(str(ground_truth_path), match_threshold=0.65, llm_client=None)
    result = evaluator.evaluate(load_bug_findings(report_path))

    output = {
        "report": str(report_path),
        "ground_truth": str(ground_truth_path),
        "precision": result.precision,
        "recall": result.recall,
        "matched": result.matched,
        "predicted_total": result.total_predicted,
        "ground_truth_total": result.total_ground_truth,
        "details": [detail.__dict__ for detail in result.details],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    assert result.total_ground_truth == 3
    assert result.total_predicted == 3


if __name__ == "__main__":
    main()
