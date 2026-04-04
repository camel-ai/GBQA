"""Smoke test for report.md bug section compatibility."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.reporter import Reporter
from src.types import BugFinding, RunReport


def main() -> None:
    temp_root = Path(ROOT_DIR) / "test" / "_tmp_report"
    shutil.rmtree(temp_root, ignore_errors=True)
    reporter = Reporter(str(temp_root), "dark-castle")
    report = RunReport(
        game_id="dark-castle",
        bugs=[
            BugFinding(
                title="Visible inconsistency",
                description="The room description did not update after dropping the key.",
                confidence=0.9,
            )
        ],
    )
    paths = reporter.write_report(report)
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert "## Bugs" in markdown
    assert "### Visible inconsistency" in markdown
    assert "- Description: The room description did not update after dropping the key." in markdown
    shutil.rmtree(temp_root, ignore_errors=True)
    print("report markdown compatibility smoke test passed")


if __name__ == "__main__":
    main()
