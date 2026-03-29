"""Core QA Agent loop."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from .bug_detector import BugDetector
from .evaluator import Evaluator
from .tool_registry import ToolRegistry
from .memory import MemoryManager
from .observer import ObservationParser
from .planner import ActionPlanner
from .reporter import Reporter
from .reflection import ReflectionAnalyzer
from .types import BugFinding, Observation, RunReport, StepRecord


class Orchestrator:
    """Coordinates the QA Agent loop."""

    def __init__(
        self,
        game_id: str,
        tool_registry: ToolRegistry,
        planner: ActionPlanner,
        memory: MemoryManager,
        detector: BugDetector,
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
        self._summary_interval = summary_interval
        self._parser = ObservationParser()

    def run(self, game_profile: str) -> RunReport:
        start = datetime.now(timezone.utc).isoformat()
        initial_payload = self._tool_registry.invoke("game_new", {})
        game_session_id = initial_payload.get("game_id", "")
        initial_observation = self._parser.parse(
            {
                "success": initial_payload.get("success", False),
                "message": initial_payload.get("message", ""),
                "state": initial_payload.get("state", {}),
                "game_over": False,
                "turn": 0,
            }
        )

        report = RunReport(
            game_id=self._game_id,
            steps=[],
            bugs=[],
            summaries=[],
            metadata={"start_time": start, "game_session_id": game_session_id},
        )

        current_observation = initial_observation
        consecutive_failures = 0
        last_reflection_step = 0
        last_summary_step = 0
        for step in range(1, self._max_steps + 1):
            context = self._build_context(game_profile, current_observation)
            plan = self._planner.plan(context)
            if plan.error:
                report.metadata["early_stop_reason"] = "planner_error"
                report.metadata["failed_stage"] = "planner"
                report.metadata["failed_step"] = step
                report.metadata["llm_error"] = plan.error
                break
            action = plan.action
            raw_response = self._tool_registry.invoke(
                "game_command", {"game_id": game_session_id, "command": action.command}
            )
            current_observation = self._parser.parse(raw_response)
            record = StepRecord(
                step=step,
                action=action,
                observation=current_observation,
                planner_prompt=plan.prompt,
                planner_output=plan.output,
            )
            report.steps.append(record)

            findings = self._detector.inspect(action, current_observation)
            for bug in findings:
                report.bugs.append(bug)
                self._memory.record_bug(bug, step)
                self._reporter.log_bug(bug, step)

            if current_observation.success:
                consecutive_failures = 0
            elif self._detector.is_benign_failure(current_observation):
                consecutive_failures = 0
            else:
                consecutive_failures += 1

            should_reflect = False
            reflection = None
            fatal_llm_error = ""
            if action.bug_exist and action.confidence >= self._confidence_threshold:
                should_reflect = True
            if findings or consecutive_failures >= self._reflection_threshold:
                should_reflect = True
            if (
                self._reflection_interval > 0
                and (step - last_reflection_step) >= self._reflection_interval
            ):
                should_reflect = True
            if self._reflection_analyzer and should_reflect:
                reflection = self._reflection_analyzer.reflect(context)
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
                "observation": observation.message,
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

    @staticmethod
    def _is_fatal_llm_error(error: str) -> bool:
        lowered = (error or "").lower()
        if not lowered:
            return False
        return any(
            token in lowered
            for token in (
                "ratelimiterror",
                "rate limit",
                "quota",
                "error code: 429",
            )
        )

    def _build_context(
        self, game_profile: str, observation: Observation
    ) -> Dict[str, Any]:
        hud_text = self._build_hud_text(observation)
        observation_text = observation.message
        if hud_text:
            observation_text = f"{observation_text}\n\n{hud_text}"
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
            "turn": observation.turn or 0,
        }

    def _build_hud_text(self, observation: Observation) -> str:
        state = observation.state or {}
        room = state.get("room", {}) if isinstance(state, dict) else {}
        room_name = room.get("name", "")
        exits = room.get("exits", [])
        exit_text = ", ".join(exits) if isinstance(exits, list) else ""
        inventory = state.get("inventory", [])
        inventory_count = len(inventory) if isinstance(inventory, list) else 0
        lit_items = []
        if isinstance(inventory, list):
            for item in inventory:
                if not isinstance(item, dict):
                    continue
                item_state = item.get("state", {})
                if isinstance(item_state, dict) and item_state.get("lit") is True:
                    lit_items.append(item.get("name", "unknown"))
        light_source_text = "on" if lit_items else "off"
        can_see = state.get("can_see", None)
        visibility_text = "on" if can_see else "off" if can_see is not None else "unknown"
        if not any([room_name, exit_text, inventory_count, light_source_text, visibility_text]):
            return ""
        return (
            f"current room={room_name or 'unknown'}, "
            f"inventory load={inventory_count}/6, "
            f"current turn={observation.turn or 0}, "
            f"light_source={light_source_text}, "
            f"visibility={visibility_text}, "
            f"exits=[{exit_text}]"
        )
