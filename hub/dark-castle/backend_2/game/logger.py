"""
Game logging module.
Record the full interaction history for each play session.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class GameLogger:
    """Persist session logs to the game-level cache directory."""

    def __init__(self, log_dir: str | Path | None = None):
        cache_root = Path(__file__).resolve().parents[2] / ".cache"
        self.cache_root = cache_root
        self.data_dir = cache_root / "data"
        self.log_dir = Path(log_dir) if log_dir is not None else cache_root / "log"

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.current_log_file: Optional[Path] = None
        self.game_id: Optional[str] = None
        self.session_data: Dict[str, Any] = {}

    def start_new_session(self, game_id: str) -> str:
        """Create a new log file for a game session."""
        self.game_id = game_id

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"game_{timestamp}_{game_id[:8]}.json"
        self.current_log_file = self.log_dir / filename

        self.session_data = {
            "game_id": game_id,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "game_name": "Dark Castle: Night of Awakening",
            "version": "1.0.0",
            "result": "in_progress",
            "total_turns": 0,
            "commands": [],
            "initial_state": None,
            "final_state": None,
        }

        self._save_log()
        return str(self.current_log_file)

    def log_initial_state(self, state: Dict[str, Any]):
        """Record the initial visible state."""
        self.session_data["initial_state"] = state
        self._save_log()

    def log_command(
        self,
        command: str,
        response: Dict[str, Any],
        turn: int,
        state: Dict[str, Any] = None,
    ):
        """Append a command/response pair to the current log."""
        entry = {
            "turn": turn,
            "timestamp": datetime.now().isoformat(),
            "command": command,
            "response": {
                "success": response.get("success", False),
                "message": response.get("message", ""),
                "game_over": response.get("game_over", False),
            },
        }

        if state:
            entry["state_snapshot"] = {
                "room": state.get("room", {}).get("id") if state.get("room") else None,
                "inventory": [item.get("id") for item in state.get("inventory", [])],
                "flags": state.get("flags", {}),
            }

        self.session_data["commands"].append(entry)
        self.session_data["total_turns"] = turn

        if response.get("game_over"):
            self.session_data["result"] = "victory"
            self.end_session(state)
        else:
            self._save_log()

    def end_session(self, final_state: Dict[str, Any] = None, result: str = None):
        """Close out the current session log."""
        self.session_data["end_time"] = datetime.now().isoformat()

        if result:
            self.session_data["result"] = result

        if final_state:
            self.session_data["final_state"] = final_state

        self._save_log()

    def _save_log(self):
        """Write the current session data to disk."""
        if self.current_log_file:
            try:
                with open(self.current_log_file, "w", encoding="utf-8") as file:
                    json.dump(self.session_data, file, ensure_ascii=False, indent=2)
            except Exception as exc:
                print(f"[Logger] Failed to save log: {exc}")

    def get_log_file_path(self) -> Optional[str]:
        """Return the path of the active log file."""
        return str(self.current_log_file) if self.current_log_file else None

    def list_logs(self) -> list:
        """List all stored game logs."""
        logs = []
        for file in sorted(self.log_dir.glob("game_*.json"), reverse=True):
            try:
                with open(file, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                logs.append(
                    {
                        "filename": file.name,
                        "game_id": data.get("game_id"),
                        "start_time": data.get("start_time"),
                        "result": data.get("result"),
                        "total_turns": data.get("total_turns", 0),
                    }
                )
            except Exception:
                continue
        return logs

    def get_log(self, filename: str) -> Optional[Dict[str, Any]]:
        """Read a single stored log by filename."""
        log_path = self.log_dir / filename
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8") as file:
                    return json.load(file)
            except Exception:
                return None
        return None


game_logger = GameLogger()
