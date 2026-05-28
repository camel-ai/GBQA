"""Export harness-specific outputs into the stable GBQA artifact contract."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from gbqa.protocol.schemas import (
    SCHEMA_VERSION,
    normalize_bug_candidate,
    normalize_step_record,
)


def export_harbor_artifacts(
    *,
    reports_root: str | Path,
    task_id: str,
    out_dir: str | Path,
) -> dict[str, str]:
    """Export the newest harness report into GBQA protocol artifact files."""

    reports_root = Path(reports_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    task_slug = task_id.rsplit("/", maxsplit=1)[-1]
    report_path = _find_latest_report(reports_root, task_slug)
    if report_path is None:
        report = _empty_report(task_id, "No legacy GBQA report was found.")
        source_dir = None
    else:
        with report_path.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
        source_dir = report_path.parent

    bugs = report.get("bugs", [])
    if not isinstance(bugs, list):
        bugs = []
    steps = report.get("steps", [])
    if not isinstance(steps, list):
        steps = []

    run_payload = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "source_report": str(report_path) if report_path else "",
        "metadata": report.get("metadata", {}),
        "summary": report.get("summary", ""),
        "harness": {
            "name": "gbqa-legacy-qa-agent",
            "llm": report.get("llm", {}),
            "agent": report.get("agent", {}),
        },
    }
    bugs_payload = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "bugs": [
            normalize_bug_candidate(bug)
            for bug in bugs
            if isinstance(bug, dict)
        ],
    }

    run_path = out_dir / "run.json"
    bugs_path = out_dir / "bugs.json"
    steps_path = out_dir / "steps.jsonl"
    run_path.write_text(json.dumps(run_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    bugs_path.write_text(json.dumps(bugs_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with steps_path.open("w", encoding="utf-8") as handle:
        for step in steps:
            if isinstance(step, dict):
                handle.write(json.dumps(normalize_step_record(step), ensure_ascii=False) + "\n")

    if source_dir is not None:
        trace_path = source_dir / "trace.jsonl"
        if trace_path.exists():
            shutil.copy2(trace_path, out_dir / "trace.jsonl")
        markdown_path = source_dir / "report.md"
        if markdown_path.exists():
            shutil.copy2(markdown_path, out_dir / "report.md")
        _copy_screenshot_artifacts(report, out_dir / "artifacts")

    return {
        "run": str(run_path),
        "bugs": str(bugs_path),
        "steps": str(steps_path),
    }


def _find_latest_report(reports_root: Path, task_slug: str) -> Path | None:
    task_root = reports_root / task_slug
    if not task_root.exists():
        return None
    reports = sorted(task_root.glob("*/report.json"), key=lambda path: path.stat().st_mtime)
    return reports[-1] if reports else None


def _empty_report(task_id: str, reason: str) -> dict[str, Any]:
    return {
        "metadata": {"export_warning": reason},
        "task": {"id": task_id},
        "summary": "",
        "bugs": [],
        "steps": [],
    }


def _copy_screenshot_artifacts(report: dict[str, Any], artifacts_dir: Path) -> None:
    for step in report.get("steps", []):
        environment = step.get("environment", {}) if isinstance(step, dict) else {}
        artifacts = environment.get("artifacts", {}) if isinstance(environment, dict) else {}
        for screenshot in artifacts.get("screenshots", []) if isinstance(artifacts, dict) else []:
            if not isinstance(screenshot, dict):
                continue
            source = Path(str(screenshot.get("path", "")))
            if source.exists() and source.is_file():
                shutil.copy2(source, artifacts_dir / source.name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export GBQA protocol artifacts")
    parser.add_argument("--reports-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    export_harbor_artifacts(
        reports_root=args.reports_root,
        task_id=args.task_id,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
