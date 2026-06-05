"""Benchmark task execution orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Type

from .bug_detector import BugDetector
from .evaluator import Evaluator
from .execution_backends import ExecutionBackend
from .memory import MemoryManager
from .operator import Operator
from .planner import ActionPlanner
from .reflection import ReflectionAnalyzer
from .reporter import Reporter
from .tool_registry import ToolRegistry
from .types import (
    Action,
    BugFinding,
    CapabilityDescriptor,
    LifecycleEvent,
    Observation,
    RunReport,
    SessionHandle,
    StepRecord,
)

_LIFECYCLE_SESSION_TOOLS = frozenset(
    {
        "start_session",
        "end_session",
        "new_session",
        "refresh_session",
        "switch_session",
        "list_sessions",
    }
)


class Orchestrator:
    """Orchestrates the multi-step QA exploration loop."""

    def __init__(
        self,
        *,
        task_id: str,
        execution_backend: ExecutionBackend,
        operator: Operator,
        tool_registry: ToolRegistry,
        planner: ActionPlanner,
        memory: MemoryManager,
        detector: Optional[BugDetector] = None,
        reporter: Reporter,
        evaluator: Optional[Evaluator] = None,
        max_steps: int = 50,
        reflection_analyzer: Optional[ReflectionAnalyzer] = None,
        reflection_threshold: int = 3,
        max_consecutive_failures: int = 5,
        confidence_threshold: float = 0.8,
        reflection_interval: int = 10,
        log_analysis_interval: int = 20,
        summary_interval: int = 50,
    ) -> None:
        self._task_id = task_id
        self._execution_backend = execution_backend
        self._operator = operator
        self._tool_registry = tool_registry
        self._planner = planner
        self._memory = memory
        self._detector = detector
        self._reporter = reporter
        self._evaluator = evaluator
        self._max_steps = max_steps
        self._reflection_analyzer = reflection_analyzer
        self._reflection_threshold = reflection_threshold
        self._max_consecutive_failures = max_consecutive_failures
        self._confidence_threshold = confidence_threshold
        self._reflection_interval = reflection_interval
        self._log_analysis_interval = log_analysis_interval
        self._summary_interval = summary_interval

    def run(self, task_profile: str) -> RunReport:
        start = datetime.now(timezone.utc).isoformat()
        self._ensure_lifecycle_tools()
        report = RunReport(
            task_id=self._task_id,
            steps=[],
            bugs=[],
            summaries=[],
            metadata={
                "start_time": start,
                "backend": {"type": self._execution_backend.backend_type},
                "session_ids": [],
                "capability_summary": "",
            },
        )
        self._record_lifecycle_event(
            report,
            event="start_task",
            step=0,
            reason="task loop started",
            trigger="system",
        )

        open_sessions: Dict[str, SessionHandle] = {}
        active_session = self._start_session(
            report=report,
            task_profile=task_profile,
            step=0,
            trigger="system",
            open_sessions=open_sessions,
        )

        # FINAL GUARANTEE: Ensure code skill is registered if we are in a sandbox
        if not self._has_tool("code_read_file"):
            if hasattr(self._execution_backend, "shell") or self._execution_backend.backend_type in {"computer_use", "daytona"}:
                from .codebase_types import UniversalCodebaseAdapter
                from .tool_registry import register_code_tools
                print("[orchestrator] auto-registering 'code' skill for sandbox environment")
                register_code_tools(self._tool_registry, UniversalCodebaseAdapter(shell_client=self._execution_backend))

        # Skill-aware capability rendering
        capability_prompt = self._tool_registry.render_prompt_section()
        
        report.metadata["capability_summary"] = capability_prompt
        current_observation = self._session_aware_observation(
            session=active_session,
            capability_prompt=capability_prompt,
            open_sessions=open_sessions,
            preamble="Harness started the initial session.",
        )
        consecutive_failures = 0
        last_reflection_step = 0
        task_end_reason = ""
        task_end_trigger = ""

        for step in range(1, self._max_steps + 1):
            print(f"\n[step {step}]")
            
            # Re-render prompt section if skills might have changed
            capability_prompt = self._tool_registry.render_prompt_section()
            
            # Use dictionary context aligned with ActionPlanner's internal processing
            # (Matches keys used in src/planner.py and prompts/planner.md)
            plan = self._planner.plan({
                "task_profile": task_profile,
                "current_observation": current_observation.message,
                "memory_summary": self._memory.get_long_term_summary(),
                "recent_trace": self._memory.get_recent_trace(),
                "available_tools_prompt_section": capability_prompt,
                "step": step,
            })

            action = plan.action
            if getattr(plan, "error", ""):
                report.metadata["early_stop_reason"] = "planner_error"
                report.metadata["failed_stage"] = "planner"
                report.metadata["failed_step"] = step
                report.metadata["llm_error"] = plan.error
                task_end_reason = "planner_error"
                task_end_trigger = "system"
                break

            if action.tool == "end_task":
                current_observation = self._lifecycle_observation(
                    action=action,
                    event="end_task",
                    terminal=True,
                )
                record = self._record_step(
                    report=report,
                    step=step,
                    action=action,
                    observation=current_observation,
                    plan=plan,
                    capability_prompt=capability_prompt,
                )
                task_end_reason = self._lifecycle_reason(action) or "agent requested task end"
                task_end_trigger = "agent"
                record.notes = self._append_note(
                    record.notes,
                    "Task ended by planner-selected `end_task`.",
                )
                break

            if action.tool in _LIFECYCLE_SESSION_TOOLS:
                active_session, current_observation, handled = (
                    self._handle_lifecycle_session_tool(
                        action=action,
                        report=report,
                        plan=plan,
                        step=step,
                        task_profile=task_profile,
                        capability_prompt=capability_prompt,
                        open_sessions=open_sessions,
                        active_session=active_session,
                    )
                )
                if handled:
                    consecutive_failures = 0
                    continue

            if active_session is None and action.tool == "environment_action":
                current_observation = Observation(
                    success=False,
                    message="No active session. Use start_session or new_session first.",
                    state={},
                    summary="No active session is available for environment_action.",
                    env_state={},
                )
                self._record_step(
                    report=report,
                    step=step,
                    action=action,
                    observation=current_observation,
                    plan=plan,
                    capability_prompt=capability_prompt,
                )
                consecutive_failures += 1
                continue

            current_observation = self._execute_action(
                action=action,
                current_observation=current_observation,
                capability_prompt=capability_prompt,
                session=active_session,
                report=report,
            )

            record = self._record_step(
                report=report,
                step=step,
                action=action,
                observation=current_observation,
                plan=plan,
                capability_prompt=capability_prompt,
            )

            # Bug detection for environment actions
            if action.tool == "environment_action":
                findings = (
                    self._detector.inspect(action, current_observation)
                    if self._detector
                    else []
                )
                for bug in findings:
                    report.bugs.append(bug)
                    self._memory.record_bug(bug, step)
                    self._reporter.log_bug(bug, step)
                    
                    # Auto codebase lookup for discovered bugs
                    if bug.confidence >= self._confidence_threshold:
                         record.notes = self._append_note(
                             record.notes, 
                             self._auto_code_lookup(active_session, bug)
                         )

                if current_observation.success:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1

            # Auto log analysis
            if self._should_auto_log_analysis(
                action=action,
                findings=report.bugs,
                step=step,
                consecutive_failures=consecutive_failures,
            ):
                record.notes = self._append_note(
                    record.notes,
                    self._auto_log_analysis(active_session, report),
                )

        if not task_end_reason:
            task_end_reason = "max_steps_reached"
            task_end_trigger = "max_steps"
            report.metadata["forced_end_reason"] = "max_steps_reached"
            report.metadata["max_steps"] = self._max_steps
        self._close_all_sessions(
            report=report,
            open_sessions=open_sessions,
            step=min(len(report.steps), self._max_steps),
            reason=task_end_reason,
            trigger=task_end_trigger or "system",
        )
        active_session = None
        self._record_lifecycle_event(
            report,
            event="end_task",
            step=min(len(report.steps), self._max_steps),
            reason=task_end_reason,
            trigger=task_end_trigger or "system",
            metadata={"max_steps": self._max_steps},
        )
        report.metadata["end_reason"] = task_end_reason
        report.metadata["end_trigger"] = task_end_trigger or "system"
        return report

    def _ensure_lifecycle_tools(self) -> None:
        from .tool_registry import register_lifecycle_tools

        missing = {
            "start_session",
            "end_session",
            "new_session",
            "refresh_session",
            "switch_session",
            "list_sessions",
            "end_task",
        } - {tool.name for tool in self._tool_registry.list_tools()}
        if missing:
            register_lifecycle_tools(self._tool_registry)

    def _start_session(
        self,
        *,
        report: RunReport,
        task_profile: str,
        step: int,
        trigger: str,
        open_sessions: Dict[str, SessionHandle],
        reason: str = "session started",
    ) -> SessionHandle:
        print(
            f"[session] starting session: "
            f"backend={self._execution_backend.backend_type} task={self._task_id}"
        )
        session = self._execution_backend.start_session(
            {"task_id": self._task_id, "task_profile": task_profile}
        )
        print(
            f"[session] session started: "
            f"backend={session.backend_type} session_id={session.session_id}"
        )
        open_sessions[session.session_id] = session
        self._sync_session_metadata(report, open_sessions, session.session_id)
        session_ids = report.metadata.setdefault("session_ids", [])
        if isinstance(session_ids, list) and session.session_id not in session_ids:
            session_ids.append(session.session_id)
        self._record_lifecycle_event(
            report,
            event="start_session",
            step=step,
            reason=reason,
            trigger=trigger,
            session=session,
        )
        return session

    def _end_session(
        self,
        *,
        report: RunReport,
        session: SessionHandle,
        step: int,
        reason: str,
        trigger: str,
        open_sessions: Dict[str, SessionHandle],
    ) -> None:
        self._execution_backend.close_session(session)
        open_sessions.pop(session.session_id, None)
        self._record_lifecycle_event(
            report,
            event="end_session",
            step=step,
            reason=reason,
            trigger=trigger,
            session=session,
        )

    def _close_all_sessions(
        self,
        *,
        report: RunReport,
        open_sessions: Dict[str, SessionHandle],
        step: int,
        reason: str,
        trigger: str,
    ) -> None:
        for session_id in list(open_sessions):
            session = open_sessions[session_id]
            self._end_session(
                report=report,
                session=session,
                step=step,
                reason=reason,
                trigger=trigger,
                open_sessions=open_sessions,
            )
        self._sync_session_metadata(report, open_sessions, "")

    def _sync_session_metadata(
        self,
        report: RunReport,
        open_sessions: Dict[str, SessionHandle],
        active_session_id: str,
    ) -> None:
        report.metadata["current_session_id"] = active_session_id
        report.metadata["open_session_ids"] = list(open_sessions)
        if active_session_id:
            report.metadata["session_id"] = active_session_id

    def _handle_lifecycle_session_tool(
        self,
        *,
        action: Action,
        report: RunReport,
        plan,
        step: int,
        task_profile: str,
        capability_prompt: str,
        open_sessions: Dict[str, SessionHandle],
        active_session: Optional[SessionHandle],
    ) -> tuple[Optional[SessionHandle], Observation, bool]:
        tool_name = action.tool
        reason = self._lifecycle_reason(action) or f"agent requested {tool_name}"

        if tool_name in {"start_session", "new_session"}:
            session = self._start_session(
                report=report,
                task_profile=task_profile,
                step=step,
                trigger="agent",
                open_sessions=open_sessions,
                reason=reason,
            )
            active_session = session
            observation = self._session_aware_observation(
                session=session,
                capability_prompt=capability_prompt,
                open_sessions=open_sessions,
                preamble=f"Opened session {session.session_id} and set it active.",
            )
            self._record_step(
                report=report,
                step=step,
                action=action,
                observation=observation,
                plan=plan,
                capability_prompt=capability_prompt,
            )
            return active_session, observation, True

        if tool_name == "list_sessions":
            observation = self._list_sessions_observation(
                open_sessions=open_sessions,
                active_session=active_session,
            )
            self._record_step(
                report=report,
                step=step,
                action=action,
                observation=observation,
                plan=plan,
                capability_prompt=capability_prompt,
            )
            return active_session, observation, True

        if tool_name == "end_session":
            target_session, close_reason = self._resolve_end_session_target(
                action=action,
                open_sessions=open_sessions,
                active_session=active_session,
            )
            if target_session is None:
                observation = Observation(
                    success=False,
                    message="No open session is available to close.",
                    state={},
                    summary="end_session failed: no open session",
                    env_state={},
                )
            else:
                closed_active = (
                    active_session is not None
                    and target_session.session_id == active_session.session_id
                )
                self._end_session(
                    report=report,
                    session=target_session,
                    step=step,
                    reason=close_reason,
                    trigger="agent",
                    open_sessions=open_sessions,
                )
                if closed_active:
                    active_session = None
                self._sync_session_metadata(
                    report,
                    open_sessions,
                    active_session.session_id if active_session else "",
                )
                observation = self._lifecycle_observation(
                    action=action,
                    event="end_session",
                    terminal=False,
                    message=self._format_session_state_message(
                        active_session_id=(
                            active_session.session_id if active_session else ""
                        ),
                        open_sessions=open_sessions,
                        preamble=(
                            f"Closed session {target_session.session_id}."
                        ),
                    ),
                )
            self._record_step(
                report=report,
                step=step,
                action=action,
                observation=observation,
                plan=plan,
                capability_prompt=capability_prompt,
            )
            return active_session, observation, True

        session_id = self._session_id_from_action(action)
        target_session = open_sessions.get(session_id)
        if target_session is None:
            observation = Observation(
                success=False,
                message=f"Unknown or closed session_id: {session_id}",
                state={},
                summary=f"{tool_name} failed: session not open",
                env_state={},
            )
            self._record_step(
                report=report,
                step=step,
                action=action,
                observation=observation,
                plan=plan,
                capability_prompt=capability_prompt,
            )
            return active_session, observation, True

        if tool_name == "switch_session":
            active_session = target_session
            self._sync_session_metadata(report, open_sessions, session_id)
            self._record_lifecycle_event(
                report,
                event="switch_session",
                step=step,
                reason=reason,
                trigger="agent",
                session=target_session,
                metadata={"active_session_id": session_id},
            )
            observation = self._session_aware_observation(
                session=target_session,
                capability_prompt=capability_prompt,
                open_sessions=open_sessions,
                preamble=f"Switched active session to {session_id}.",
            )
            self._record_step(
                report=report,
                step=step,
                action=action,
                observation=observation,
                plan=plan,
                capability_prompt=capability_prompt,
            )
            return active_session, observation, True

        capability = self._execution_backend.describe_capabilities(
            target_session,
            refresh=True,
        )
        target_session.metadata["refreshed_capability"] = capability.planner_summary
        self._record_lifecycle_event(
            report,
            event="refresh_session",
            step=step,
            reason=reason,
            trigger="agent",
            session=target_session,
            metadata={"capability_summary": capability.planner_summary},
        )
        observation = Observation(
            success=True,
            message=capability.planner_summary or f"Refreshed session {session_id}",
            state={},
            raw={"event": "refresh_session", "session_id": session_id},
            summary=f"Refreshed session {session_id}",
            env_state={},
        )
        self._record_step(
            report=report,
            step=step,
            action=action,
            observation=observation,
            plan=plan,
            capability_prompt=capability_prompt,
        )
        if active_session and active_session.session_id == session_id:
            observation = self._inject_capability_observation(
                target_session.initial_observation
                or Observation(
                    success=True,
                    message=capability.planner_summary,
                    state={},
                    summary=capability.planner_summary,
                    env_state={},
                ),
                capability_prompt,
            )
            return active_session, observation, True
        return active_session, observation, True

    def _record_lifecycle_event(
        self,
        report: RunReport,
        *,
        event: str,
        step: int,
        reason: str,
        trigger: str,
        session: Optional[SessionHandle] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        lifecycle_event = LifecycleEvent(
            event=event,
            step=step,
            timestamp=datetime.now(timezone.utc).isoformat(),
            reason=reason,
            trigger=trigger,
            session_id=session.session_id if session else "",
            backend_type=session.backend_type if session else self._execution_backend.backend_type,
            metadata=dict(metadata or {}),
        )
        report.lifecycle_events.append(lifecycle_event)
        if hasattr(self._reporter, "log_lifecycle_event"):
            self._reporter.log_lifecycle_event(lifecycle_event)

    @staticmethod
    def _format_session_state_message(
        *,
        active_session_id: str,
        open_sessions: Dict[str, SessionHandle],
        preamble: str = "",
    ) -> str:
        open_ids = list(open_sessions)
        lines = [
            preamble.strip(),
            f"active_session_id: {active_session_id or 'none'}",
            f"open_session_ids: {open_ids}",
        ]
        return "\n".join(line for line in lines if line)

    def _session_state_payload(
        self,
        *,
        open_sessions: Dict[str, SessionHandle],
        active_session: Optional[SessionHandle],
    ) -> Dict[str, Any]:
        active_session_id = active_session.session_id if active_session else ""
        open_ids = list(open_sessions)
        return {
            "active_session_id": active_session_id,
            "open_session_ids": open_ids,
        }

    def _list_sessions_observation(
        self,
        *,
        open_sessions: Dict[str, SessionHandle],
        active_session: Optional[SessionHandle],
    ) -> Observation:
        payload = self._session_state_payload(
            open_sessions=open_sessions,
            active_session=active_session,
        )
        message = self._format_session_state_message(
            active_session_id=payload["active_session_id"],
            open_sessions=open_sessions,
            preamble="Open sessions:",
        )
        return Observation(
            success=True,
            message=message,
            state=payload,
            raw={"event": "list_sessions", **payload},
            summary=message,
            env_state={},
        )

    def _session_aware_observation(
        self,
        *,
        session: SessionHandle,
        capability_prompt: str,
        open_sessions: Dict[str, SessionHandle],
        preamble: str,
    ) -> Observation:
        base = self._initial_observation(
            session=session,
            capability_prompt=capability_prompt,
        )
        state_block = self._format_session_state_message(
            active_session_id=session.session_id,
            open_sessions=open_sessions,
            preamble=preamble,
        )
        payload = self._session_state_payload(
            open_sessions=open_sessions,
            active_session=session,
        )
        return Observation(
            success=base.success,
            message=f"{state_block}\n\n{base.message}",
            state=payload,
            raw={
                "session_state": payload,
                **(base.raw or {}),
            },
            terminal=base.terminal,
            summary=state_block,
            env_state=base.env_state,
            artifacts=base.artifacts,
            execution=base.execution,
        )

    def _initial_observation(
        self,
        *,
        session: SessionHandle,
        capability_prompt: str,
    ) -> Observation:
        base_initial_observation = session.initial_observation or Observation(
            success=True,
            message="Session started.",
            state={},
            summary="Session started.",
            env_state={},
        )
        return self._inject_capability_observation(
            base_initial_observation,
            capability_prompt,
        )

    def _execute_action(
        self,
        *,
        action: Action,
        current_observation: Observation,
        capability_prompt: str,
        session: Optional[SessionHandle],
        report: RunReport,
    ) -> Observation:
        try:
            if action.tool == "environment_action":
                backend_capability = self._backend_capability(session, capability_prompt)
                result = self._operator.execute(
                    action=action,
                    current_observation=current_observation,
                    capability=backend_capability,
                    session=session,
                    backend=self._execution_backend,
                )
                return result.observation
            registry_result = self._tool_registry.invoke(
                action.tool,
                self._tool_registry.parse_action(action.tool, action.command),
                {
                    "session": session,
                    "history": report.steps,
                    "steps": report.steps,
                    "lifecycle_events": report.lifecycle_events,
                    "current_observation": current_observation,
                }
            )
            return registry_result.observation
        except Exception as exc:
            print(f"[operator] execution error: {exc}")
            return Observation(
                success=False,
                message=str(exc),
                summary=f"Internal error: {exc}",
                state={},
                env_state={},
            )

    def _backend_capability(
        self,
        session: SessionHandle,
        capability_prompt: str,
    ) -> CapabilityDescriptor:
        if not hasattr(self._execution_backend, "describe_capabilities"):
            return CapabilityDescriptor(planner_summary=capability_prompt)
        backend_capability = self._execution_backend.describe_capabilities(session)
        summary_parts = [
            item
            for item in [
                capability_prompt,
                backend_capability.planner_summary,
            ]
            if item
        ]
        return CapabilityDescriptor(
            planner_summary="\n\n".join(summary_parts),
            operator_context=backend_capability.operator_context,
            raw=backend_capability.raw,
        )

    def _record_step(
        self,
        *,
        report: RunReport,
        step: int,
        action: Action,
        observation: Observation,
        plan,
        capability_prompt: str,
    ) -> StepRecord:
        record = StepRecord(
            step=step,
            action=action,
            observation=observation,
            planner_prompt=plan.prompt,
            planner_output=plan.output,
            capability_summary=capability_prompt,
        )
        report.steps.append(record)
        if hasattr(self._memory, "record_step"):
            self._memory.record_step(record)
        if hasattr(self._reporter, "log_step"):
            self._reporter.log_step(record)
        return record

    def _resolve_end_session_target(
        self,
        *,
        action: Action,
        open_sessions: Dict[str, SessionHandle],
        active_session: Optional[SessionHandle],
    ) -> tuple[Optional[SessionHandle], str]:
        payload = self._tool_registry.parse_action("end_session", action.command)
        session_id = str(payload.get("session_id") or "").strip()
        reason = str(payload.get("reason") or "").strip() or "agent requested session end"
        if session_id:
            return open_sessions.get(session_id), reason
        return active_session, reason

    @staticmethod
    def _session_id_from_action(action: Action) -> str:
        return action.command.strip().split()[0] if action.command.strip() else ""

    def _lifecycle_observation(
        self,
        *,
        action: Action,
        event: str,
        terminal: bool,
        message: str = "",
    ) -> Observation:
        reason = message or self._lifecycle_reason(action)
        return Observation(
            success=True,
            message=reason or event,
            state={},
            raw={"event": event, "reason": reason},
            terminal=terminal,
            summary=f"Lifecycle event requested: {event}",
            env_state={},
            execution={
                "attempts": [],
                "diagnostics": {
                    "tool": event,
                    "reason": reason,
                    "lifecycle_event": event,
                },
            },
        )

    @staticmethod
    def _lifecycle_reason(action: Action) -> str:
        return action.command.strip() or action.rationale.strip()

    def _should_auto_log_analysis(self, *, action, findings, step, consecutive_failures) -> bool:
        if not self._has_tool("log_analyze"): return False
        interval_due = (
            self._log_analysis_interval > 0
            and step % self._log_analysis_interval == 0
        )
        return interval_due or consecutive_failures >= 3 or bool(findings)

    def _auto_log_analysis(self, session: Any, report: RunReport) -> str:
        try:
            result = self._tool_registry.invoke_internal(
                "log_analyze",
                {"include_debug_output": True},
                {
                    "session": session,
                    "history": report.steps,
                    "steps": report.steps,
                    "lifecycle_events": report.lifecycle_events,
                },
            )
            return f"[Auto log analysis]\n{result.observation.summary}"
        except: return ""

    def _auto_code_lookup(self, session: Any, bug: BugFinding) -> str:
        if not self._has_tool("code_search"): return ""
        try:
            query = "|".join(bug.description.split()[:5])
            res = self._tool_registry.invoke_internal("code_search", {"pattern": query}, {"session": session})
            return f"[Auto code lookup] Relevant files:\n{res.observation.message[:300]}"
        except: return ""

    def _has_tool(self, name: str) -> bool:
        return any(t.name == name for t in self._tool_registry.list_tools())

    def _inject_capability_observation(
        self,
        base: Observation,
        summary: str,
    ) -> Observation:
        return Observation(
            success=base.success,
            message=f"Capability observation:\n{summary}\n\nInitial environment observation:\n{base.message}",
            state=base.state,
            summary=base.summary,
            env_state=base.env_state,
            raw=base.raw,
            artifacts=base.artifacts,
            execution=base.execution,
        )

    @staticmethod
    def _append_note(existing: str, addition: str) -> str:
        if not addition: return existing
        return f"{existing}\n{addition}".strip()
