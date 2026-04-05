"""Minimal JSON-RPC stdio client for MCP-compatible servers."""

from __future__ import annotations

from collections import deque
import json
import subprocess
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, List, Optional


class McpProtocolError(RuntimeError):
    """Raised when MCP transport or protocol interaction fails."""


class StdioMcpClient:
    """Very small MCP stdio client for tools/list and tools/call."""

    def __init__(
        self,
        command: List[str],
        *,
        cwd: Optional[str] = None,
        startup_timeout: int = 20,
    ) -> None:
        if not command:
            raise ValueError("MCP command must not be empty")
        self._command = command
        self._cwd = cwd
        self._startup_timeout = startup_timeout
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._messages: Queue[Dict[str, Any]] = Queue()
        self._next_id = 1
        self._stderr_lines: deque[str] = deque(maxlen=200)
        self._stderr_lock = threading.Lock()

    def start(self) -> None:
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            self._command,
            cwd=self._cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(
            target=self._read_stderr_loop,
            daemon=True,
        )
        self._stderr_reader.start()
        self.initialize()
        self.notify("notifications/initialized", {})

    def initialize(self) -> Dict[str, Any]:
        return self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "gbqa", "version": "0.1.0"},
                "capabilities": {},
            },
        )

    def list_tools(self) -> Dict[str, Any]:
        return self.request("tools/list", {})

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def notify(self, method: str, params: Dict[str, Any]) -> None:
        self._ensure_started()
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_message(payload)

    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_started()
        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        self._write_message(payload)
        deadline = time.time() + self._startup_timeout
        while time.time() < deadline:
            self._raise_if_process_exited(method)
            try:
                message = self._messages.get(timeout=0.2)
            except Empty:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise McpProtocolError(json.dumps(message["error"], ensure_ascii=False))
            result = message.get("result")
            if not isinstance(result, dict):
                return {"result": result}
            return result
        self._raise_if_process_exited(method)
        raise McpProtocolError(f"Timed out waiting for MCP response to {method}")

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        self._process = None

    def _ensure_started(self) -> None:
        if self._process is None:
            self.start()

    def _write_message(self, payload: Dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise McpProtocolError("MCP process is not writable")
        body = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        self._process.stdin.write(body)
        self._process.stdin.flush()

    def _read_loop(self) -> None:
        if not self._process or not self._process.stdout:
            return
        stdout = self._process.stdout
        while True:
            raw_line = stdout.readline()
            if not raw_line:
                return
            try:
                payload = json.loads(raw_line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                self._messages.put(payload)

    def _raise_if_process_exited(self, method: str) -> None:
        process = self._process
        if process is None:
            return
        return_code = process.poll()
        if return_code is None:
            return
        stderr_text = self._recent_stderr()
        detail = (
            f"MCP process exited with code {return_code} while waiting for {method}."
        )
        if stderr_text:
            detail = f"{detail} stderr: {stderr_text}"
        raise McpProtocolError(detail)

    def _read_stderr_loop(self) -> None:
        if not self._process or not self._process.stderr:
            return
        stderr = self._process.stderr
        while True:
            raw_line = stderr.readline()
            if not raw_line:
                return
            text = raw_line.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue
            with self._stderr_lock:
                self._stderr_lines.append(text)

    def _recent_stderr(self) -> str:
        with self._stderr_lock:
            return "\n".join(self._stderr_lines).strip()


def default_mcp_cwd(root_path: str) -> str:
    """Resolve a stable cwd for launching MCP servers."""
    return str(Path(root_path).resolve())
