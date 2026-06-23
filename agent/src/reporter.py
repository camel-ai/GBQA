"""Reporting utilities for the CAMEL-based QA Agent."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import json

from .types import BugFinding, HookEvent, LifecycleEvent, RunReport, StepRecord


class Reporter:
    """Writes structured logs and reports."""

    def __init__(self, output_dir: str, task_slug: str) -> None:
        self._output_dir = Path(output_dir)
        self._task_slug = task_slug
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._run_dir = self._output_dir / task_slug / timestamp
        self._jsonl_path = self._run_dir / "trace.jsonl"
        self._events: List[Dict[str, Any]] = []
        self._run_dir.mkdir(parents=True, exist_ok=True)

    @property
    def run_dir(self) -> Path:
        """Return the report directory for the current run."""
        return self._run_dir

    def log_step(self, record: StepRecord) -> None:
        summary = record.observation.summary or record.observation.message
        payload = {
            "type": "trace",
            "step": record.step,
            "tool": record.action.tool,
            "planner_action": record.action.command,
            "capability_summary": record.capability_summary,
            "observation_summary": summary,
            "execution": record.observation.execution,
            "text": f"Step {record.step}: {record.action.command} -> {summary}",
        }
        self._events.append(payload)
        self._append_jsonl(payload)
        self._print_step(record)

    def log_lifecycle_event(self, event: LifecycleEvent) -> None:
        payload = {
            "type": "lifecycle",
            **asdict(event),
        }
        self._events.append(payload)
        self._append_jsonl(payload)
        print(
            f"[lifecycle] {event.event}"
            f" step={event.step} trigger={event.trigger} reason={event.reason}"
        )

    def log_hook_event(self, event: HookEvent) -> None:
        payload = {
            "type": "hook",
            **asdict(event),
            "text": (
                f"{event.event_type}: hook={event.hook}"
                f" step={event.step} tool={event.tool}"
            ),
        }
        self._events.append(payload)
        self._append_jsonl(payload)
        print(
            f"[hook:{event.event_type}] {event.hook}"
            f" step={event.step} tool={event.tool}"
        )

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
            f"# QA Agent Report - {report.task_id}",
            "",
            f"Total steps: {len(report.steps)}",
            f"Total bugs: {len(report.bugs)}",
            "",
            "## Bugs",
        ]
        if not report.bugs:
            lines.append("No bugs reported.")
        for bug in report.bugs:
            reproduction = bug.reproduction or bug.evidence.get("reproduction", [])
            lines.extend(
                [
                    f"### {bug.title}",
                    f"- Confidence: {bug.confidence:.2f}",
                    f"- Description: {bug.description}",
                    f"- Expected behavior: {bug.expected_behavior or bug.evidence.get('expected_behavior', '')}",
                    f"- Observed fault: {bug.observed_fault or bug.evidence.get('observed_fault', '')}",
                    f"- Root cause: {bug.root_cause or bug.evidence.get('root_cause', '')}",
                    f"- Pinpoint: {json.dumps(bug.pinpoint or bug.evidence.get('pinpoint', {}), ensure_ascii=False)}",
                    "",
                ]
            )
            if reproduction:
                lines.append("Reproduction:")
                for index, step in enumerate(reproduction, start=1):
                    lines.append(f"{index}. {step}")
                lines.append("")
        if report.lifecycle_events:
            lines.extend(["## Lifecycle", ""])
            for event in report.lifecycle_events:
                lines.append(
                    f"- Step {event.step}: `{event.event}`"
                    f" trigger=`{event.trigger}` reason=`{event.reason}`"
                )
            lines.append("")
        if report.hook_events:
            lines.extend(["## Hooks", ""])
            for event in report.hook_events:
                lines.append(
                    f"- Step {event.step}: `{event.event_type}`"
                    f" hook=`{event.hook}` tool=`{event.tool}`"
                )
            lines.append("")
        lines.extend(["## Step Trace", ""])
        if not report.steps:
            lines.append("No steps recorded.")
        for record in report.steps:
            lines.extend(
                [
                    f"### Step {record.step}",
                    f"- Tool: {record.action.tool}",
                    f"- Action: {record.action.command}",
                    f"- Expected: {record.action.expected_outcome}",
                    f"- Success: {record.observation.success}",
                    "- Feedback:",
                    "```text",
                    record.observation.message or "",
                    "```",
                ]
            )
            if record.notes:
                lines.extend(
                    [
                        "- Notes:",
                        "```text",
                        record.notes,
                        "```",
                    ]
                )
            lines.append("")
        if report.summary:
            lines.extend(["## Summary", report.summary, ""])
        return "\n".join(lines)

    def _print_step(self, record: StepRecord) -> None:
        print(f"\n[step {record.step}]")
        print("[planner.prompt]")
        print(record.planner_prompt)
        print("[planner.output]")
        print(record.planner_output)
        if record.observation.execution:
            print("[operator.execution]")
            print(json.dumps(record.observation.execution, ensure_ascii=False, indent=2))
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
            "task": report.metadata.get("task", {}),
            "summary": report.summary,
            "lifecycle_events": [asdict(event) for event in report.lifecycle_events],
            "hook_events": [asdict(event) for event in report.hook_events],
            "bugs": [asdict(bug) for bug in report.bugs],
            "summaries": [asdict(summary) for summary in report.summaries],
            "steps": [
                {
                    "step": record.step,
                    "planner": {
                        "prompt": record.planner_prompt,
                        "output": record.planner_output,
                        "action": record.action.command,
                        "capability_summary": record.capability_summary,
                    },
                    "environment": {
                        "tool": record.action.tool,
                        "action": record.action.command,
                        "rationale": record.action.rationale,
                        "expected_outcome": record.action.expected_outcome,
                        "feedback": record.observation.message,
                        "summary": record.observation.summary,
                        "success": record.observation.success,
                        "terminal": record.observation.terminal,
                        "state": record.observation.state,
                        "env_state": record.observation.env_state,
                        "artifacts": record.observation.artifacts,
                        "execution": record.observation.execution,
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
