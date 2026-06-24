"""Benchmark task execution orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Type

from .bug_detector import BugDetector
from .execution_backends import ExecutionBackend
from .final_issue import (
    fallback_final_issue_from_report,
    final_issue_metadata,
)
from .hooks import HookManager, event_type_for_action
from .memory import MemoryManager
from .operator import Operator
from .planner import ActionPlanner
from .qa_state import CoverageState, HypothesisManager, build_bug_evidence
from .reflection import ReflectionAnalyzer
from .reporter import Reporter
from .subagents import SubagentManager, SubagentResult
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

_ENVIRONMENT_ACTION_TOOLS = frozenset(
    {
        "environment_action",
        "terminal_action",
        "browser_action",
        "computer_action",
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
        max_steps: int = 50,
        reflection_analyzer: Optional[ReflectionAnalyzer] = None,
        reflection_threshold: int = 3,
        max_consecutive_failures: int = 5,
        confidence_threshold: float = 0.8,
        reflection_interval: int = 10,
        log_analysis_interval: int = 20,
        summary_interval: int = 50,
        auto_log_analysis_policy: Optional[Dict[str, Any]] = None,
        auto_code_lookup_policy: Optional[Dict[str, Any]] = None,
        end_condition_policy: Optional[Dict[str, Any]] = None,
        allow_auto_code_registration: bool = False,
        hook_manager: Optional[HookManager] = None,
        subagent_manager: Optional[SubagentManager] = None,
        final_issue_reporter: Optional[Any] = None,
    ) -> None:
        self._task_id = task_id
        self._execution_backend = execution_backend
        self._operator = operator
        self._tool_registry = tool_registry
        self._planner = planner
        self._memory = memory
        self._detector = detector
        self._reporter = reporter
        self._max_steps = max_steps
        self._reflection_analyzer = reflection_analyzer
        self._reflection_threshold = reflection_threshold
        self._max_consecutive_failures = max_consecutive_failures
        self._confidence_threshold = confidence_threshold
        self._reflection_interval = reflection_interval
        self._log_analysis_interval = log_analysis_interval
        self._summary_interval = summary_interval
        self._auto_log_analysis_policy = self._normalize_auto_log_policy(
            auto_log_analysis_policy,
            log_analysis_interval=log_analysis_interval,
        )
        self._auto_code_lookup_policy = self._normalize_auto_code_policy(
            auto_code_lookup_policy,
            confidence_threshold=confidence_threshold,
        )
        self._end_condition_policy = dict(end_condition_policy or {})
        self._allow_auto_code_registration = allow_auto_code_registration
        self._hook_manager = hook_manager or HookManager()
        self._subagents = subagent_manager
        self._final_issue_reporter = final_issue_reporter
        self._hypotheses = HypothesisManager(
            confidence_threshold=confidence_threshold,
        )
        self._coverage = CoverageState()

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
                "strategy": {
                    "auto_log_analysis": self._auto_log_analysis_policy,
                    "auto_code_lookup": self._auto_code_lookup_policy,
                    "end_conditions": self._end_condition_policy,
                    "max_consecutive_failures": self._max_consecutive_failures,
                    "reflection_interval": self._reflection_interval,
                    "summary_interval": self._summary_interval,
                    "subagents": (
                        self._subagents.policy
                        if self._subagents is not None
                        else {"enabled": False}
                    ),
                },
            },
        )
        self._emit_hook(
            report,
            hook="on_run_start",
            event_type="RunStarted",
            metadata={
                "backend_type": self._execution_backend.backend_type,
                "max_steps": self._max_steps,
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

        if self._allow_auto_code_registration and not self._has_tool("code_read_file"):
            if (
                hasattr(self._execution_backend, "shell")
                or self._execution_backend.backend_type in {"computer_use", "daytona"}
            ):
                from .codebase_types import UniversalCodebaseAdapter
                from .tool_registry import register_code_tools
                register_code_tools(
                    self._tool_registry,
                    UniversalCodebaseAdapter(shell_client=self._execution_backend),
                )

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
            
            self._emit_hook(
                report,
                hook="before_plan",
                event_type="Planning",
                step=step,
                session=active_session,
            )
            # Use dictionary context aligned with ActionPlanner's internal processing
            # (Matches keys used in src/planner.py and prompts/planner.md)
            plan = self._planner.plan({
                "task_profile": task_profile,
                "current_observation": current_observation.message,
                "memory_summary": self._memory.get_long_term_summary(),
                "recent_trace": self._memory.get_recent_trace(),
                "coverage_summary": self._coverage.summary(),
                "hypothesis_summary": self._hypotheses.summary(),
                "subagent_summary": self._subagent_summary(report),
                "available_tools_prompt_section": capability_prompt,
                "step": step,
            })

            action = plan.action
            if getattr(plan, "error", ""):
                self._emit_hook(
                    report,
                    hook="after_plan",
                    event_type="PlanFailed",
                    step=step,
                    action=action,
                    session=active_session,
                    metadata={"error": plan.error},
                )
                report.metadata["early_stop_reason"] = "planner_error"
                report.metadata["failed_stage"] = "planner"
                report.metadata["failed_step"] = step
                report.metadata["llm_error"] = plan.error
                task_end_reason = "planner_error"
                task_end_trigger = "system"
                break
            self._emit_hook(
                report,
                hook="after_plan",
                event_type="Planned",
                step=step,
                action=action,
                session=active_session,
            )

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
                    session=active_session,
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

            if active_session is None and self._is_environment_action_tool(action.tool):
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
                    session=None,
                )
                consecutive_failures += 1
                continue

            current_observation = self._execute_action(
                action=action,
                current_observation=current_observation,
                capability_prompt=capability_prompt,
                session=active_session,
                report=report,
                step=step,
            )

            record = self._record_step(
                report=report,
                step=step,
                action=action,
                observation=current_observation,
                plan=plan,
                capability_prompt=capability_prompt,
                session=active_session,
            )

            # Bug detection for environment actions
            findings: List[BugFinding] = []
            if self._is_environment_action_tool(action.tool):
                findings = (
                    self._detector.inspect(action, current_observation)
                    if self._detector
                    else []
                )
                for bug in findings:
                    new_bug_added = self._add_bug_finding(
                        report=report,
                        bug=bug,
                        step=step,
                        action=action,
                        observation=current_observation,
                        source="detector",
                    )
                    if new_bug_added:
                        reproducer_result = self._maybe_run_reproducer_subagent(
                            report=report,
                            record=record,
                            step=step,
                            session=active_session,
                            bug=bug,
                            observation=current_observation,
                        )
                        if reproducer_result is not None:
                            record.notes = self._append_note(
                                record.notes,
                                self._format_subagent_note(reproducer_result),
                            )
                    
                    # Auto codebase lookup for discovered bugs
                    if self._should_auto_code_lookup(bug):
                        auto_code_note = self._auto_code_lookup(
                            active_session,
                            bug,
                            report=report,
                            step=step,
                        )
                        record.notes = self._append_note(record.notes, auto_code_note)
                        if auto_code_note:
                            self._emit_hook(
                                report,
                                hook="on_auto_code_lookup",
                                event_type="Diagnosed",
                                step=step,
                                action=action,
                                session=active_session,
                                metadata={"bug_title": bug.title},
                            )

                if current_observation.success:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1

            self._record_strategy_state(
                record=record,
                report=report,
                session=active_session,
            )
            explorer_result = self._maybe_run_explorer_subagent(
                report=report,
                record=record,
                step=step,
                session=active_session,
                observation=current_observation,
            )
            if explorer_result is not None:
                record.notes = self._append_note(
                    record.notes,
                    self._format_subagent_note(explorer_result),
                )

            if self._is_environment_action_tool(action.tool):
                planner_hypothesis = self._hypotheses.add_from_planner_signal(
                    action=action,
                    step=step,
                    observation=current_observation,
                )
                if (
                    planner_hypothesis
                    and action.confidence >= self._confidence_threshold
                ):
                    new_bug_added = self._add_bug_finding(
                        report=report,
                        bug=BugFinding(
                            title=planner_hypothesis.title,
                            description=planner_hypothesis.description,
                            confidence=planner_hypothesis.confidence,
                            evidence=planner_hypothesis.evidence,
                            tags=planner_hypothesis.tags,
                        ),
                        step=step,
                        action=action,
                        observation=current_observation,
                        source="planner",
                    )
                    if new_bug_added and report.bugs:
                        reproducer_result = self._maybe_run_reproducer_subagent(
                            report=report,
                            record=record,
                            step=step,
                            session=active_session,
                            bug=report.bugs[-1],
                            observation=current_observation,
                        )
                        if reproducer_result is not None:
                            record.notes = self._append_note(
                                record.notes,
                                self._format_subagent_note(reproducer_result),
                            )

                reflection = self._maybe_reflect(
                    report=report,
                    record=record,
                    step=step,
                    action=action,
                    observation=current_observation,
                    consecutive_failures=consecutive_failures,
                    last_reflection_step=last_reflection_step,
                )
                if reflection is not None:
                    last_reflection_step = step

            # Auto log analysis
            if self._should_auto_log_analysis(
                action=action,
                findings=findings,
                step=step,
                consecutive_failures=consecutive_failures,
            ):
                auto_log_note = self._auto_log_analysis(
                    active_session,
                    report,
                    step=step,
                )
                record.notes = self._append_note(record.notes, auto_log_note)
                if auto_log_note:
                    self._emit_hook(
                        report,
                        hook="on_auto_log_analysis",
                        event_type="Diagnosed",
                        step=step,
                        action=action,
                        session=active_session,
                    )

            self._maybe_summarize(report=report, step=step, force_interval=True)

            if (
                self._end_condition_policy.get("end_on_terminal", False)
                and current_observation.terminal
            ):
                task_end_reason = "terminal_observation"
                task_end_trigger = "system"
                report.metadata["terminal_step"] = step
                break

            if (
                self._max_consecutive_failures > 0
                and consecutive_failures >= self._max_consecutive_failures
            ):
                task_end_reason = "max_consecutive_failures"
                task_end_trigger = "system"
                report.metadata["forced_end_reason"] = task_end_reason
                report.metadata["failed_step"] = step
                report.metadata["consecutive_failures"] = consecutive_failures
                break

        if not task_end_reason:
            task_end_reason = "max_steps_reached"
            task_end_trigger = "max_steps"
            report.metadata["forced_end_reason"] = "max_steps_reached"
            report.metadata["max_steps"] = self._max_steps
        exit_status = self._exit_status(
            trigger=task_end_trigger or "system",
            reason=task_end_reason,
            report=report,
        )
        report.metadata["exit_status"] = exit_status
        report.metadata["end_reason"] = task_end_reason
        report.metadata["end_trigger"] = task_end_trigger or "system"
        self._maybe_summarize(
            report=report,
            step=min(len(report.steps), self._max_steps),
            force_interval=False,
            force=True,
        )
        self._finalize_issue_report(
            report=report,
            task_profile=task_profile,
            exit_status=exit_status,
            exit_trigger=task_end_trigger or "system",
            exit_reason=task_end_reason,
        )
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
        report.metadata["coverage"] = self._coverage.to_dict()
        report.metadata["hypotheses"] = self._hypotheses.to_dict()
        self._emit_hook(
            report,
            hook="on_run_end",
            event_type="RunEnded",
            step=min(len(report.steps), self._max_steps),
            metadata={
                "end_reason": task_end_reason,
                "end_trigger": task_end_trigger or "system",
            },
        )
        return report

    def _finalize_issue_report(
        self,
        *,
        report: RunReport,
        task_profile: str,
        exit_status: str,
        exit_trigger: str,
        exit_reason: str,
    ) -> None:
        try:
            if self._final_issue_reporter is None:
                result = fallback_final_issue_from_report(report)
            else:
                result = self._final_issue_reporter.finalize(
                    report=report,
                    task_profile=task_profile,
                    exit_status=exit_status,
                    exit_trigger=exit_trigger,
                    exit_reason=exit_reason,
                    max_steps=self._max_steps,
                )
        except Exception as exc:  # noqa: BLE001
            result = fallback_final_issue_from_report(report)
            result.report_status = "invalid"
            result.issue["report_status"] = "invalid"
            result.error = f"{type(exc).__name__}: {exc}"
        report.metadata["final_issue_report"] = final_issue_metadata(result)
        self._emit_hook(
            report,
            hook="on_final_issue_report",
            event_type="Reported",
            step=min(len(report.steps), self._max_steps),
            metadata={
                "report_status": result.report_status,
                "missing_fields": result.missing_fields,
                "error": result.error,
            },
        )

    @staticmethod
    def _exit_status(*, trigger: str, reason: str, report: RunReport) -> str:
        if trigger == "max_steps" or reason == "max_steps_reached":
            return "max_steps"
        if report.metadata.get("failed_stage") or reason.endswith("_error"):
            return "error"
        return "completed"

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
                session=session,
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
                session=active_session,
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
                session=target_session,
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
                session=None,
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
                session=target_session,
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
            session=target_session,
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
        self._emit_hook(
            report,
            hook="on_lifecycle_event",
            event_type="Lifecycle",
            step=step,
            session=session,
            metadata={
                "event": event,
                "reason": reason,
                "trigger": trigger,
                **dict(metadata or {}),
            },
        )

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
        step: int,
    ) -> Observation:
        self._emit_hook(
            report,
            hook="before_tool_call",
            event_type=event_type_for_action(action),
            step=step,
            action=action,
            session=session,
            metadata={"phase": "before"},
        )
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
                self._emit_hook(
                    report,
                    hook="after_tool_call",
                    event_type=event_type_for_action(action),
                    step=step,
                    action=action,
                    session=session,
                    metadata={
                        "success": result.observation.success,
                        "phase": "after",
                    },
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
                    "planner_action": action,
                }
            )
            self._emit_hook(
                report,
                hook="after_tool_call",
                event_type=event_type_for_action(action),
                step=step,
                action=action,
                session=session,
                metadata={
                    "success": registry_result.observation.success,
                    "phase": "after",
                },
            )
            return registry_result.observation
        except Exception as exc:
            print(f"[operator] execution error: {exc}")
            self._emit_hook(
                report,
                hook="after_tool_call",
                event_type=event_type_for_action(action),
                step=step,
                action=action,
                session=session,
                metadata={
                    "success": False,
                    "error": str(exc),
                    "phase": "after",
                },
            )
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
        session: Optional[SessionHandle] = None,
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
        self._emit_hook(
            report,
            hook="after_step",
            event_type=event_type_for_action(action),
            step=step,
            action=action,
            session=session,
            metadata={"success": observation.success},
        )
        return record

    def _record_strategy_state(
        self,
        *,
        record: StepRecord,
        report: RunReport,
        session: Optional[SessionHandle],
    ) -> None:
        self._coverage.record(
            step=record.step,
            action=record.action,
            observation=record.observation,
            session_id=session.session_id if session else "",
        )
        report.metadata["coverage_summary"] = self._coverage.summary()
        report.metadata["hypothesis_summary"] = self._hypotheses.summary()
        self._emit_hook(
            report,
            hook="on_coverage_recorded",
            event_type="Covered",
            step=record.step,
            action=record.action,
            session=session,
            metadata={"coverage_summary": report.metadata["coverage_summary"]},
        )

    def _add_bug_finding(
        self,
        *,
        report: RunReport,
        bug: BugFinding,
        step: int,
        action: Action,
        observation: Observation,
        source: str,
    ) -> bool:
        if self._is_duplicate_bug(bug, report.bugs):
            self._hypotheses.add_from_finding(
                finding=bug,
                step=step,
                action=action,
                observation=observation,
                source=source,
            )
            return False
        bug.evidence = build_bug_evidence(
            bug.evidence,
            action=action,
            observation=observation,
        )
        bug.expected_behavior = bug.expected_behavior or str(
            bug.evidence.get("expected_behavior", "")
        ).strip()
        bug.observed_fault = bug.observed_fault or str(
            bug.evidence.get("observed_fault", "")
        ).strip()
        if not bug.reproduction:
            reproduction = bug.evidence.get("reproduction") or bug.evidence.get(
                "minimal_reproduction",
                [],
            )
            bug.reproduction = self._string_list(reproduction)
        if not bug.pinpoint:
            pinpoint = bug.evidence.get("pinpoint")
            if isinstance(pinpoint, dict):
                bug.pinpoint = pinpoint
        if not bug.root_cause:
            bug.root_cause = str(bug.evidence.get("root_cause", "")).strip()
        report.bugs.append(bug)
        self._hypotheses.add_from_finding(
            finding=bug,
            step=step,
            action=action,
            observation=observation,
            source=source,
        )
        if hasattr(self._memory, "record_bug"):
            self._memory.record_bug(bug, step)
        if hasattr(self._reporter, "log_bug"):
            self._reporter.log_bug(bug, step)
        self._emit_hook(
            report,
            hook="on_bug_reported",
            event_type="Reported",
            step=step,
            action=action,
            metadata={
                "source": source,
                "title": bug.title,
                "confidence": bug.confidence,
            },
        )
        return True

    def _maybe_reflect(
        self,
        *,
        report: RunReport,
        record: StepRecord,
        step: int,
        action: Action,
        observation: Observation,
        consecutive_failures: int,
        last_reflection_step: int,
    ) -> Optional[Any]:
        if not self._reflection_analyzer:
            return None
        if not self._should_reflect(
            action=action,
            step=step,
            observation=observation,
            consecutive_failures=consecutive_failures,
            last_reflection_step=last_reflection_step,
        ):
            return None
        execution_diagnostics = (
            observation.execution.get("diagnostics", {})
            if observation.execution
            else {}
        )
        reflection = self._reflection_analyzer.reflect(
            {
                "memory_summary": self._memory.get_long_term_summary(),
                "recent_trace": self._memory.get_recent_trace(),
                "current_observation": observation.summary or observation.message,
                "execution_diagnostics": str(execution_diagnostics),
            }
        )
        record.reflection_prompt = reflection.prompt
        record.reflection_output = reflection.output
        formatted_note = self._reflection_analyzer.format_note(reflection)
        record.notes = self._append_note(
            record.notes,
            f"[Reflection]\n{formatted_note}",
        )
        promoted = self._promote_reflection_bug(
            reflection=reflection,
            step=step,
            action_command=action.command,
            observation=observation,
            existing_bugs=report.bugs,
        )
        if promoted is not None:
            self._add_bug_finding(
                report=report,
                bug=promoted,
                step=step,
                action=action,
                observation=observation,
                source="reflection",
            )
        return reflection

    def _should_reflect(
        self,
        *,
        action: Action,
        step: int,
        observation: Observation,
        consecutive_failures: int,
        last_reflection_step: int,
    ) -> bool:
        if not self._is_environment_action_tool(action.tool):
            return False
        if action.bug_exist and action.confidence >= self._confidence_threshold:
            return True
        if (
            self._reflection_threshold > 0
            and consecutive_failures >= self._reflection_threshold
        ):
            return True
        if self._reflection_interval <= 0:
            return False
        if step - last_reflection_step < self._reflection_interval:
            return False
        if observation.success and not action.bug_exist:
            return True
        return not BugDetector.is_benign_failure(observation)

    def _promote_reflection_bug(
        self,
        *,
        reflection: Any,
        step: int,
        action_command: str,
        observation: Observation,
        existing_bugs: List[BugFinding],
    ) -> Optional[BugFinding]:
        if not getattr(reflection, "bug_exist", False):
            return None
        confidence = float(getattr(reflection, "bug_confidence", 0.0) or 0.0)
        evidence_text = str(getattr(reflection, "bug_evidence", "") or "").strip()
        if confidence < self._confidence_threshold or not evidence_text:
            return None
        candidate = BugFinding(
            title="Reflection-identified environment issue",
            description=evidence_text,
            confidence=confidence,
            evidence=build_bug_evidence(
                {
                    "step": step,
                    "action": action_command,
                    "observation": observation.summary or observation.message,
                    "observed_fault": evidence_text,
                    "source": "reflection",
                },
                action=Action(
                    tool="reflection",
                    command=action_command,
                    bug_exist=True,
                    explanation=evidence_text,
                ),
                observation=observation,
            ),
            tags=["reflection"],
        )
        if self._is_duplicate_bug(candidate, existing_bugs):
            return None
        return candidate

    def _maybe_summarize(
        self,
        *,
        report: RunReport,
        step: int,
        force_interval: bool,
        force: bool = False,
    ) -> None:
        summary = None
        if force:
            if hasattr(self._memory, "force_summarize"):
                summary = self._memory.force_summarize(step)
        elif (
            force_interval
            and self._summary_interval > 0
            and step > 0
            and step % self._summary_interval == 0
            and hasattr(self._memory, "force_summarize")
        ):
            summary = self._memory.force_summarize(step)
        elif hasattr(self._memory, "maybe_summarize"):
            summary = self._memory.maybe_summarize(step)
        if summary is None:
            return
        report.summaries.append(summary)
        if hasattr(self._reporter, "log_summary"):
            self._reporter.log_summary(
                {"summary": getattr(summary, "output", "")},
                step,
            )
        self._emit_hook(
            report,
            hook="on_summary_created",
            event_type="Summarized",
            step=step,
            metadata={"summary_length": len(getattr(summary, "output", "") or "")},
        )

    @staticmethod
    def _is_duplicate_bug(
        candidate: BugFinding,
        existing_bugs: List[BugFinding],
    ) -> bool:
        candidate_text = (
            f"{candidate.title} {candidate.description}"
        ).strip().lower()
        for bug in existing_bugs:
            existing_text = f"{bug.title} {bug.description}".strip().lower()
            if candidate_text and (
                candidate_text in existing_text
                or existing_text in candidate_text
                or SequenceMatcher(None, candidate_text, existing_text).ratio() >= 0.86
            ):
                return True
        return False

    def _resolve_end_session_target(
        self,
        *,
        action: Action,
        open_sessions: Dict[str, SessionHandle],
        active_session: Optional[SessionHandle],
    ) -> tuple[Optional[SessionHandle], str]:
        text = action.command.strip()
        if not text:
            return active_session, "agent requested session end"

        first, _, remainder = text.partition(" ")
        if first in open_sessions:
            reason = remainder.strip() or "agent requested session end"
            return open_sessions[first], reason
        return active_session, text

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

    def _maybe_run_explorer_subagent(
        self,
        *,
        report: RunReport,
        record: StepRecord,
        step: int,
        session: Optional[SessionHandle],
        observation: Observation,
    ) -> Optional[SubagentResult]:
        del record
        if self._subagents is None or not self._subagents.should_run_explorer(step=step):
            return None
        result = self._subagents.explore(
            coverage_summary=self._coverage.summary(),
            observation_summary=observation.summary or observation.message,
        )
        self._record_subagent_result(
            report=report,
            result=result,
            step=step,
            session=session,
        )
        return result

    def _maybe_run_reproducer_subagent(
        self,
        *,
        report: RunReport,
        record: StepRecord,
        step: int,
        session: Optional[SessionHandle],
        bug: BugFinding,
        observation: Observation,
    ) -> Optional[SubagentResult]:
        del record
        if self._subagents is None or not self._subagents.enabled("reproducer"):
            return None
        result = self._subagents.reproduce(
            hypothesis_summary=self._hypotheses.summary(),
            bug=bug,
            observation_summary=observation.summary or observation.message,
        )
        self._record_subagent_result(
            report=report,
            result=result,
            step=step,
            session=session,
        )
        return result

    def _record_subagent_result(
        self,
        *,
        report: RunReport,
        result: SubagentResult,
        step: int,
        session: Optional[SessionHandle],
    ) -> None:
        policy = self._subagents.policy if self._subagents is not None else {}
        include_prompt = bool(policy.get("record_prompts", False))
        payload = result.to_dict(include_prompt=include_prompt)
        payload["step"] = step
        results = report.metadata.setdefault("subagent_results", [])
        if isinstance(results, list):
            results.append(payload)
        report.metadata["subagent_summary"] = self._subagent_summary(report)
        self._emit_hook(
            report,
            hook="on_subagent_result",
            event_type="Ran",
            step=step,
            session=session,
            metadata={
                "worker": result.worker,
                "summary": result.summary,
                "suggestion_count": len(result.suggestions),
                "error": result.error,
            },
        )

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _subagent_summary(report: RunReport, *, max_items: int = 4) -> str:
        results = report.metadata.get("subagent_results", [])
        if not isinstance(results, list) or not results:
            return "No isolated worker subagent hints yet."
        lines = []
        for item in results[-max_items:]:
            if not isinstance(item, dict):
                continue
            worker = str(item.get("worker") or "Subagent")
            summary = str(item.get("summary") or "").strip()
            suggestions = item.get("suggestions", [])
            suggestion_text = ""
            if isinstance(suggestions, list) and suggestions:
                suggestion_text = "; next: " + "; ".join(
                    str(value) for value in suggestions[:2]
                )
            if summary or suggestion_text:
                lines.append(f"- {worker}: {summary}{suggestion_text}")
        return "\n".join(lines) if lines else "No isolated worker subagent hints yet."

    @staticmethod
    def _format_subagent_note(result: SubagentResult) -> str:
        if result.error:
            return f"[{result.worker}] error: {result.error}"
        parts = [f"[{result.worker}]", result.summary]
        if result.suggestions:
            parts.append("Suggestions: " + "; ".join(result.suggestions[:4]))
        return "\n".join(part for part in parts if part).strip()

    def _should_auto_log_analysis(self, *, action, findings, step, consecutive_failures) -> bool:
        policy = self._auto_log_analysis_policy
        if not policy.get("enabled", False):
            return False
        if not self._has_tool("log_analyze"):
            return False
        if not self._is_environment_action_tool(action.tool):
            return False
        interval_steps = int(policy.get("interval_steps") or 0)
        interval_due = interval_steps > 0 and step % interval_steps == 0
        failure_threshold = int(policy.get("consecutive_failures_threshold") or 0)
        failure_due = failure_threshold > 0 and consecutive_failures >= failure_threshold
        findings_due = bool(policy.get("on_findings", True)) and bool(findings)
        return interval_due or failure_due or findings_due

    @staticmethod
    def _is_environment_action_tool(tool_name: str) -> bool:
        return str(tool_name) in _ENVIRONMENT_ACTION_TOOLS

    def _auto_log_analysis(
        self,
        session: Any,
        report: RunReport,
        *,
        step: int,
    ) -> str:
        if self._subagents is not None and self._subagents.enabled("log_analyst"):
            result = self._subagents.analyze_logs(
                registry=self._tool_registry,
                session=session,
                runtime_context={
                    "history": report.steps,
                    "steps": report.steps,
                    "lifecycle_events": report.lifecycle_events,
                },
            )
            self._record_subagent_result(
                report=report,
                result=result,
                step=step,
                session=session,
            )
            return self._format_subagent_note(result)
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
        except Exception:
            return ""

    def _auto_code_lookup(
        self,
        session: Any,
        bug: BugFinding,
        *,
        report: RunReport,
        step: int,
    ) -> str:
        if not self._has_tool("code_search"):
            return ""
        if self._subagents is not None and self._subagents.enabled("code_localizer"):
            result = self._subagents.localize_code(
                registry=self._tool_registry,
                session=session,
                bug=bug,
            )
            self._record_subagent_result(
                report=report,
                result=result,
                step=step,
                session=session,
            )
            return self._format_subagent_note(result)
        try:
            query = "|".join(bug.description.split()[:5])
            res = self._tool_registry.invoke_internal(
                "code_search",
                {"pattern": query},
                {"session": session},
            )
            return f"[Auto code lookup] Relevant files:\n{res.observation.message[:300]}"
        except Exception:
            return ""

    def _should_auto_code_lookup(self, bug: BugFinding) -> bool:
        policy = self._auto_code_lookup_policy
        if not policy.get("enabled", False):
            return False
        minimum = float(policy.get("min_confidence", self._confidence_threshold))
        return bug.confidence >= minimum

    def _has_tool(self, name: str) -> bool:
        return any(t.name == name for t in self._tool_registry.list_tools())

    def _emit_hook(
        self,
        report: RunReport,
        *,
        hook: str,
        event_type: str,
        step: int = 0,
        action: Optional[Action] = None,
        session: Optional[SessionHandle] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            self._hook_manager.emit(
                report=report,
                reporter=self._reporter,
                hook=hook,
                event_type=event_type,
                step=step,
                action=action,
                session=session,
                metadata=metadata,
            )
        except Exception:
            return

    def _inject_capability_observation(
        self,
        base: Observation,
        summary: str,
    ) -> Observation:
        return Observation(
            success=base.success,
            message=(
                f"Capability observation:\n{summary}\n\n"
                f"Initial environment observation:\n{base.message}"
            ),
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

    @staticmethod
    def _normalize_auto_log_policy(
        policy: Optional[Dict[str, Any]],
        *,
        log_analysis_interval: int,
    ) -> Dict[str, Any]:
        normalized = {
            "enabled": True,
            "interval_steps": log_analysis_interval,
            "on_findings": True,
            "consecutive_failures_threshold": 3,
        }
        if policy is not None:
            normalized.update(policy)
        return normalized

    @staticmethod
    def _normalize_auto_code_policy(
        policy: Optional[Dict[str, Any]],
        *,
        confidence_threshold: float,
    ) -> Dict[str, Any]:
        normalized = {
            "enabled": True,
            "min_confidence": confidence_threshold,
        }
        if policy is not None:
            normalized.update(policy)
        return normalized
