"""Targeted known-bug evaluation for GBQA basic-tier tasks."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from gbqa.protocol.schemas import (
    issue_report_completeness,
    load_issue_reports,
)


EVALUATION_METHOD = "targeted_bug"
RUBRIC_VERSION = "targeted_function_pinpoint_v1"


@dataclass(frozen=True)
class FunctionAnchor:
    """One function-level location touched by the golden patch."""

    file: str
    function: str
    qualified_name: str = ""
    class_name: str = ""
    start_line: int | None = None
    end_line: int | None = None


def evaluate_targeted_bug_report(
    *,
    issue_path: str | Path,
    ground_truth_path: str | Path,
    max_reported_issues: int | None = 1,
) -> dict[str, Any]:
    """Evaluate whether the agent found the single targeted known bug."""

    try:
        issues = load_issue_reports(issue_path)
        target = _load_target_bug(Path(ground_truth_path))
    except Exception as exc:  # noqa: BLE001
        return _error_result(f"{type(exc).__name__}: {exc}")

    report_limit = max(0, int(max_reported_issues or 1))
    evaluated = issues[:report_limit]
    ignored = issues[report_limit:]
    issue = evaluated[0] if evaluated else {}
    completeness = issue_report_completeness(issue) if issue else {
        "complete": False,
        "missing_fields": ["issue"],
    }
    alignment = _evaluate_pinpoint_alignment(issue, target) if issue else {
        "aligned": False,
        "matched_anchor": {},
        "rationale": "No issue report was submitted.",
        "candidate_pinpoint_text": "",
    }
    found = bool(issue) and bool(completeness["complete"]) and bool(alignment["aligned"])
    reward = 1.0 if found else 0.0
    return {
        "evaluation_method": EVALUATION_METHOD,
        "rubric_version": RUBRIC_VERSION,
        "reward": reward,
        "found_target_bug": found,
        "target_bug_id": str(target.get("id", "")),
        "evaluated_issue_count": len(evaluated),
        "ignored_issue_count": len(ignored),
        "total_reported": len(issues),
        "report_complete": bool(completeness["complete"]),
        "missing_report_fields": completeness["missing_fields"],
        "pinpoint_aligned": bool(alignment["aligned"]),
        "details": [
            {
                "issue_index": 0,
                "issue": issue,
                "target": _public_target_payload(target),
                "completeness": completeness,
                "pinpoint_alignment": alignment,
                "verified": found,
            }
        ] if issue else [],
        "ignored_candidates": [
            {
                "issue_index": report_limit + index,
                "title": str(item.get("title", "")),
                "reason": "outside_single_issue_report_budget",
            }
            for index, item in enumerate(ignored)
        ],
    }


def _load_target_bug(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and isinstance(payload.get("target_bug"), dict):
        return dict(payload["target_bug"])
    if isinstance(payload, dict) and isinstance(payload.get("bug"), dict):
        return dict(payload["bug"])
    if isinstance(payload, dict) and isinstance(payload.get("bugs"), list):
        bugs = [item for item in payload["bugs"] if isinstance(item, dict)]
        if bugs:
            return dict(bugs[0])
    if isinstance(payload, dict):
        return dict(payload)
    raise ValueError(f"Ground truth file does not contain a target bug: {path}")


def _public_target_payload(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(target.get("id", "")),
        "hint": str(target.get("hint", "")),
        "expected_behavior": _target_field(target, "expected_behavior"),
        "observed_fault": _target_field(target, "observed_fault"),
        "reproduction": _string_list(
            target.get("reproduction") or target.get("minimal_reproduction")
        ),
        "golden_patch": {
            "functions": [
                asdict(anchor) for anchor in _golden_function_anchors(target)
            ],
        },
    }


def _evaluate_pinpoint_alignment(
    issue: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    anchors = _golden_function_anchors(target)
    candidate_text = _pinpoint_text(issue)
    candidate_functions = _candidate_functions(issue, candidate_text)
    candidate_files = _candidate_files(issue, candidate_text)
    candidate_lines = _candidate_lines(issue)

    best: dict[str, Any] | None = None
    for anchor in anchors:
        function_match = _function_matches(anchor, candidate_functions, candidate_text)
        file_match = _file_matches(anchor.file, candidate_files, candidate_text)
        line_match = _line_matches(anchor, candidate_lines)
        diff_match = _diff_matches(issue, target, anchor)
        aligned = function_match and (file_match or line_match or diff_match)
        if function_match and not best:
            best = _alignment_payload(
                anchor,
                aligned=aligned,
                function_match=function_match,
                file_match=file_match,
                line_match=line_match,
                diff_match=diff_match,
                candidate_text=candidate_text,
            )
        if aligned:
            return _alignment_payload(
                anchor,
                aligned=True,
                function_match=function_match,
                file_match=file_match,
                line_match=line_match,
                diff_match=diff_match,
                candidate_text=candidate_text,
            )

    if best:
        best["rationale"] = (
            "The issue mentions a golden-patch function but does not align to "
            "the corresponding file, changed line range, or patch hunk."
        )
        return best
    return {
        "aligned": False,
        "matched_anchor": {},
        "function_match": False,
        "file_match": False,
        "line_match": False,
        "diff_match": False,
        "candidate_pinpoint_text": candidate_text,
        "rationale": "No reported pinpoint matched a function touched by the golden patch.",
    }


def _alignment_payload(
    anchor: FunctionAnchor,
    *,
    aligned: bool,
    function_match: bool,
    file_match: bool,
    line_match: bool,
    diff_match: bool,
    candidate_text: str,
) -> dict[str, Any]:
    return {
        "aligned": aligned,
        "matched_anchor": asdict(anchor),
        "function_match": function_match,
        "file_match": file_match,
        "line_match": line_match,
        "diff_match": diff_match,
        "candidate_pinpoint_text": candidate_text,
        "rationale": (
            "The issue pinpoint aligns with a function-level golden patch anchor."
            if aligned
            else "The issue pinpoint did not fully align with the golden patch anchor."
        ),
    }


def _golden_function_anchors(target: dict[str, Any]) -> list[FunctionAnchor]:
    patch = target.get("golden_patch", {})
    if not isinstance(patch, dict):
        patch = {}
    raw_functions = patch.get("functions") or target.get("functions") or []
    anchors: list[FunctionAnchor] = []
    for item in raw_functions:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file") or item.get("path") or "").strip()
        function = str(item.get("function") or item.get("name") or "").strip()
        qualified = str(item.get("qualified_name") or "").strip()
        if not function and qualified:
            function = qualified.rsplit(".", maxsplit=1)[-1]
        if not file_path or not function:
            continue
        anchors.append(
            FunctionAnchor(
                file=file_path,
                function=function,
                qualified_name=qualified,
                class_name=str(item.get("class") or item.get("class_name") or "").strip(),
                start_line=_optional_int(item.get("start_line")),
                end_line=_optional_int(item.get("end_line")),
            )
        )
    return anchors


def _pinpoint_text(issue: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("pinpoint", "root_cause"):
        value = issue.get(key)
        parts.append(_stringify(value))
    evidence = issue.get("evidence", {})
    if isinstance(evidence, dict):
        parts.append(_stringify(evidence.get("pinpoint")))
        parts.append(_stringify(evidence.get("root_cause")))
    parts.append(_stringify(issue.get("description")))
    return " ".join(part for part in parts if part).strip()


def _candidate_functions(issue: dict[str, Any], text: str) -> set[str]:
    functions: set[str] = set()
    for payload in _pinpoint_payloads(issue):
        for key in ("function", "function_name", "symbol", "qualified_name", "method"):
            value = payload.get(key)
            if value:
                functions.add(_normalize_symbol(str(value)))
    patterns = [
        r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\bfunction\s+([A-Za-z_][A-Za-z0-9_.]*)\b",
        r"\bmethod\s+([A-Za-z_][A-Za-z0-9_.]*)\b",
        r"\bsymbol\s+([A-Za-z_][A-Za-z0-9_.]*)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            functions.add(_normalize_symbol(match.group(1)))
    return functions


def _candidate_files(issue: dict[str, Any], text: str) -> set[str]:
    files: set[str] = set()
    for payload in _pinpoint_payloads(issue):
        for key in ("file", "path", "file_path", "source_file"):
            value = payload.get(key)
            if value:
                files.add(_normalize_path(str(value)))
    for match in re.finditer(r"[\w./-]+\.(?:py|js|ts|go|rs|c|cc|cpp|h|hpp|java)", text):
        files.add(_normalize_path(match.group(0)))
    return files


def _candidate_lines(issue: dict[str, Any]) -> set[int]:
    lines: set[int] = set()
    for payload in _pinpoint_payloads(issue):
        for key in ("line", "line_number", "start_line"):
            line = _optional_int(payload.get(key))
            if line is not None:
                lines.add(line)
    return lines


def _pinpoint_payloads(issue: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for value in (issue.get("pinpoint"), issue.get("root_cause")):
        if isinstance(value, dict):
            payloads.append(value)
        elif isinstance(value, list):
            payloads.extend(item for item in value if isinstance(item, dict))
    evidence = issue.get("evidence", {})
    if isinstance(evidence, dict):
        for value in (evidence.get("pinpoint"), evidence.get("root_cause")):
            if isinstance(value, dict):
                payloads.append(value)
            elif isinstance(value, list):
                payloads.extend(item for item in value if isinstance(item, dict))
    return payloads


def _function_matches(
    anchor: FunctionAnchor,
    candidate_functions: set[str],
    candidate_text: str,
) -> bool:
    names = {
        _normalize_symbol(anchor.function),
        _normalize_symbol(anchor.qualified_name),
    }
    names.discard("")
    for name in names:
        if name in candidate_functions:
            return True
        short = name.rsplit(".", maxsplit=1)[-1]
        if short and short in candidate_functions:
            return True
    lowered = candidate_text.lower()
    return any(name and name.lower() in lowered for name in names)


def _file_matches(anchor_file: str, candidate_files: set[str], candidate_text: str) -> bool:
    normalized_anchor = _normalize_path(anchor_file)
    anchor_name = Path(normalized_anchor).name
    for candidate in candidate_files:
        if candidate == normalized_anchor or candidate.endswith("/" + normalized_anchor):
            return True
        if normalized_anchor.endswith("/" + candidate):
            return True
        if Path(candidate).name == anchor_name:
            return True
    lowered = candidate_text.lower()
    return normalized_anchor.lower() in lowered or anchor_name.lower() in lowered


def _line_matches(anchor: FunctionAnchor, lines: set[int]) -> bool:
    if anchor.start_line is None or anchor.end_line is None:
        return False
    return any(anchor.start_line <= line <= anchor.end_line for line in lines)


def _diff_matches(
    issue: dict[str, Any],
    target: dict[str, Any],
    anchor: FunctionAnchor,
) -> bool:
    text = _stringify(issue.get("patch") or issue.get("diff"))
    pinpoint = issue.get("pinpoint")
    if isinstance(pinpoint, dict):
        text += "\n" + _stringify(pinpoint.get("patch") or pinpoint.get("diff"))
    if not text.strip():
        return False
    patch = target.get("golden_patch", {})
    if not isinstance(patch, dict):
        return False
    snippets = []
    for hunk in patch.get("hunks", []):
        if not isinstance(hunk, dict):
            continue
        if _normalize_path(str(hunk.get("file", ""))) != _normalize_path(anchor.file):
            continue
        if str(hunk.get("function", "")) not in {
            anchor.function,
            anchor.qualified_name,
        }:
            continue
        snippets.extend(_string_list(hunk.get("removed")))
        snippets.extend(_string_list(hunk.get("added")))
    normalized_text = _normalize_free_text(text)
    return any(_normalize_free_text(snippet) in normalized_text for snippet in snippets)


def _target_field(target: dict[str, Any], key: str) -> str:
    value = target.get(key)
    if value:
        return str(value).strip()
    evidence = target.get("evidence", {})
    if isinstance(evidence, dict) and evidence.get(key):
        return str(evidence[key]).strip()
    return ""


def _stringify(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_symbol(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.]", "", value).strip(".").lower()


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip().lstrip("./").lower()


def _normalize_free_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _error_result(error: str) -> dict[str, Any]:
    return {
        "evaluation_method": EVALUATION_METHOD,
        "rubric_version": RUBRIC_VERSION,
        "reward": 0.0,
        "found_target_bug": False,
        "target_bug_id": "",
        "evaluated_issue_count": 0,
        "ignored_issue_count": 0,
        "total_reported": 0,
        "report_complete": False,
        "missing_report_fields": [],
        "pinpoint_aligned": False,
        "details": [],
        "ignored_candidates": [],
        "error": error,
    }
