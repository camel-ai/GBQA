"""
Flask API service.
Expose the game backend to the web frontend and agent clients.
"""

import os
import re
import secrets
import builtins
import contextvars
import sys
import io
import importlib
import threading
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS

from game.engine import GameEngine, create_new_game, game_sessions
from game.logger import GameLogger

CODE_ROOT = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT_REAL = os.path.realpath(CODE_ROOT)
_ALLOWED_EXTENSIONS = {".py", ".json"}
_SKIP_DIRS = {"__pycache__", "venv", ".venv", "node_modules", ".git", "path"}

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

# Debug log buffers for agent-based debugging.
class DebugBuffer(io.StringIO):
    def write(self, s):
        if s.strip():
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            super().write(f"[{timestamp}] {s.rstrip()}\n")
        else:
            super().write(s)
        return len(s)

debug_outputs: dict[str, DebugBuffer] = {}
debug_outputs_lock = threading.Lock()
active_debug_game_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "active_debug_game_id", default=None
)
code_write_backups: dict[str, str] = {}
original_print = builtins.print


def _get_debug_buffer(game_id: str) -> DebugBuffer:
    with debug_outputs_lock:
        return debug_outputs.setdefault(game_id, DebugBuffer())


def _clear_debug_buffer(game_id: str) -> None:
    buffer = _get_debug_buffer(game_id)
    buffer.truncate(0)
    buffer.seek(0)


def _read_debug_buffer(game_id: str) -> str:
    return _get_debug_buffer(game_id).getvalue()


class _DebugCapture:
    """Context manager that scopes captured print output to a game id."""

    def __init__(self, game_id: str) -> None:
        self._game_id = game_id
        self._token: contextvars.Token[str | None] | None = None

    def __enter__(self) -> None:
        self._token = active_debug_game_id.set(self._game_id)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            active_debug_game_id.reset(self._token)


def _debug_print(*args, **kwargs):
    """Mirror normal print behavior while capturing agent debug output per game."""
    original_print(*args, **kwargs)
    game_id = active_debug_game_id.get()
    if not game_id:
        return

    target = kwargs.get("file")
    if target not in (None, sys.stdout, sys.stderr):
        return

    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    text = sep.join(str(arg) for arg in args) + end
    _get_debug_buffer(game_id).write(text)


builtins.print = _debug_print

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.secret_key = secrets.token_hex(32)
CORS(app, supports_credentials=True)


@app.route("/")
def serve_index():
    """Serve the main frontend page."""
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/css/<path:filename>")
def serve_css(filename):
    """Serve frontend CSS assets."""
    return send_from_directory(os.path.join(FRONTEND_DIR, "css"), filename)


@app.route("/js/<path:filename>")
def serve_js(filename):
    """Serve frontend JavaScript assets."""
    return send_from_directory(os.path.join(FRONTEND_DIR, "js"), filename)


def get_game_engine() -> GameEngine:
    """Return the game engine bound to the current browser session."""
    session_id = session.get("game_id")
    if session_id and session_id in game_sessions:
        return game_sessions[session_id]
    return None


@app.route("/api/game/new", methods=["POST"])
def new_game():
    """Create a new browser-session game."""
    game_id, engine = create_new_game()
    session["game_id"] = game_id

    result = engine.get_state()
    intro = engine._get_initial_response()

    return jsonify(
        {
            "success": True,
            "game_id": game_id,
            "message": intro["message"],
            "state": result["state"],
        }
    )


@app.route("/api/game/command", methods=["POST"])
def process_command():
    """Process a command for the current browser-session game."""
    engine = get_game_engine()
    if not engine:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "There is no active game session. Start a new game first.",
                    "state": None,
                }
            ),
            400,
        )

    data = request.get_json()
    if not data or "command" not in data:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Please provide a command.",
                    "state": None,
                }
            ),
            400,
        )

    return jsonify(engine.process_command(data["command"]))


