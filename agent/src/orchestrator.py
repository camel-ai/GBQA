"""Core QA Agent loop."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .bug_detector import BugDetector
from .evaluator import Evaluator
from .execution_backends import ExecutionBackend
from .memory import MemoryManager
from .operator import Operator
from .planner import ActionPlanner
from .reflection import ReflectionAnalyzer
from .reporter import Reporter
from .types import BugFinding, Observation, RunReport, StepRecord


class Orchestrator:
    """Coordinates the QA Agent loop."""

    def __init__(
        self,
        game_id: str,
        execution_backend: ExecutionBackend,
        operator: Operator,
        planner: ActionPlanner,
        memory: MemoryManager,
        detector: Optional[BugDetector],
        reporter: Reporter,
        evaluator: Optional[Evaluator],
        max_steps: int,
        reflection_analyzer: Optional[ReflectionAnalyzer],
        reflection_threshold: int,
        max_consecutive_failures: int,
        confidence_threshold: float,
        reflection_interval: int,
        summary_interval: int,
    ) -> None:
        self._game_id = game_id
        self._execution_backend = execution_backend
        self._operator = operator
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
        self._summary_interval = summary_interval

    def run(self, game_profile: str) -> RunReport:
        start = datetime.now(timezone.utc).isoformat()
        print(
            f"[session] starting backend session: "
            f"backend={self._execution_backend.backend_type} game={self._game_id}"
        )
        session = self._execution_backend.start_session(
            {"game_id": self._game_id, "game_profile": game_profile}
        )
        print(
            f"[session] backend session started: "
            f"backend={session.backend_type} session_id={session.session_id}"
        )
        capability = self._execution_backend.describe_capabilities(session, refresh=False)
        base_initial_observation = session.initial_observation or Observation(
            success=True,
            message="Session started.",
            state={},
            summary="Session started.",
            env_state={},
        )
        initial_observation = self._inject_capability_observation(
            base_initial_observation,
            capability.planner_summary,
        )

        report = RunReport(
            game_id=self._game_id,
            steps=[],
            bugs=[],
            summaries=[],
            metadata={
                "start_time": start,
                "session_id": session.session_id,
                "backend": {"type": session.backend_type},
                "capability_summary": capability.planner_summary,
            },
        )

        current_observation = initial_observation
        consecutive_failures = 0
        last_reflection_step = 0
        last_summary_step = 0

        try:
            for step in range(1, self._max_steps + 1):
                context = self._build_context(
                    game_profile=game_profile,
                    observation=current_observation,
                )
                plan = self._planner.plan(context)
                if plan.error:
                    report.metadata["early_stop_reason"] = "planner_error"
                    report.metadata["failed_stage"] = "planner"
                    report.metadata["failed_step"] = step
                    report.metadata["llm_error"] = plan.error
                    break

                action = plan.action
                execution_result = self._operator.execute(
                    action=action,
                    current_observation=current_observation,
                    capability=capability,
                    session=session,
                    backend=self._execution_backend,
                )
                refreshed_capability = getattr(
                    execution_result,
                    "refreshed_capability",
                    None,
                )
                if refreshed_capability is not None:
                    capability = refreshed_capability
                current_observation = execution_result.observation

                record = StepRecord(
                    step=step,
                    action=action,
                    observation=current_observation,
                    planner_prompt=plan.prompt,
                    planner_output=plan.output,
                    capability_summary=capability.planner_summary,
                )
                report.steps.append(record)

                findings = (
                    self._detector.inspect(action, current_observation)
                    if self._detector
                    else []
                )
                for bug in findings:
                    report.bugs.append(bug)
                    self._memory.record_bug(bug, step)
                    self._reporter.log_bug(bug, step)

                if current_observation.success:
                    consecutive_failures = 0
                elif self._detector and self._detector.is_benign_failure(current_observation):
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1

                should_reflect = self._should_reflect(
                    action=action,
                    observation=current_observation,
                    findings=findings,
                    step=step,
                    last_reflection_step=last_reflection_step,
                    consecutive_failures=consecutive_failures,
                )
                reflection = None
                fatal_llm_error = ""
                if self._reflection_analyzer and should_reflect:
                    reflection_context = self._build_context(
                        game_profile=game_profile,
                        observation=current_observation,
                    )
                    reflection = self._reflection_analyzer.reflect(reflection_context)
                    record.notes = self._reflection_analyzer.format_note(reflection)
                    record.reflection_prompt = reflection.prompt
                    record.reflection_output = reflection.output
                    last_reflection_step = step
                    if reflection.error:
                        fatal_llm_error = reflection.error
                    promoted_bug = self._promote_reflection_bug(
                        reflection=reflection,
                        step=step,
                        action_command=action.command,
                        observation=current_observation,
                        existing_bugs=report.bugs,
                    )
                    if promoted_bug is not None:
                        report.bugs.append(promoted_bug)
                        self._memory.record_bug(promoted_bug, step)
                        self._reporter.log_bug(promoted_bug, step)

                self._memory.record_step(record)
                self._reporter.log_step(record)
                if fatal_llm_error:
                    report.metadata["early_stop_reason"] = "reflection_error"
                    report.metadata["failed_stage"] = "reflection"
                    report.metadata["failed_step"] = step
                    report.metadata["llm_error"] = fatal_llm_error
                    self._reporter.write_report(report)
                    break

                summary_record = None
                if plan.error and "context" in plan.error.lower():
                    summary_record = self._memory.force_summarize(step)
                if reflection and reflection.error and "context" in reflection.error.lower():
                    summary_record = self._memory.force_summarize(step)
                if (
                    not summary_record
                    and self._summary_interval > 0
                    and (step - last_summary_step) >= self._summary_interval
                ):
                    summary_record = self._memory.force_summarize(step)
                if not summary_record:
                    summary_record = self._memory.maybe_summarize(step)
                if summary_record:
                    report.summaries.append(summary_record)
                    last_summary_step = step
                    self._reporter.log_summary(
                        {"prompt": summary_record.prompt, "output": summary_record.output},
                        step,
                    )
                self._reporter.write_report(report)
                if current_observation.game_over:
                    break
                if consecutive_failures >= self._max_consecutive_failures:
                    report.metadata["early_stop_reason"] = "max_consecutive_failures"
                    break
        finally:
            try:
                self._execution_backend.close_session(session)
            except Exception as exc:  # noqa: BLE001
                report.metadata["session_close_error"] = str(exc)

        report.summary = self._memory.get_long_term_summary()
        report.metadata["end_time"] = datetime.now(timezone.utc).isoformat()
        if self._evaluator:
            result = self._evaluator.evaluate(report.bugs)
            report.metadata["evaluation"] = {
                "precision": result.precision,
                "recall": result.recall,
                "matched": result.matched,
                "total_predicted": result.total_predicted,
                "total_ground_truth": result.total_ground_truth,
                "details": [detail.__dict__ for detail in result.details],
            }
        return report

    @staticmethod
    def _inject_capability_observation(
        observation: Observation,
        capability_text: str,
    ) -> Observation:
        capability_text = capability_text.strip()
        if not capability_text:
            return observation
        base_text = (observation.summary or observation.message or "").strip()
        sections = [f"Capability observation:\n{capability_text}"]
        if base_text:
            sections.append(f"Initial environment observation:\n{base_text}")
        combined_text = "\n\n".join(sections).strip()
        return Observation(
            success=observation.success,
            message=combined_text,
            state=observation.state,
            raw=observation.raw,
            game_over=observation.game_over,
            turn=observation.turn,
            summary=combined_text,
            env_state=observation.env_state,
            artifacts=observation.artifacts,
            execution=observation.execution,
        )

    def _should_reflect(
        self,
        *,
        action: Any,
        observation: Observation,
        findings: List[BugFinding],
        step: int,
        last_reflection_step: int,
        consecutive_failures: int,
    ) -> bool:
        suspected_origin = str(
            (observation.execution or {}).get("suspected_origin", "")
        )
        if not observation.success and suspected_origin == "execution":
            return False
        if action.bug_exist and action.confidence >= self._confidence_threshold:
            return True
        if findings or consecutive_failures >= self._reflection_threshold:
            return True
        return (
            self._reflection_interval > 0
            and (step - last_reflection_step) >= self._reflection_interval
            and (observation.success or suspected_origin in {"environment", "ambiguous", ""})
        )

    def _promote_reflection_bug(
        self,
        *,
        reflection: Any,
        step: int,
        action_command: str,
        observation: Observation,
        existing_bugs: List[BugFinding],
    ) -> Optional[BugFinding]:
        if not reflection.bug_exist:
            return None
        if reflection.bug_confidence < self._confidence_threshold:
            return None
        evidence = reflection.bug_evidence.strip()
        if not evidence:
            return None
        candidate = BugFinding(
            title="Reflection-identified gameplay issue",
            description=evidence,
            confidence=float(reflection.bug_confidence),
            evidence={
                "command": action_command,
                "observation": observation.summary or observation.message,
                "execution": observation.execution,
                "next_check": reflection.next_check,
                "step": step,
            },
            tags=["reflection"],
        )
        if self._is_duplicate_bug(candidate, existing_bugs):
            return None
        return candidate

    @staticmethod
    def _is_duplicate_bug(
        candidate: BugFinding,
        existing_bugs: List[BugFinding],
    ) -> bool:
        for existing in existing_bugs:
            similarity = SequenceMatcher(
                None,
                candidate.description.lower(),
                existing.description.lower(),
            ).ratio()
            if similarity >= 0.88:
                return True
        return False

    def _build_context(
        self,
        *,
        game_profile: str,
        observation: Observation,
    ) -> Dict[str, Any]:
        observation_text = observation.summary or observation.message
        execution_diagnostics = json.dumps(
            (observation.execution or {}).get("diagnostics", {}),
            ensure_ascii=False,
        )
        cross_session_memory = ""
        query = "\n".join([observation_text, self._memory.get_long_term_summary()])
        hits = self._memory.get_cross_session_memories(query)
        if hits:
            lines = [
                f"- ({hit.session_id} step {hit.step}, score={hit.score:.2f}) {hit.text}"
                for hit in hits
            ]
            cross_session_memory = "\n".join(lines)
        recent_trace = self._memory.get_recent_trace()
        memory_summary = self._memory.get_long_term_summary()
        if cross_session_memory:
            memory_summary = (
                f"{memory_summary}\n\nCross-session relevant memory:\n{cross_session_memory}"
            ).strip()
        return {
            "game_profile": game_profile,
            "memory_summary": memory_summary,
            "recent_trace": recent_trace,
            "current_observation": observation_text,
            "current_artifacts": self._artifact_summary(observation),
            "observation_images": self._observation_images(observation),
            "execution_diagnostics": execution_diagnostics,
            "turn": observation.turn or 0,
            "code_tools_prompt_section": self._build_code_tools_prompt_section(),
        }

    @staticmethod
    def _artifact_summary(observation: Observation) -> str:
        screenshots = observation.artifacts.get("screenshots", [])
        if not isinstance(screenshots, list) or not screenshots:
            return ""
        labels = []
        for item in screenshots:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            path = str(item.get("path", "")).strip()
            if label:
                labels.append(label)
            elif path:
                labels.append(Path(path).name)
        if not labels:
            return ""
        return "Attached screenshots: " + ", ".join(labels)

    @staticmethod
    def _observation_images(observation: Observation) -> List[str]:
        screenshots = observation.artifacts.get("screenshots", [])
        if not isinstance(screenshots, list):
            return []
        image_paths = []
        for item in screenshots:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            if path:
                image_paths.append(path)
        return image_paths

    @staticmethod
    def _build_code_tools_prompt_section() -> str:
        return (
            "## Available Tools:\n"
            "- game_command (default): Send a command to the game.\n\n"
            "Code-reading and white-box debugging tools are not available through this "
            "execution path yet. Do not choose any `code_*` tool."
        )
