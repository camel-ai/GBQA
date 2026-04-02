"""Core QA Agent loop."""

from __future__ import annotations

import json
import re
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
from .types import Action, BugFinding, Observation, RunReport, StepRecord


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

            # Auto-trigger code lookup + white-box debug when bug confidence is high
            auto_code_note = ""
            auto_debug_note = ""
            if (
                action.bug_exist
                and action.confidence >= self._confidence_threshold
                and self._has_code_tools()
            ):
                lookup_result = self._auto_code_lookup(action)
                auto_code_note = lookup_result["note"]
                if lookup_result.get("file_path") and self._has_write_tools():
                    auto_debug_note = self._auto_white_box_debug(
                        action, game_session_id, lookup_result
                    )

            is_code_tool = action.tool.startswith("code_")
            raw_response = self._invoke_tool(action, game_session_id)

            if is_code_tool:
                current_observation = Observation(
                    success=raw_response.get("success", True),
                    message=self._format_code_response(raw_response),
                    state=current_observation.state,
                    turn=current_observation.turn,
                )
            else:
                current_observation = self._parser.parse(raw_response)

            record = StepRecord(
                step=step,
                action=action,
                observation=current_observation,
                planner_prompt=plan.prompt,
                planner_output=plan.output,
                notes="\n".join(filter(None, [auto_code_note, auto_debug_note])),
            )
            report.steps.append(record)

            if is_code_tool:
                findings: List[BugFinding] = []
            else:
                findings = self._detector.inspect(action, current_observation)
                for bug in findings:
                    report.bugs.append(bug)
                    self._memory.record_bug(bug, step)
                    self._reporter.log_bug(bug, step)

            if is_code_tool or current_observation.success:
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
                reflection_note = self._reflection_analyzer.format_note(reflection)
                record.notes = (
                    f"{record.notes}\n{reflection_note}".strip()
                    if record.notes
                    else reflection_note
                )
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

    def _invoke_tool(
        self, action: Action, game_session_id: str
    ) -> Dict[str, Any]:
        """Dispatch to the appropriate tool based on ``action.tool``."""
        if action.tool == "code_list_files":
            payload: Dict[str, Any] = {}
        elif action.tool == "code_read_file":
            payload = self._parse_code_read_params(action.command)
        elif action.tool == "code_search":
            payload = {"pattern": action.command}
        elif action.tool == "code_write_file":
            try:
                payload = self._parse_code_write_params(action.command)
            except ValueError as exc:
                return {"success": False, "message": str(exc)}
        elif action.tool == "code_read_debug_logs":
            payload = {"clear": action.command.strip().lower() == "clear"}
        elif action.tool == "code_restore_file":
            payload = {"path": action.command.strip()}
        else:
            payload = {"game_id": game_session_id, "command": action.command}
        return self._tool_registry.invoke(action.tool, payload)

    @staticmethod
    def _parse_code_read_params(command: str) -> Dict[str, Any]:
        """Parse ``"path/to/file.py:10-50"`` into tool payload."""
        match = re.match(r"^(.+?):(\d+)-(\d+)$", command.strip())
        if match:
            return {
                "path": match.group(1),
                "start_line": int(match.group(2)),
                "end_line": int(match.group(3)),
            }
        return {"path": command.strip()}

    @staticmethod
    def _parse_code_write_params(command: str) -> Dict[str, Any]:
        """Parse ``"path:search->replace"`` or JSON from command."""
        cmd = command.strip()
        if cmd.startswith("{"):
            try:
                return json.loads(cmd)
            except Exception as exc:
                raise ValueError(f"Invalid JSON payload for code_write_file: {exc}") from exc

        # Format: path:search_text->replace_text
        # Split on first ":" to isolate the file path, then on first "->"
        # to separate search / replace.  This is more robust than a single
        # regex when the search or replace text itself contains ":" or "->".
        colon_idx = cmd.find(":")
        if colon_idx == -1:
            raise ValueError(
                "Invalid code_write_file command. Use 'path:old_text->new_text' or a JSON payload."
            )
        path = cmd[:colon_idx]
        rest = cmd[colon_idx + 1:]
        arrow_idx = rest.find("->")
        if arrow_idx == -1:
            raise ValueError(
                "Invalid code_write_file command. Use 'path:old_text->new_text' or a JSON payload."
            )
        return {
            "path": path,
            "patch": {
                "search": rest[:arrow_idx],
                "replace": rest[arrow_idx + 2:],
            },
        }

    @staticmethod
    def _format_code_response(raw: Dict[str, Any]) -> str:
        """Format a code-tool API response into readable text."""
        if not raw.get("success", False):
            return f"[Code tool error] {raw.get('message', 'Unknown error')}"
        if "files" in raw:
            lines = [f"  {f['path']}  ({f['size']} bytes)" for f in raw["files"]]
            return "Source files:\n" + "\n".join(lines)
        if "content" in raw:
            header = f"File: {raw.get('path', '?')} (lines {raw.get('start_line')}-{raw.get('end_line')} of {raw.get('total_lines')})"
            return f"{header}\n{raw['content']}"
        if "matches" in raw:
            if not raw["matches"]:
                return f"No matches for pattern: {raw.get('pattern', '')}"
            lines = [
                f"  {m['path']}:{m['line']}  {m['text']}" for m in raw["matches"]
            ]
            return f"Search results for '{raw.get('pattern', '')}':\n" + "\n".join(lines)
        if "logs" in raw:
            logs = raw["logs"]
            if not logs.strip():
                return "Debug logs are empty."
            return f"--- Debug Logs ---\n{logs}\n------------------"
        if "message" in raw:
            return str(raw["message"])
        return str(raw)

    _KNOWN_GAME_VERBS = frozenset({
        "go", "look", "examine", "take", "drop", "put", "open", "close",
        "use", "light", "unlock", "read", "combine", "climb", "oil",
        "enter", "inventory", "help",
    })

    def _has_code_tools(self) -> bool:
        """Return True when code-reading tools are registered."""
        return any(t.name == "code_search" for t in self._tool_registry.list_tools())

    def _has_write_tools(self) -> bool:
        """Return True when white-box debug tools are registered."""
        names = {t.name for t in self._tool_registry.list_tools()}
        return "code_write_file" in names and "code_restore_file" in names

    def _auto_code_lookup(self, action: Action) -> Dict[str, Any]:
        """Auto-trigger code search + read when the planner reports a high-confidence bug.

        Returns a dict with keys:
          - note: formatted text for StepRecord.notes
          - file_path: path of the first match (or None)
          - match_line: line number of the first match (or None)
          - handler_signature: the matched line text (or None)
          - verb: the extracted game verb
        """
        query = self._extract_code_search_query(action)
        empty = {"note": "", "file_path": None, "match_line": None,
                 "handler_signature": None, "verb": ""}
        if not query:
            return empty

        verb = action.command.strip().lower().split()[0] if action.command.strip() else ""

        search_response = self._tool_registry.invoke("code_search", {"pattern": query})
        search_text = self._format_code_response(search_response)

        read_text = ""
        file_path = None
        match_line = None
        handler_signature = None
        matches = search_response.get("matches", [])
        if matches:
            first = matches[0]
            file_path = first["path"]
            match_line = first["line"]
            handler_signature = first["text"]
            start = max(1, first["line"] - 15)
            end = first["line"] + 15
            read_response = self._tool_registry.invoke("code_read_file", {
                "path": first["path"],
                "start_line": start,
                "end_line": end,
            })
            read_text = self._format_code_response(read_response)

        parts = [f"[Auto code lookup for '{query}']", search_text]
        if read_text:
            parts.append(read_text)
        return {
            "note": "\n".join(parts),
            "file_path": file_path,
            "match_line": match_line,
            "handler_signature": handler_signature,
            "verb": verb,
        }

    @classmethod
    def _extract_code_search_query(cls, action: Action) -> str:
        """Derive a source-code search pattern from the game command."""
        cmd = action.command.strip().lower()
        verb = cmd.split()[0] if cmd else ""
        if verb in cls._KNOWN_GAME_VERBS:
            return f"def handle_{verb}"
        return cmd if len(cmd) <= 40 else cmd[:40]

    def _auto_white_box_debug(
        self,
        action: Action,
        game_session_id: str,
        lookup_result: Dict[str, Any],
    ) -> str:
        """Auto-trigger white-box debugging: inject print → replay command → read logs → restore.

        Only called when ``_auto_code_lookup`` found a matching handler.
        """
        file_path = lookup_result["file_path"]
        signature = lookup_result["handler_signature"]
        verb = lookup_result["verb"]
        if not file_path or not signature:
            return ""

        # Build the debug print line (8-space indent to match method body)
        debug_print = f'        print(f"[AUTO_DEBUG] handle_{verb} called, command={{command}}")'
        patch_search = signature
        patch_replace = f"{signature}\n{debug_print}"

        parts = [f"[Auto white-box debug for handle_{verb}]"]

        # Clear old logs first
        self._tool_registry.invoke("code_read_debug_logs", {"clear": True})

        restore_needed = False
        try:
            # 1. Inject debug print
            write_resp = self._tool_registry.invoke("code_write_file", {
                "path": file_path,
                "patch": {"search": patch_search, "replace": patch_replace},
            })
            if not write_resp.get("success", False):
                parts.append(f"Write failed: {write_resp.get('message', 'unknown error')}")
                return "\n".join(parts)
            restore_needed = True
            parts.append(f"Injected debug print into {file_path}")

            # 2. Replay the game command
            game_resp = self._tool_registry.invoke(
                "game_command",
                {"game_id": game_session_id, "command": action.command},
            )
            game_msg = game_resp.get("message", str(game_resp))
            parts.append(f"Replay '{action.command}': {game_msg[:200]}")

            # 3. Read debug logs
            log_resp = self._tool_registry.invoke("code_read_debug_logs", {"clear": False})
            logs = log_resp.get("logs", "")
            if logs.strip():
                parts.append(f"Debug output:\n{logs.strip()}")
            else:
                parts.append("Debug output: (empty)")
        finally:
            # 4. Always restore
            if restore_needed:
                try:
                    restore_resp = self._tool_registry.invoke(
                        "code_restore_file", {"path": file_path}
                    )
                    parts.append(f"Restored {file_path}: {restore_resp.get('message', '')}")
                except Exception:
                    parts.append(f"WARNING: failed to restore {file_path}")

        return "\n".join(parts)

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