@app.route("/api/game/state", methods=["GET"])
def get_state():
    """Return the current browser-session game state."""
    engine = get_game_engine()
    if not engine:
        return jsonify({"initialized": False, "message": "There is no active game session."})
    return jsonify(engine.get_state())


@app.route("/api/game/actions", methods=["GET"])
def get_valid_actions():
    """Return currently available actions for the active session."""
    engine = get_game_engine()
    if not engine:
        return jsonify({"valid_actions": [], "message": "There is no active game session."})
    return jsonify(engine.get_valid_actions())


@app.route("/api/game/reset", methods=["POST"])
def reset_game():
    """Reset the current browser-session game."""
    old_game_id = session.get("game_id")
    if old_game_id and old_game_id in game_sessions:
        del game_sessions[old_game_id]
    return new_game()


@app.route("/api/health", methods=["GET"])
def health_check():
    """Health-check endpoint."""
    return jsonify(
        {
            "status": "healthy",
            "game": "Dark Castle: Night of Awakening",
            "version": "1.0.0",
        }
    )


@app.route("/api/agent/new", methods=["POST"])
def agent_new_game():
    """Create a new agent-driven game without relying on browser session state."""
    game_id, engine = create_new_game()
    _clear_debug_buffer(game_id)
    intro = engine._get_initial_response()

    return jsonify(
        {
            "success": True,
            "game_id": game_id,
            "message": intro["message"],
            "state": engine.get_state()["state"],
            "full_state": engine.get_state()["full_state"],
        }
    )


@app.route("/api/agent/command", methods=["POST"])
def agent_command():
    """Process a command for an agent-managed game id."""
    data = request.get_json()
    if not data or "game_id" not in data:
        return jsonify({"success": False, "message": "Please provide game_id."}), 400

    game_id = data["game_id"]
    if game_id not in game_sessions:
        return jsonify({"success": False, "message": "Invalid game_id."}), 400

    if "command" not in data:
        return jsonify({"success": False, "message": "Please provide a command."}), 400

    engine = game_sessions[game_id]
    with _DebugCapture(game_id):
        result = engine.process_command(data["command"])
    result["full_state"] = engine.get_state()["full_state"]
    return jsonify(result)


@app.route("/api/agent/state/<game_id>", methods=["GET"])
def agent_get_state(game_id):
    """Return the state for a specific agent-managed game."""
    if game_id not in game_sessions:
        return jsonify({"success": False, "message": "Invalid game_id."}), 400
    return jsonify(game_sessions[game_id].get_state())


@app.route("/api/logs", methods=["GET"])
def list_logs():
    """List all stored game logs."""
    logger = GameLogger()
    logs = logger.list_logs()
    return jsonify({"success": True, "logs": logs, "total": len(logs)})


@app.route("/api/logs/<filename>", methods=["GET"])
def get_log(filename):
    """Fetch a single stored game log by filename."""
    logger = GameLogger()
    log_data = logger.get_log(filename)

    if log_data:
        return jsonify({"success": True, "data": log_data})
    return jsonify({"success": False, "message": "Log file does not exist."}), 404


@app.route("/api/logs/current/<game_id>", methods=["GET"])
def get_current_log(game_id):
    """Return the active log for a running game id."""
    if game_id not in game_sessions:
        return jsonify({"success": False, "message": "Invalid game_id."}), 400

    engine = game_sessions[game_id]
    if engine.logger:
        return jsonify(
            {
                "success": True,
                "log_file": engine.logger.get_log_file_path(),
                "data": engine.logger.session_data,
            }
        )

    return jsonify({"success": False, "message": "There is no active log."}), 404


