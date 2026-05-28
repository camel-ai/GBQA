"""
Session log analysis engine.
Detect anomalies in environment session logs and debug output using normalized data structures.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .log_types import (
    DefaultLogAdapter,
    LogAdapter,
    NormalizedCommand,
    NormalizedSession,
)


class LogAnalyzer:
    """Analyze environment session logs and debug output for anomalies."""

    STREAK_THRESHOLD = 3
    TIME_GAP_THRESHOLD = 30.0
    _ERROR_KEYWORDS = re.compile(
        r"traceback|exception|keyerror|attributeerror|typeerror|valueerror|indexerror|nameerror",
        re.IGNORECASE,
    )

    def __init__(self, adapter: Optional[LogAdapter] = None):
        self.adapter = adapter or DefaultLogAdapter()

    def analyze_session(
        self,
        session_data: Dict[str, Any] | NormalizedSession,
        debug_output: str = "",
    ) -> Dict[str, Any]:
        """Run all anomaly checks on an environment session log."""
        if isinstance(session_data, dict):
            session = self.adapter.normalize_session(session_data)
        else:
            session = session_data

        if self.adapter:
            debug_output = self.adapter.normalize_debug_output(debug_output)

        commands = session.commands
        total_turns = session.total_turns

        anomalies: List[Dict[str, Any]] = []
        anomalies.extend(self._check_failed_streaks(commands))
        anomalies.extend(self._check_repeated_commands(commands))
        anomalies.extend(self._check_state_inconsistencies(commands))
        anomalies.extend(self._check_error_patterns(commands))
        anomalies.extend(self._check_time_gaps(commands))
        anomalies.extend(self._check_terminal_mismatch(session))
        
        # Sort by turn number
        anomalies.sort(key=lambda anomaly: anomaly["turns"][0] if anomaly["turns"] else 0)

        debug_findings = self._analyze_debug_output(debug_output) if debug_output else {}
        anomaly_count = len(anomalies)
        
        summary = f"Found {anomaly_count} anomalies in {total_turns}-turn session"
        if debug_findings.get("error_count", 0) > 0:
            summary += f", {debug_findings['error_count']} server errors"

        return {
            "summary": summary,
            "total_turns": total_turns,
            "anomaly_count": anomaly_count,
            "anomalies": anomalies,
            "debug_findings": debug_findings,
        }

    def filter_commands(
        self,
        session_data: Dict[str, Any] | NormalizedSession,
        *,
        start_turn: int = 0,
        end_turn: int = 0,
        failures_only: bool = False,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Return a filtered view of session commands."""
        if isinstance(session_data, dict):
            session = self.adapter.normalize_session(session_data)
        else:
            session = session_data

        filtered = session.commands
        if start_turn > 0:
            filtered = [cmd for cmd in filtered if cmd.turn >= start_turn]
        if end_turn > 0:
            filtered = [cmd for cmd in filtered if cmd.turn <= end_turn]
        if failures_only:
            filtered = [cmd for cmd in filtered if not cmd.success]

        total = len(filtered)
        paged = filtered[:limit]
        
        # Convert back to dicts for tool response consistency
        return {
            "commands": [
                {
                    "turn": cmd.turn,
                    "command": cmd.command,
                    "response": {"success": cmd.success, "message": cmd.message},
                }
                for cmd in paged
            ],
            "total_commands": len(session.commands),
            "returned_commands": len(paged),
            "filtered_total": total,
        }

    def _check_failed_streaks(self, commands: List[NormalizedCommand]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        streak_start = -1
        streak_len = 0

        for index, cmd in enumerate(commands):
            if not cmd.success:
                if streak_len == 0:
                    streak_start = index
                streak_len += 1
            else:
                if streak_len >= self.STREAK_THRESHOLD:
                    anomalies.append(
                        self._build_streak_anomaly(commands, streak_start, streak_len)
                    )
                streak_len = 0

        if streak_len >= self.STREAK_THRESHOLD:
            anomalies.append(self._build_streak_anomaly(commands, streak_start, streak_len))
        return anomalies

    def _build_streak_anomaly(
        self,
        commands: List[NormalizedCommand],
        start_idx: int,
        length: int,
    ) -> Dict[str, Any]:
        segment = commands[start_idx : start_idx + length]
        return {
            "type": "failed_command_streak",
            "severity": "high" if length >= 5 else "medium",
            "turns": [cmd.turn for cmd in segment],
            "description": f"{length} consecutive failures: " + 
                           ", ".join(f"'{cmd.command}'" for cmd in segment[:5]),
            "evidence": [
                {
                    "turn": cmd.turn,
                    "command": cmd.command,
                    "message": cmd.message[:120],
                }
                for cmd in segment
            ],
        }

    def _check_repeated_commands(self, commands: List[NormalizedCommand]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        if not commands:
            return anomalies

        prev_cmd_text = None
        repeat_start = 0
        repeat_count = 0
        
        for index, cmd in enumerate(commands):
            curr_text = cmd.command.strip().lower()
            if curr_text == prev_cmd_text:
                repeat_count += 1
            else:
                if repeat_count >= self.STREAK_THRESHOLD:
                    anomalies.append(
                        self._build_repeat_anomaly(commands, repeat_start, repeat_count)
                    )
                prev_cmd_text = curr_text
                repeat_start = index
                repeat_count = 1

        if repeat_count >= self.STREAK_THRESHOLD:
            anomalies.append(self._build_repeat_anomaly(commands, repeat_start, repeat_count))
        return anomalies

    def _build_repeat_anomaly(
        self,
        commands: List[NormalizedCommand],
        start_idx: int,
        count: int,
    ) -> Dict[str, Any]:
        segment = commands[start_idx : start_idx + count]
        return {
            "type": "repeated_command",
            "severity": "medium",
            "turns": [cmd.turn for cmd in segment],
            "description": f"Command '{segment[0].command}' repeated {count} times consecutively",
            "evidence": [{"turn": cmd.turn, "command": cmd.command} for cmd in segment],
        }

    def _check_state_inconsistencies(self, commands: List[NormalizedCommand]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        if len(commands) < 2:
            return anomalies

        removal_verbs = self.adapter.get_removal_verbs()
        movement_verbs = self.adapter.get_movement_verbs()

        for i in range(1, len(commands)):
            prev, curr = commands[i - 1], commands[i]
            if not prev.state or not curr.state:
                continue

            # Check inventory shrinkage
            prev_inv = set(prev.state.inventory)
            curr_inv = set(curr.state.inventory)
            vanished = prev_inv - curr_inv
            
            verb = curr.command.strip().lower().split()[0] if curr.command else ""
            
            if vanished and verb not in removal_verbs:
                anomalies.append({
                    "type": "state_inconsistency",
                    "severity": "high",
                    "turns": [prev.turn, curr.turn],
                    "description": f"Items {vanished} vanished from inventory after '{curr.command}' (not a remove verb)",
                    "evidence": [
                        {"turn": prev.turn, "inventory": list(prev_inv)},
                        {"turn": curr.turn, "inventory": list(curr_inv), "command": curr.command},
                    ]
                })

            # Check unexpected location changes
            if prev.state.location and curr.state.location and prev.state.location != curr.state.location:
                if verb not in movement_verbs:
                    anomalies.append({
                        "type": "state_inconsistency",
                        "severity": "high",
                        "turns": [prev.turn, curr.turn],
                        "description": f"Location changed from '{prev.state.location}' to '{curr.state.location}' "
                                       f"after '{curr.command}' (not a movement verb)",
                        "evidence": [
                            {"turn": prev.turn, "location": prev.state.location},
                            {"turn": curr.turn, "location": curr.state.location, "command": curr.command},
                        ]
                    })
        return anomalies

    def _check_error_patterns(self, commands: List[NormalizedCommand]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        for cmd in commands:
            if self._ERROR_KEYWORDS.search(cmd.message):
                anomalies.append({
                    "type": "error_in_response",
                    "severity": "high",
                    "turns": [cmd.turn],
                    "description": f"Error pattern in response to '{cmd.command}'",
                    "evidence": [{
                        "turn": cmd.turn,
                        "command": cmd.command,
                        "message": cmd.message[:200],
                    }]
                })
        return anomalies

    def _check_time_gaps(self, commands: List[NormalizedCommand]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        if len(commands) < 2:
            return anomalies

        for i in range(1, len(commands)):
            prev, curr = commands[i - 1], commands[i]
            if not prev.timestamp or not curr.timestamp:
                continue
            
            gap = (curr.timestamp - prev.timestamp).total_seconds()
            if gap > self.TIME_GAP_THRESHOLD:
                anomalies.append({
                    "type": "time_gap",
                    "severity": "low",
                    "turns": [prev.turn, curr.turn],
                    "description": f"{gap:.1f}s gap between turns",
                    "evidence": [
                        {"turn": prev.turn, "timestamp": prev.timestamp.isoformat()},
                        {"turn": curr.turn, "timestamp": curr.timestamp.isoformat()},
                    ]
                })
        return anomalies

    def _check_terminal_mismatch(self, session: NormalizedSession) -> List[Dict[str, Any]]:
        if not session.commands:
            return []

        last_cmd = session.commands[-1]
        if last_cmd.terminal and session.result == "in_progress":
            return [{
                "type": "terminal_state_mismatch",
                "severity": "medium",
                "turns": [last_cmd.turn],
                "description": "terminal=true in last command but session result is 'in_progress'",
                "evidence": [{"turn": last_cmd.turn, "terminal": True, "result": session.result}]
            }]
        
        if not last_cmd.terminal and session.result == "victory":
            return [{
                "type": "terminal_state_mismatch",
                "severity": "medium",
                "turns": [last_cmd.turn],
                "description": "Session result is 'victory' but last command has terminal=false",
                "evidence": [{"turn": last_cmd.turn, "terminal": False, "result": session.result}]
            }]
        return []

    def _analyze_debug_output(self, debug_text: str) -> Dict[str, Any]:
        lines = debug_text.strip().splitlines()
        errors: List[Dict[str, str]] = []
        warnings: List[Dict[str, str]] = []

        error_pattern = re.compile(r"error|exception|traceback|fail", re.IGNORECASE)
        warning_pattern = re.compile(r"warn", re.IGNORECASE)

        for index, line in enumerate(lines):
            timestamp = ""
            content = line
            timestamp_match = re.match(r"^\[(\d{2}:\d{2}:\d{2}\.\d+)\]\s*(.*)", line)
            if timestamp_match:
                timestamp = timestamp_match.group(1)
                content = timestamp_match.group(2)

            if error_pattern.search(content):
                context = "\n".join(lines[max(0, index - 1) : index + 2])
                errors.append({"timestamp": timestamp, "line": content, "context": context})
            elif warning_pattern.search(content):
                warnings.append({"timestamp": timestamp, "line": content})

        return {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors[:10],
            "warnings": warnings[:10],
        }
