"""Reporting utilities for the CAMEL-based QA Agent."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import json

from .types import BugFinding, RunReport, StepRecord


class Reporter:
    """Writes structured logs and reports."""

    def __init__(self, output_dir: str, game_id: str) -> None:
        self._output_dir = Path(output_dir)
        self._game_id = game_id
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._run_dir = self._output_dir / game_id / timestamp
        self._jsonl_path = self._run_dir / "trace.jsonl"
        self._events: List[Dict[str, Any]] = []
        self._run_dir.mkdir(parents=True, exist_ok=True)

    @property
    def run_dir(self) -> Path:
        """Return the report directory for the current run."""
        return self._run_dir

    def log_step(self, record: StepRecord) -> None:
        payload = {
            "type": "trace",
            "step": record.step,
            "text": f"Step {record.step}: {record.action.command} -> {record.observation.message}",
        }
        self._events.append(payload)
        self._append_jsonl(payload)
        self._print_step(record)

    def log_bug(self, bug: BugFinding, step: int) -> None:
        payload = {
            "type": "bug",
            "step": step,
            "title": bug.title,
            "description": bug.description,
            "confidence": bug.confidence,
            "evidence": bug.evidence,
            "tags": bug.tags,
        }
        self._events.append(payload)
        self._append_jsonl(payload)
        self._print_bug(bug)

    def log_summary(self, summary: Dict[str, str], step: int) -> None:
        payload = {"type": "summary", "step": step, "data": summary}
        self._events.append(payload)
        self._append_jsonl(payload)
        self._print_summary(summary, step)

    def write_report(self, report: RunReport) -> Dict[str, str]:
        json_path = self._run_dir / "report.json"
        md_path = self._run_dir / "report.md"
        with open(json_path, "w", encoding="utf-8") as file_handle:
            json.dump(
                self._build_compact_report(report),
                file_handle,
                ensure_ascii=False,
                indent=2,
            )
        with open(md_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(self._format_markdown(report))
        return {"json": str(json_path), "markdown": str(md_path)}

    def _append_jsonl(self, payload: Dict[str, Any]) -> None:
        with open(self._jsonl_path, "a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _format_markdown(self, report: RunReport) -> str:
        lines = [
            f"# QA Agent Report - {report.game_id}",
            "",
            f"Total steps: {len(report.steps)}",
            f"Total bugs: {len(report.bugs)}",
            "",
            "## Bugs",
        ]
        if not report.bugs:
            lines.append("No bugs reported.")
        for bug in report.bugs:
            lines.extend(
                [
                    f"### {bug.title}",
                    f"- Confidence: {bug.confidence:.2f}",
                    f"- Description: {bug.description}",
                    "",
                ]
            )
        if report.summary:
            lines.extend(["## Summary", report.summary, ""])
        return "\n".join(lines)

    def _print_step(self, record: StepRecord) -> None:
        print(f"\n[step {record.step}]")
        print("[planner.prompt]")
        print(record.planner_prompt)
        print("[planner.output]")
        print(record.planner_output)
        if record.reflection_prompt or record.reflection_output:
            print("[reflection.prompt]")
            print(record.reflection_prompt)
            print("[reflection.output]")
            print(record.reflection_output)

    @staticmethod
    def _print_bug(bug: BugFinding) -> None:
        print(f"\n[bug] {bug.title} (conf={bug.confidence:.2f})")
        print(bug.description)

    @staticmethod
    def _print_summary(summary: Dict[str, str], step: int) -> None:
        print(f"\n[summary step {step}]")
        print("[summary.prompt]")
        print(summary.get("prompt", ""))
        print("[summary.output]")
        print(summary.get("output", ""))

    def _build_compact_report(self, report: RunReport) -> Dict[str, Any]:
        summaries_by_step: Dict[int, List[Dict[str, str]]] = {}
        for summary in report.summaries:
            summaries_by_step.setdefault(summary.step, []).append(
                {
                    "prompt": summary.prompt,
                    "output": summary.output,
                }
            )
        return {
            "metadata": report.metadata,
            "llm": report.metadata.get("llm", {}),
            "agent": report.metadata.get("agent", {}),
            "game": report.metadata.get("game", {}),
            "summary": report.summary,
            "bugs": [asdict(bug) for bug in report.bugs],
            "summaries": [asdict(summary) for summary in report.summaries],
            "steps": [
                {
                    "step": record.step,
                    "planner": {
                        "prompt": record.planner_prompt,
                        "output": record.planner_output,
                    },
                    "environment": {
                        "tool": record.action.tool,
                        "action": record.action.command,
                        "rationale": record.action.rationale,
                        "expected_outcome": record.action.expected_outcome,
                        "feedback": record.observation.message,
                        "success": record.observation.success,
                        "game_over": record.observation.game_over,
                        "bug_exist": record.action.bug_exist,
                        "confidence": record.action.confidence,
                        "explanation": record.action.explanation,
                    },
                    "reflection": {
                        "prompt": record.reflection_prompt,
                        "output": record.reflection_output,
                        "notes": record.notes,
                    },
                    "summaries": summaries_by_step.get(record.step, []),
                }
                for record in report.steps
            ],
        }