def _safe_code_path(requested: str) -> str | None:
    """Resolve *requested* to an absolute path under CODE_ROOT.

    Returns ``None`` when the path escapes CODE_ROOT or has a
    disallowed extension.
    """
    cleaned = requested.replace("\\", "/")
    if ".." in cleaned.split("/"):
        return None
    full = os.path.realpath(os.path.join(CODE_ROOT, cleaned))
    try:
        if os.path.commonpath([full, CODE_ROOT_REAL]) != CODE_ROOT_REAL:
            return None
    except ValueError:
        return None
    _, ext = os.path.splitext(full)
    if ext not in _ALLOWED_EXTENSIONS:
        return None
    return full


def _reload_runtime_for_path(path: str) -> None:
    """Best-effort hot reload for edited runtime game modules."""
    normalized = path.replace("\\", "/")
    if not normalized.startswith("game/") or not normalized.endswith(".py"):
        return

    module_name = normalized[:-3].replace("/", ".")
    module = importlib.import_module(module_name)
    reloaded = importlib.reload(module)

    if module_name == "game.actions":
        action_handler_cls = reloaded.ActionHandler
        for engine in game_sessions.values():
            if engine.world is not None:
                engine.action_handler = action_handler_cls(engine.world)

    if module_name == "game.parser":
        parser_cls = reloaded.CommandParser
        for engine in game_sessions.values():
            engine.parser = parser_cls()

    if module_name == "game.engine":
        engine_cls = reloaded.GameEngine
        for game_id, engine in list(game_sessions.items()):
            if not isinstance(engine, engine_cls):
                continue
            if engine.world is not None:
                import game.actions as actions_module
                import game.parser as parser_module

                engine.parser = parser_module.CommandParser()
                engine.action_handler = actions_module.ActionHandler(engine.world)


@app.route("/api/agent/code/files", methods=["GET"])
def agent_code_list_files():
    """List source code files available for reading."""
    files = []
    for dirpath, dirnames, filenames in os.walk(CODE_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            _, ext = os.path.splitext(fname)
            if ext not in _ALLOWED_EXTENSIONS:
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, CODE_ROOT)
            files.append({"path": rel, "size": os.path.getsize(full)})
    files.sort(key=lambda f: f["path"])
    return jsonify({"success": True, "files": files})


