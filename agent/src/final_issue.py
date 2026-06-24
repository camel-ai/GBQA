"""Final targeted issue report generation for GBQA runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import json

from .llm_client import LlmClient
from .structured_outputs import FinalIssueDecision
from .types import RunReport

REPORT_STATUS_COMPLETE = "complete"
REPORT_STATUS_INCOMPLETE = "incomplete"
REPORT_STATUS_INVALID = "invalid"
REQUIRED_FIELDS = (
    "title",
    "description",
    "expected_behavior",
    "observed_fault",
    "reproduction",
    "pinpoint",
)


@dataclass
class FinalIssueResult:
    """Result of the final issue report pass."""

    issue: dict[str, Any]
    report_status: str
    missing_fields: list[str]
    prompt: str = ""
    output: str = ""
    error: str = ""


class FinalIssueReporter:
    """Generate one fixed-format issue report at task exit."""

    def __init__(self, llm_client: LlmClient) -> None:
        self._agent = llm_client.create_task_agent(
            system_prompt=(
                "You are a strict QA report finalizer. Produce one open-source "
                "issue report for the targeted known-bug task using only the "
                "provided instruction, trajectory, hypotheses, and bug drafts. "
                "Do not invent unobserved steps. Return structured JSON only."
            ),
            agent_id="final_issue",
        )

    def finalize(
        self,
        *,
        report: RunReport,
        task_profile: str,
        exit_status: str,
        exit_trigger: str,
        exit_reason: str,
        max_steps: int,
    ) -> FinalIssueResult:
        prompt = _build_prompt(
            report=report,
            task_profile=task_profile,
            exit_status=exit_status,
            exit_trigger=exit_trigger,
            exit_reason=exit_reason,
            max_steps=max_steps,
        )
        response = self._agent.run(prompt, response_format=FinalIssueDecision)
        if response.parsed is None:
            return build_final_issue_payload(
                {},
                explicit_status=REPORT_STATUS_INVALID,
                prompt=prompt,
                output=response.content,
                error=response.error or "invalid_structured_output",
            )
        payload = response.parsed.model_dump()
        return build_final_issue_payload(
            payload,
            explicit_status=payload.get("report_status"),
            prompt=prompt,
            output=response.content,
            error=response.error,
        )


def build_final_issue_payload(
    payload: dict[str, Any],
    *,
    explicit_status: str | None = None,
    prompt: str = "",
    output: str = "",
    error: str = "",
) -> FinalIssueResult:
    """Normalize a finalizer payload and compute its report status."""

    issue = {
        "title": str(payload.get("title", "")).strip(),
        "description": str(payload.get("description", "")).strip(),
        "expected_behavior": str(payload.get("expected_behavior", "")).strip(),
        "observed_fault": str(payload.get("observed_fault", "")).strip(),
        "reproduction": _string_list(payload.get("reproduction")),
        "pinpoint": _pinpoint_payload(payload.get("pinpoint")),
        "root_cause": str(payload.get("root_cause", "")).strip(),
    }
    if not issue["description"]:
        issue["description"] = issue["observed_fault"]

    missing = _missing_fields(issue)
    status = _normalize_report_status(explicit_status)
    if status == REPORT_STATUS_COMPLETE and missing:
        status = REPORT_STATUS_INCOMPLETE
    if status not in {
        REPORT_STATUS_COMPLETE,
        REPORT_STATUS_INCOMPLETE,
        REPORT_STATUS_INVALID,
    }:
        status = REPORT_STATUS_COMPLETE if not missing else REPORT_STATUS_INCOMPLETE
    if error and status == REPORT_STATUS_COMPLETE:
        status = REPORT_STATUS_INVALID
    if status == REPORT_STATUS_INVALID and not missing:
        missing = _string_list(payload.get("missing_fields"))

    issue["report_status"] = status
    issue["missing_fields"] = missing
    return FinalIssueResult(
        issue=issue,
        report_status=status,
        missing_fields=missing,
        prompt=prompt,
        output=output,
        error=error,
    )


def fallback_final_issue_from_report(report: RunReport) -> FinalIssueResult:
    """Build a deterministic final issue from existing bug candidates."""

    if not report.bugs:
        return build_final_issue_payload({})
    bug = report.bugs[0]
    payload = {
        "title": bug.title,
        "description": bug.description,
        "expected_behavior": bug.expected_behavior or bug.evidence.get("expected_behavior", ""),
        "observed_fault": bug.observed_fault or bug.evidence.get("observed_fault", ""),
        "reproduction": bug.reproduction or bug.evidence.get("reproduction", []),
        "pinpoint": bug.pinpoint or bug.evidence.get("pinpoint", {}),
        "root_cause": bug.root_cause or bug.evidence.get("root_cause", ""),
    }
    return build_final_issue_payload(payload)


def final_issue_metadata(result: FinalIssueResult) -> dict[str, Any]:
    """Return JSON-serializable metadata for a final issue result."""

    payload = asdict(result)
    if len(str(payload.get("prompt", ""))) > 12000:
        payload["prompt"] = str(payload["prompt"])[:12000] + "\n...[truncated]"
    if len(str(payload.get("output", ""))) > 12000:
        payload["output"] = str(payload["output"])[:12000] + "\n...[truncated]"
    return payload


def _build_prompt(
    *,
    report: RunReport,
    task_profile: str,
    exit_status: str,
    exit_trigger: str,
    exit_reason: str,
    max_steps: int,
) -> str:
    bug_drafts = [asdict(bug) for bug in report.bugs[:5]]
    trace = [_step_summary(step) for step in report.steps[-60:]]
    context = {
        "task_id": report.task_id,
        "task_profile": task_profile,
        "exit_status": exit_status,
        "exit_trigger": exit_trigger,
        "exit_reason": exit_reason,
        "max_steps": max_steps,
        "hypothesis_summary": report.metadata.get("hypothesis_summary", ""),
        "bug_drafts": bug_drafts,
        "trajectory": trace,
    }
    return (
        "Create the final issue report for this targeted GBQA task.\n\n"
        "Rules:\n"
        "- Output exactly one issue report.\n"
        "- Use only provided evidence; do not invent actions that are not in the trajectory.\n"
        "- If evidence is insufficient, fill known fields, leave unknown fields empty, "
        "set report_status to incomplete, and list missing_fields.\n"
        "- If a bug is reproduced, include concrete reproduction steps from the trajectory.\n"
        "- Pinpoint should be source-based when possible. Prefer locations[] with file "
        "and function/qualified_name, or a minimal patch/diff when you inspected code.\n"
        "- Set report_status to complete only when every required field is non-empty.\n\n"
        "Required fields: title, description, expected_behavior, observed_fault, "
        "reproduction, pinpoint.\n\n"
        "Return ONLY this JSON shape:\n"
        "{\n"
        '  "title": "",\n'
        '  "description": "",\n'
        '  "expected_behavior": "",\n'
        '  "observed_fault": "",\n'
        '  "reproduction": ["step 1", "step 2"],\n'
        '  "pinpoint": {\n'
        '    "locations": [\n'
        '      {"file": "", "class": "", "function": "", "qualified_name": "", "line": null, "rationale": ""}\n'
        '    ],\n'
        '    "patch": "",\n'
        '    "rationale": ""\n'
        "  },\n"
        '  "root_cause": "",\n'
        '  "report_status": "complete|incomplete|invalid",\n'
        '  "missing_fields": []\n'
        "}\n\n"
        "Context:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _step_summary(step: Any) -> dict[str, Any]:
    message = step.observation.message or step.observation.summary or ""
    if len(message) > 1600:
        message = message[:1600] + "\n...[truncated]"
    return {
        "step": step.step,
        "tool": step.action.tool,
        "action": step.action.command,
        "expected_outcome": step.action.expected_outcome,
        "bug_signal": {
            "exists": step.action.bug_exist,
            "confidence": step.action.confidence,
            "explanation": step.action.explanation,
        },
        "success": step.observation.success,
        "observation": message,
    }


def _missing_fields(issue: dict[str, Any]) -> list[str]:
    missing = []
    for field in REQUIRED_FIELDS:
        value = issue.get(field)
        if field == "pinpoint":
            if not _has_pinpoint_locator(value):
                missing.append(field)
            continue
        if value in (None, "", [], {}):
            missing.append(field)
    return missing


def _has_pinpoint_locator(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if not isinstance(value, dict):
        return False
    if _has_patch_text(value):
        return True
    for location in value.get("locations", []):
        if isinstance(location, dict) and _has_location_fields(location):
            return True
    return _has_location_fields(value)


def _has_location_fields(value: dict[str, Any]) -> bool:
    function_keys = ("function", "function_name", "qualified_name", "method", "symbol")
    location_keys = ("file", "path", "file_path", "source_file", "line", "start_line")
    has_function = any(str(value.get(key, "")).strip() for key in function_keys)
    has_location = any(str(value.get(key, "")).strip() for key in location_keys)
    return has_function and has_location


def _has_patch_text(value: dict[str, Any]) -> bool:
    return any(str(value.get(key, "")).strip() for key in ("patch", "diff"))


def _normalize_report_status(value: Any) -> str:
    status = str(value or "").strip().lower().replace("-", "_")
    if status in {
        REPORT_STATUS_COMPLETE,
        REPORT_STATUS_INCOMPLETE,
        REPORT_STATUS_INVALID,
    }:
        return status
    return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _pinpoint_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        return {"summary": value.strip()}
    return {}
