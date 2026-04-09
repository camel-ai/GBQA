"""
Server log analysis engine.
Detect anomalies in game session logs and debug output using hard-coded rules.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


class LogAnalyzer:
    """Analyze game session logs and debug output for anomalies."""

    # Minimum streak length to flag as anomaly
    STREAK_THRESHOLD = 3
    # Maximum seconds between consecutive commands before flagging
    TIME_GAP_THRESHOLD = 30.0
    # Keywords that indicate errors in response messages
    _ERROR_KEYWORDS = re.compile(
        r"traceback|exception|keyerror|attributeerror|typeerror|valueerror|indexerror|nameerror",
        re.IGNORECASE,
    )
    # Commands that remove items from inventory
    _INVENTORY_REMOVE_VERBS = {"drop", "put", "use", "combine", "give"}

    def analyze_session(
        self,
        session_data: Dict[str, Any],
        debug_output: str = "",
    ) -> Dict[str, Any]:
        """Run all anomaly checks on a game session log.

        Returns a structured analysis dict with anomalies and debug findings.
        """
        commands = session_data.get("commands", [])
        total_turns = session_data.get("total_turns", len(commands))

        anomalies: List[Dict[str, Any]] = []
        anomalies.extend(self._check_failed_streaks(commands))
        anomalies.extend(self._check_repeated_commands(commands))
        anomalies.extend(self._check_state_inconsistencies(commands))
        anomalies.extend(self._check_error_patterns(commands))
        anomalies.extend(self._check_time_gaps(commands))
        anomalies.extend(self._check_game_over_mismatch(session_data))

        # Sort by first affected turn
        anomalies.sort(key=lambda a: a["turns"][0] if a["turns"] else 0)

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
        """Return a filtered/paginated view of session commands."""
        commands = session_data.get("commands", [])
        filtered = commands

        if start_turn > 0:
            filtered = [c for c in filtered if c.get("turn", 0) >= start_turn]
        if end_turn > 0:
            filtered = [c for c in filtered if c.get("turn", 0) <= end_turn]
        if failures_only:
            filtered = [
                c for c in filtered if not c.get("response", {}).get("success", True)
            ]

        total = len(filtered)
        filtered = filtered[:limit]

        return {
            "commands": filtered,
            "total_commands": len(commands),
            "returned_commands": len(filtered),
            "filtered_total": total,
        }

    # ------------------------------------------------------------------
    # Anomaly detection rules
    # ------------------------------------------------------------------

    def _check_failed_streaks(self, commands: List[Dict]) -> List[Dict[str, Any]]:
        """Rule 1: Detect 3+ consecutive failed commands."""
        anomalies = []
        streak_start = -1
        streak_len = 0

        for i, cmd in enumerate(commands):
            success = cmd.get("response", {}).get("success", True)
            if not success:
                if streak_len == 0:
                    streak_start = i
                streak_len += 1
            else:
                if streak_len >= self.STREAK_THRESHOLD:
                    anomalies.append(self._build_streak_anomaly(
                        commands, streak_start, streak_len,
                    ))
                streak_len = 0

        # Handle trailing streak
        if streak_len >= self.STREAK_THRESHOLD:
            anomalies.append(self._build_streak_anomaly(
                commands, streak_start, streak_len,
            ))

        return anomalies

    def _build_streak_anomaly(
        self, commands: List[Dict], start_idx: int, length: int,
    ) -> Dict[str, Any]:
        segment = commands[start_idx : start_idx + length]
        turns = [c.get("turn", 0) for c in segment]
        evidence = [
            {
                "turn": c.get("turn", 0),
                "command": c.get("command", ""),
                "message": c.get("response", {}).get("message", "")[:120],
            }
            for c in segment
        ]
        cmds_text = ", ".join(f"'{c.get('command', '')}'" for c in segment[:5])
        return {
            "type": "failed_command_streak",
            "severity": "high" if length >= 5 else "medium",
            "turns": turns,
            "description": f"{length} consecutive failures: {cmds_text}",
            "evidence": evidence,
        }

    def _check_repeated_commands(self, commands: List[Dict]) -> List[Dict[str, Any]]:
        """Rule 2: Detect same command issued 3+ times in a row."""
        anomalies = []
        if not commands:
            return anomalies

        prev_cmd = None
        repeat_start = 0
        repeat_count = 0

        for i, cmd in enumerate(commands):
            current = cmd.get("command", "").strip().lower()
            if current == prev_cmd:
                repeat_count += 1
            else:
                if repeat_count >= self.STREAK_THRESHOLD:
                    anomalies.append(self._build_repeat_anomaly(
                        commands, repeat_start, repeat_count,
                    ))
                prev_cmd = current
                repeat_start = i
                repeat_count = 1

        if repeat_count >= self.STREAK_THRESHOLD:
            anomalies.append(self._build_repeat_anomaly(
                commands, repeat_start, repeat_count,
            ))

        return anomalies

    def _build_repeat_anomaly(
        self, commands: List[Dict], start_idx: int, count: int,
    ) -> Dict[str, Any]:
        segment = commands[start_idx : start_idx + count]
        turns = [c.get("turn", 0) for c in segment]
        cmd_text = segment[0].get("command", "") if segment else ""
        return {
            "type": "repeated_command",
            "severity": "medium",
            "turns": turns,
            "description": f"Command '{cmd_text}' repeated {count} times consecutively",
            "evidence": [
                {"turn": c.get("turn", 0), "command": c.get("command", "")}
                for c in segment
            ],
        }

    def _check_state_inconsistencies(self, commands: List[Dict]) -> List[Dict[str, Any]]:
        """Rule 3: Detect inventory/room changes without matching commands."""
        anomalies = []
        if len(commands) < 2:
            return anomalies

        for i in range(1, len(commands)):
            prev = commands[i - 1]
            curr = commands[i]
            prev_snap = prev.get("state_snapshot", {})
            curr_snap = curr.get("state_snapshot", {})
            if not prev_snap or not curr_snap:
                continue

            cmd_verb = curr.get("command", "").strip().lower().split()[0] if curr.get("command") else ""

            # Check inventory vanish (item disappears without remove command)
            prev_inv = set(prev_snap.get("inventory", []))
            curr_inv = set(curr_snap.get("inventory", []))
            vanished = prev_inv - curr_inv
            if vanished and cmd_verb not in self._INVENTORY_REMOVE_VERBS:
                anomalies.append({
                    "type": "state_inconsistency",
                    "severity": "high",
                    "turns": [prev.get("turn", 0), curr.get("turn", 0)],
                    "description": (
                        f"Items {vanished} vanished from inventory after "
                        f"'{curr.get('command', '')}' (not a remove command)"
                    ),
                    "evidence": [
                        {"turn": prev.get("turn", 0), "inventory": list(prev_inv)},
                        {"turn": curr.get("turn", 0), "inventory": list(curr_inv),
                         "command": curr.get("command", "")},
                    ],
                })

            # Check room change without go/enter command
            prev_room = prev_snap.get("room")
            curr_room = curr_snap.get("room")
            if prev_room and curr_room and prev_room != curr_room:
                if cmd_verb not in {"go", "enter", "climb", "down", "up"}:
                    anomalies.append({
                        "type": "state_inconsistency",
                        "severity": "high",
                        "turns": [prev.get("turn", 0), curr.get("turn", 0)],
                        "description": (
                            f"Room changed from '{prev_room}' to '{curr_room}' "
                            f"after '{curr.get('command', '')}' (not a movement command)"
                        ),
                        "evidence": [
                            {"turn": prev.get("turn", 0), "room": prev_room},
                            {"turn": curr.get("turn", 0), "room": curr_room,
                             "command": curr.get("command", "")},
                        ],
                    })

        return anomalies

    def _check_error_patterns(self, commands: List[Dict]) -> List[Dict[str, Any]]:
        """Rule 4: Detect error keywords in response messages."""
        anomalies = []
        for cmd in commands:
            msg = cmd.get("response", {}).get("message", "")
            if self._ERROR_KEYWORDS.search(msg):
                anomalies.append({
                    "type": "error_in_response",
                    "severity": "high",
                    "turns": [cmd.get("turn", 0)],
                    "description": f"Error pattern in response to '{cmd.get('command', '')}'",
                    "evidence": [
                        {
                            "turn": cmd.get("turn", 0),
                            "command": cmd.get("command", ""),
                            "message": msg[:200],
                        }
                    ],
                })
        return anomalies

    def _check_time_gaps(self, commands: List[Dict]) -> List[Dict[str, Any]]:
        """Rule 5: Detect abnormally long gaps between turns."""
        anomalies = []
        if len(commands) < 2:
            return anomalies

        for i in range(1, len(commands)):
            prev_ts = commands[i - 1].get("timestamp")
            curr_ts = commands[i].get("timestamp")
            if not prev_ts or not curr_ts:
                continue
            try:
                prev_dt = datetime.fromisoformat(prev_ts)
                curr_dt = datetime.fromisoformat(curr_ts)
                gap = (curr_dt - prev_dt).total_seconds()
                if gap > self.TIME_GAP_THRESHOLD:
                    anomalies.append({
                        "type": "time_gap",
                        "severity": "low",
                        "turns": [
                            commands[i - 1].get("turn", 0),
                            commands[i].get("turn", 0),
                        ],
                        "description": f"{gap:.1f}s gap between turns",
                        "evidence": [
                            {"turn": commands[i - 1].get("turn", 0), "timestamp": prev_ts},
                            {"turn": commands[i].get("turn", 0), "timestamp": curr_ts},
                        ],
                    })
            except (ValueError, TypeError):
                continue
        return anomalies

    def _check_game_over_mismatch(self, session_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Rule 6: Detect contradictions between result and game_over flag."""
        commands = session_data.get("commands", [])
        result = session_data.get("result", "in_progress")
        if not commands:
            return []

        last_cmd = commands[-1]
        game_over = last_cmd.get("response", {}).get("game_over", False)

        if game_over and result == "in_progress":
            return [{
                "type": "game_over_mismatch",
                "severity": "medium",
                "turns": [last_cmd.get("turn", 0)],
                "description": "game_over=true in last command but session result is 'in_progress'",
                "evidence": [{"turn": last_cmd.get("turn", 0), "game_over": True, "result": result}],
            }]
        if not game_over and result == "victory":
            return [{
                "type": "game_over_mismatch",
                "severity": "medium",
                "turns": [last_cmd.get("turn", 0)],
                "description": "Session result is 'victory' but last command has game_over=false",
                "evidence": [{"turn": last_cmd.get("turn", 0), "game_over": False, "result": result}],
            }]
        return []

    # ------------------------------------------------------------------
    # Debug output analysis
    # ------------------------------------------------------------------

    def _analyze_debug_output(self, debug_text: str) -> Dict[str, Any]:
        """Scan debug/print output for errors and warnings."""
        lines = debug_text.strip().splitlines()
        errors: List[Dict[str, str]] = []
        warnings: List[Dict[str, str]] = []

        error_re = re.compile(
            r"error|exception|traceback|fail", re.IGNORECASE,
        )
        warn_re = re.compile(r"warn", re.IGNORECASE)

        for i, line in enumerate(lines):
            # Extract timestamp if present: [HH:MM:SS.mmm] ...
            ts = ""
            content = line
            ts_match = re.match(r"^\[(\d{2}:\d{2}:\d{2}\.\d+)\]\s*(.*)", line)
            if ts_match:
                ts = ts_match.group(1)
                content = ts_match.group(2)

            if error_re.search(content):
                context = "\n".join(lines[max(0, i - 1) : i + 2])
                errors.append({"timestamp": ts, "line": content, "context": context})
            elif warn_re.search(content):
                warnings.append({"timestamp": ts, "line": content})

        return {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors[:10],  # Cap to avoid huge payloads
            "warnings": warnings[:10],
        }
