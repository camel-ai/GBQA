"""Lifecycle hook event support for the QA agent harness."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .types import Action, HookEvent, RunReport, SessionHandle


_DEFAULT_HOOK_POLICY = {
    "enabled": True,
    "run": True,
    "planner": True,
    "tool_calls": True,
    "steps": True,
    "lifecycle": True,
    "bugs": True,
    "summaries": True,
    "coverage_recording": True,
    "artifact_export": True,
    "diagnostics": False,
    "context_injection": False,
}

_HOOK_CATEGORIES = {
    "on_run_start": "run",
    "on_run_end": "run",
    "before_plan": "planner",
    "after_plan": "planner",
    "before_tool_call": "tool_calls",
    "after_tool_call": "tool_calls",
    "after_step": "steps",
    "on_lifecycle_event": "lifecycle",
    "on_bug_reported": "bugs",
    "on_summary_created": "summaries",
    "on_coverage_recorded": "coverage_recording",
    "on_subagent_result": "diagnostics",
    "on_auto_log_analysis": "diagnostics",
    "on_auto_code_lookup": "diagnostics",
}

_READ_TOOL_PREFIXES = ("code_", "log_")
_EDIT_TOOLS = {"code_write_file", "code_restore_file"}
_ENVIRONMENT_TOOLS = {
    "environment_action",
    "terminal_action",
    "api_action",
    "browser_action",
    "computer_action",
}
_LIFECYCLE_TOOLS = {
    "start_session",
    "end_session",
    "new_session",
    "refresh_session",
    "switch_session",
    "list_sessions",
    "end_task",
}


def normalize_hook_policy(
    policy: Optional[Dict[str, Any]],
    *,
    harness_mode: str,
) -> Dict[str, Any]:
    """Normalize hook policy for minimal/full harness modes."""

    normalized = dict(_DEFAULT_HOOK_POLICY)
    if str(harness_mode).strip().lower() == "full":
        normalized.update(
            {
                "diagnostics": True,
                "context_injection": True,
            }
        )
    if policy:
        normalized.update(policy)
    return normalized


def event_type_for_action(action: Optional[Action]) -> str:
    """Return a stable trajectory label for an agent action."""

    if action is None:
        return "Ran"
    tool = str(action.tool or "")
    if tool in _ENVIRONMENT_TOOLS:
        return "Explored"
    if tool in _EDIT_TOOLS:
        return "Edited"
    if tool in _LIFECYCLE_TOOLS:
        return "Lifecycle"
    if tool.startswith(_READ_TOOL_PREFIXES) or tool == "use_skill":
        return "Ran"
    return "Ran"


class HookManager:
    """Emits policy-controlled hook events into the run report and reporter."""

    def __init__(self, policy: Optional[Dict[str, Any]] = None) -> None:
        self._policy = dict(policy or _DEFAULT_HOOK_POLICY)

    @property
    def policy(self) -> Dict[str, Any]:
        return dict(self._policy)

    def enabled(self, hook: str) -> bool:
        if not bool(self._policy.get("enabled", True)):
            return False
        category = _HOOK_CATEGORIES.get(hook, "")
        if not category:
            return True
        return bool(self._policy.get(category, False))

    def emit(
        self,
        *,
        report: RunReport,
        reporter: Any,
        hook: str,
        event_type: str,
        step: int = 0,
        action: Optional[Action] = None,
        session: Optional[SessionHandle] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[HookEvent]:
        if not self.enabled(hook):
            return None
        event = HookEvent(
            hook=hook,
            event_type=event_type,
            step=step,
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool=action.tool if action else "",
            action=action.command if action else "",
            session_id=session.session_id if session else "",
            backend_type=session.backend_type if session else "",
            metadata=dict(metadata or {}),
        )
        report.hook_events.append(event)
        if hasattr(reporter, "log_hook_event"):
            reporter.log_hook_event(event)
        return event


def hook_event_to_dict(event: HookEvent) -> Dict[str, Any]:
    return asdict(event)