@app.route("/api/agent/code/read", methods=["POST"])
def agent_code_read_file():
    """Read source code of a specific file."""
    data = request.get_json() or {}
    path = data.get("path", "")
    if not path:
        return jsonify({"success": False, "message": "Please provide a file path."}), 400

    full = _safe_code_path(path)
    if full is None or not os.path.isfile(full):
        return jsonify({"success": False, "message": f"File not found or not allowed: {path}"}), 404

    with open(full, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    start_line = max(int(data.get("start_line", 1)), 1)
    end_line = int(data.get("end_line", 0)) or len(lines)
    end_line = min(end_line, len(lines))

    selected = lines[start_line - 1 : end_line]
    numbered = "".join(
        f"{start_line + i:>4}  {line}" for i, line in enumerate(selected)
    )

    return jsonify({
        "success": True,
        "path": path,
        "content": numbered,
        "start_line": start_line,
        "end_line": end_line,
        "total_lines": len(lines),
    })


@app.route("/api/agent/code/search", methods=["POST"])
def agent_code_search():
    """Search for a pattern across source code files."""
    data = request.get_json() or {}
    pattern = data.get("pattern", "")
    if not pattern:
        return jsonify({"success": False, "message": "Please provide a search pattern."}), 400

    max_results = int(data.get("max_results", 30))
    matches = []
    for dirpath, dirnames, filenames in os.walk(CODE_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            _, ext = os.path.splitext(fname)
            if ext not in _ALLOWED_EXTENSIONS:
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, CODE_ROOT)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if re.search(pattern, line):
                            matches.append({
                                "path": rel,
                                "line": lineno,
                                "text": line.rstrip("\n"),
                            })
                            if len(matches) >= max_results:
                                break
            except re.error:
                return jsonify({"success": False, "message": f"Invalid regex pattern: {pattern}"}), 400
            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    return jsonify({"success": True, "pattern": pattern, "matches": matches, "total": len(matches)})


@app.route("/api/agent/code/write", methods=["POST"])
def agent_code_write_file():
    """Modify or overwrite a source code file."""
    data = request.get_json() or {}
    path = data.get("path", "")
    content = data.get("content", "")
    patch = data.get("patch", {})  # Optional: {"search": "old", "replace": "new"}

    if not path:
        return jsonify({"success": False, "message": "Please provide a file path."}), 400

    full = _safe_code_path(path)
    if full is None:
        return jsonify({"success": False, "message": f"Path not allowed: {path}"}), 403
    if not os.path.isfile(full):
        return jsonify({"success": False, "message": f"File not found: {path}"}), 404

    old_text = ""
    created_backup = False
    try:
        with open(full, "r", encoding="utf-8") as f:
            old_text = f.read()
        created_backup = path not in code_write_backups
        if created_backup:
            code_write_backups[path] = old_text

        if patch and "search" in patch and "replace" in patch:
            search_text = patch["search"]
            replace_text = patch["replace"]
            if search_text not in old_text:
                return jsonify({"success": False, "message": "Patch pattern not found."}), 400
            new_text = old_text.replace(search_text, replace_text, 1)
            if old_text == new_text:
                return jsonify({"success": False, "message": "Patch did not change the file."}), 400
            content = new_text
        elif content == "":
            return jsonify({
                "success": False,
                "message": "Please provide replacement content or a patch.",
            }), 400

        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        _reload_runtime_for_path(path)

        return jsonify({
            "success": True,
            "message": f"Successfully updated {path}",
            "path": path,
            "backup_available": True,
        })
    except Exception as e:
        if old_text:
            with open(full, "w", encoding="utf-8") as f:
                f.write(old_text)
        try:
            if old_text:
                _reload_runtime_for_path(path)
        except Exception:
            pass
        if created_backup:
            code_write_backups.pop(path, None)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/agent/code/restore", methods=["POST"])
def agent_code_restore_file():
    """Restore the last backup created by ``/api/agent/code/write`` for a file."""
    data = request.get_json() or {}
    path = data.get("path", "")

    if not path:
        return jsonify({"success": False, "message": "Please provide a file path."}), 400

    full = _safe_code_path(path)
    if full is None:
        return jsonify({"success": False, "message": f"Path not allowed: {path}"}), 403

    if path not in code_write_backups:
        return jsonify({
            "success": False,
            "message": f"No backup available for {path}.",
        }), 404

    try:
        with open(full, "w", encoding="utf-8") as f:
            f.write(code_write_backups[path])
        _reload_runtime_for_path(path)
        del code_write_backups[path]
        return jsonify({
            "success": True,
            "message": f"Successfully restored {path}",
            "path": path,
            "backup_available": False,
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _get_debug_logs_game_id() -> str:
    """Return the game id used to scope debug log access."""
    return (request.args.get("game_id") or "").strip()


@app.route("/api/agent/code/debug_logs", methods=["GET", "DELETE"])
def agent_code_debug_logs():
    """Retrieve or clear the captured debug/print logs for a specific game."""
    game_id = _get_debug_logs_game_id()
    if not game_id:
        return jsonify({"success": False, "message": "Please provide a game_id."}), 400

    if request.method == "DELETE":
        _clear_debug_buffer(game_id)
        return jsonify(
            {
                "success": True,
                "message": f"Debug logs cleared for game_id '{game_id}'.",
                "game_id": game_id,
            }
        )

    logs = _read_debug_buffer(game_id)
    return jsonify({"success": True, "game_id": game_id, "logs": logs})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(
        f"""
+============================================================+
|      Dark Castle: Night of Awakening - Game Server         |
+============================================================+
|  Game URL: http://localhost:{port:<32}|
|  API URL:  http://localhost:{port}/api{' ' * 27}|
+============================================================+
"""
    )
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
