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
    Observation,
    RunReport,
    StepRecord,
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
        print(
            f"[session] starting backend session: "
            f"backend={self._execution_backend.backend_type} task={self._task_id}"
        )
        session = self._execution_backend.start_session(
            {"task_id": self._task_id, "task_profile": task_profile}
        )
        print(
            f"[session] backend session started: "
            f"backend={session.backend_type} session_id={session.session_id}"
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
        
        base_initial_observation = session.initial_observation or Observation(
            success=True,
            message="Session started.",
            state={},
            summary="Session started.",
            env_state={},
        )
        initial_observation = self._inject_capability_observation(
            base_initial_observation,
            capability_prompt,
        )

        report = RunReport(
            task_id=self._task_id,
            steps=[],
            bugs=[],
            summaries=[],
            metadata={
                "start_time": start,
                "session_id": session.session_id,
                "backend": {"type": session.backend_type},
                "capability_summary": capability_prompt,
            },
        )

        current_observation = initial_observation
        consecutive_failures = 0
        last_reflection_step = 0

        for step in range(1, self._max_steps + 1):
            print(f"\n[step {step}]")
            
            # Re-render prompt section if skills might have changed
            capability_prompt = self._tool_registry.render_prompt_section()
            
            # Use the new dictionary-based context for planning
            plan = self._planner.plan({
                "task_profile": task_profile,
                "observation": current_observation,
                "memory": self._memory,
                "capability_summary": capability_prompt,
                "step": step,
            })

            action = plan.action
            if action.tool == "close_game":
                print("[session] agent requested session termination")
                break

            # Execute tool (either environment or built-in tools like use_skill)
            try:
                if action.tool == "environment_action":
                    result = self._operator.execute(
                        action=action,
                        current_observation=current_observation,
                        capability=CapabilityDescriptor(planner_summary=capability_prompt),
                        session=session,
                        backend=self._execution_backend,
                    )
                    current_observation = result.observation
                else:
                    # Invoke registry tools (including use_skill and codebase tools)
                    registry_result = self._tool_registry.invoke(
                        action.tool,
                        self._tool_registry.parse_action(action.tool, action.command),
                        {"session": session, "history": report.steps, "current_observation": current_observation}
                    )
                    current_observation = registry_result.observation
            except Exception as exc:
                print(f"[operator] execution error: {exc}")
                current_observation = Observation(
                    success=False,
                    message=str(exc),
                    summary=f"Internal error: {exc}",
                    state={},
                    env_state={}
                )

            record = StepRecord(
                step=step,
                action=action,
                observation=current_observation,
                planner_prompt=plan.prompt,
                planner_output=plan.output,
                capability_summary=capability_prompt,
            )
            report.steps.append(record)

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
                             self._auto_code_lookup(session, bug)
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
                    self._auto_log_analysis(session),
                )

        self._execution_backend.close_session(session)
        return report

    def _should_auto_log_analysis(self, *, action, findings, step, consecutive_failures) -> bool:
        if not self._has_tool("log_analyze"): return False
        return (step % self._log_analysis_interval == 0) or consecutive_failures >= 3 or bool(findings)

    def _auto_log_analysis(self, session: Any) -> str:
        try:
            result = self._tool_registry.invoke_internal(
                "log_analyze",
                {"include_debug_output": True},
                {"session": session}
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
