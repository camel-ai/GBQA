"""
Session log analysis engine.
Detect anomalies in game session logs and debug output using hard-coded rules.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List


class LogAnalyzer:
    """Analyze game session logs and debug output for anomalies."""

    STREAK_THRESHOLD = 3
    TIME_GAP_THRESHOLD = 30.0
    _ERROR_KEYWORDS = re.compile(
        r"traceback|exception|keyerror|attributeerror|typeerror|valueerror|indexerror|nameerror",
        re.IGNORECASE,
    )
    _INVENTORY_REMOVE_VERBS = {"drop", "put", "use", "combine", "give"}

    def analyze_session(
        self,
        session_data: Dict[str, Any],
        debug_output: str = "",
    ) -> Dict[str, Any]:
        """Run all anomaly checks on a game session log."""
        commands = session_data.get("commands", [])
        total_turns = session_data.get("total_turns", len(commands))

        anomalies: List[Dict[str, Any]] = []
        anomalies.extend(self._check_failed_streaks(commands))
        anomalies.extend(self._check_repeated_commands(commands))
        anomalies.extend(self._check_state_inconsistencies(commands))
        anomalies.extend(self._check_error_patterns(commands))
        anomalies.extend(self._check_time_gaps(commands))
        anomalies.extend(self._check_game_over_mismatch(session_data))
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
        session_data: Dict[str, Any],
        *,
        start_turn: int = 0,
        end_turn: int = 0,
        failures_only: bool = False,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Return a filtered view of session commands."""
        commands = session_data.get("commands", [])
        filtered = commands
        if start_turn > 0:
            filtered = [command for command in filtered if command.get("turn", 0) >= start_turn]
        if end_turn > 0:
            filtered = [command for command in filtered if command.get("turn", 0) <= end_turn]
        if failures_only:
            filtered = [
                command
                for command in filtered
                if not command.get("response", {}).get("success", True)
            ]

        total = len(filtered)
        filtered = filtered[:limit]
        return {
            "commands": filtered,
            "total_commands": len(commands),
            "returned_commands": len(filtered),
            "filtered_total": total,
        }

    def _check_failed_streaks(self, commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        streak_start = -1
        streak_len = 0

        for index, command in enumerate(commands):
            success = command.get("response", {}).get("success", True)
            if not success:
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
        commands: List[Dict[str, Any]],
        start_idx: int,
        length: int,
    ) -> Dict[str, Any]:
        segment = commands[start_idx : start_idx + length]
        turns = [command.get("turn", 0) for command in segment]
        evidence = [
            {
                "turn": command.get("turn", 0),
                "command": command.get("command", ""),
                "message": command.get("response", {}).get("message", "")[:120],
            }
            for command in segment
        ]
        commands_text = ", ".join(f"'{command.get('command', '')}'" for command in segment[:5])
        return {
            "type": "failed_command_streak",
            "severity": "high" if length >= 5 else "medium",
            "turns": turns,
            "description": f"{length} consecutive failures: {commands_text}",
            "evidence": evidence,
        }

    def _check_repeated_commands(
        self,
        commands: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        if not commands:
            return anomalies

        prev_command = None
        repeat_start = 0
        repeat_count = 0
        for index, command in enumerate(commands):
            current_command = command.get("command", "").strip().lower()
            if current_command == prev_command:
                repeat_count += 1
            else:
                if repeat_count >= self.STREAK_THRESHOLD:
                    anomalies.append(
                        self._build_repeat_anomaly(commands, repeat_start, repeat_count)
                    )
                prev_command = current_command
                repeat_start = index
                repeat_count = 1

        if repeat_count >= self.STREAK_THRESHOLD:
            anomalies.append(self._build_repeat_anomaly(commands, repeat_start, repeat_count))
        return anomalies

    def _build_repeat_anomaly(
        self,
        commands: List[Dict[str, Any]],
        start_idx: int,
        count: int,
    ) -> Dict[str, Any]:
        segment = commands[start_idx : start_idx + count]
        turns = [command.get("turn", 0) for command in segment]
        command_text = segment[0].get("command", "") if segment else ""
        return {
            "type": "repeated_command",
            "severity": "medium",
            "turns": turns,
            "description": f"Command '{command_text}' repeated {count} times consecutively",
            "evidence": [
                {"turn": command.get("turn", 0), "command": command.get("command", "")}
                for command in segment
            ],
        }

    def _check_state_inconsistencies(
        self,
        commands: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        if len(commands) < 2:
            return anomalies

        for index in range(1, len(commands)):
            previous = commands[index - 1]
            current = commands[index]
            previous_snapshot = previous.get("state_snapshot", {})
            current_snapshot = current.get("state_snapshot", {})
            if not previous_snapshot or not current_snapshot:
                continue

            command_text = str(current.get("command", "")).strip().lower()
            command_verb = command_text.split()[0] if command_text else ""

            previous_inventory = set(previous_snapshot.get("inventory", []))
            current_inventory = set(current_snapshot.get("inventory", []))
            vanished = previous_inventory - current_inventory
            if vanished and command_verb not in self._INVENTORY_REMOVE_VERBS:
                anomalies.append(
                    {
                        "type": "state_inconsistency",
                        "severity": "high",
                        "turns": [previous.get("turn", 0), current.get("turn", 0)],
                        "description": (
                            f"Items {vanished} vanished from inventory after "
                            f"'{current.get('command', '')}' (not a remove command)"
                        ),
                        "evidence": [
                            {
                                "turn": previous.get("turn", 0),
                                "inventory": list(previous_inventory),
                            },
                            {
                                "turn": current.get("turn", 0),
                                "inventory": list(current_inventory),
                                "command": current.get("command", ""),
                            },
                        ],
                    }
                )

            previous_room = previous_snapshot.get("room")
            current_room = current_snapshot.get("room")
            if previous_room and current_room and previous_room != current_room:
                if command_verb not in {"go", "enter", "climb", "down", "up"}:
                    anomalies.append(
                        {
                            "type": "state_inconsistency",
                            "severity": "high",
                            "turns": [previous.get("turn", 0), current.get("turn", 0)],
                            "description": (
                                f"Room changed from '{previous_room}' to '{current_room}' "
                                f"after '{current.get('command', '')}' (not a movement command)"
                            ),
                            "evidence": [
                                {"turn": previous.get("turn", 0), "room": previous_room},
                                {
                                    "turn": current.get("turn", 0),
                                    "room": current_room,
                                    "command": current.get("command", ""),
                                },
                            ],
                        }
                    )
        return anomalies

    def _check_error_patterns(self, commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        for command in commands:
            message = command.get("response", {}).get("message", "")
            if self._ERROR_KEYWORDS.search(message):
                anomalies.append(
                    {
                        "type": "error_in_response",
                        "severity": "high",
                        "turns": [command.get("turn", 0)],
                        "description": (
                            f"Error pattern in response to '{command.get('command', '')}'"
                        ),
                        "evidence": [
                            {
                                "turn": command.get("turn", 0),
                                "command": command.get("command", ""),
                                "message": message[:200],
                            }
                        ],
                    }
                )
        return anomalies

    def _check_time_gaps(self, commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        if len(commands) < 2:
            return anomalies

        for index in range(1, len(commands)):
            previous_timestamp = commands[index - 1].get("timestamp")
            current_timestamp = commands[index].get("timestamp")
            if not previous_timestamp or not current_timestamp:
                continue
            try:
                previous_dt = datetime.fromisoformat(previous_timestamp)
                current_dt = datetime.fromisoformat(current_timestamp)
            except (TypeError, ValueError):
                continue
            gap_seconds = (current_dt - previous_dt).total_seconds()
            if gap_seconds > self.TIME_GAP_THRESHOLD:
                anomalies.append(
                    {
                        "type": "time_gap",
                        "severity": "low",
                        "turns": [
                            commands[index - 1].get("turn", 0),
                            commands[index].get("turn", 0),
                        ],
                        "description": f"{gap_seconds:.1f}s gap between turns",
                        "evidence": [
                            {
                                "turn": commands[index - 1].get("turn", 0),
                                "timestamp": previous_timestamp,
                            },
                            {
                                "turn": commands[index].get("turn", 0),
                                "timestamp": current_timestamp,
                            },
                        ],
                    }
                )
        return anomalies

    def _check_game_over_mismatch(
        self,
        session_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        commands = session_data.get("commands", [])
        result = session_data.get("result", "in_progress")
        if not commands:
            return []

        last_command = commands[-1]
        game_over = last_command.get("response", {}).get("game_over", False)
        if game_over and result == "in_progress":
            return [
                {
                    "type": "game_over_mismatch",
                    "severity": "medium",
                    "turns": [last_command.get("turn", 0)],
                    "description": (
                        "game_over=true in last command but session result is 'in_progress'"
                    ),
                    "evidence": [
                        {
                            "turn": last_command.get("turn", 0),
                            "game_over": True,
                            "result": result,
                        }
                    ],
                }
            ]
        if not game_over and result == "victory":
            return [
                {
                    "type": "game_over_mismatch",
                    "severity": "medium",
                    "turns": [last_command.get("turn", 0)],
                    "description": (
                        "Session result is 'victory' but last command has game_over=false"
                    ),
                    "evidence": [
                        {
                            "turn": last_command.get("turn", 0),
                            "game_over": False,
                            "result": result,
                        }
                    ],
                }
            ]
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
                errors.append(
                    {"timestamp": timestamp, "line": content, "context": context}
                )
            elif warning_pattern.search(content):
                warnings.append({"timestamp": timestamp, "line": content})

        return {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors[:10],
            "warnings": warnings[:10],
        }
