"""
Data types and adapters for codebase reading and white-box debugging.
Supports both HTTP API-backed environments and Shell-based sandboxes (Daytona/CUA).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .environment_clients import CodeToolAdapter


@dataclass(frozen=True)
class CodebaseFile:
    path: str
    is_dir: bool = False


@runtime_checkable
class CodebaseAdapter(Protocol):
    """Protocol for interacting with the target codebase."""
    def list_files(self, path: str = ".") -> List[CodebaseFile]: ...
    def read_file(self, path: str) -> Optional[str]: ...
    def search_code(self, pattern: str) -> List[Dict[str, Any]]: ...
    def write_file(self, path: str, content: str) -> bool: ...
    def restore_file(self, path: str) -> bool: ...


class UniversalCodebaseAdapter:
    """A single adapter for all environments using heuristic access."""

    def __init__(self, api_client: Optional[CodeToolAdapter] = None, shell_client: Any = None):
        self.api_client = api_client
        self.shell_client = shell_client
        self.root_dir = "/sandbox/software"
        self._backups: Dict[str, str] = {}

    def list_files(self, path: str = ".") -> List[CodebaseFile]:
        if self.api_client:
            res = self.api_client.list_code_files()
            return [CodebaseFile(path=f.get("path", ""), is_dir=f.get("is_dir", False)) 
                    for f in res.get("files", [])]
        
        if self.shell_client:
            output = self._run_shell(f"find {self.root_dir} -maxdepth 2 -not -path '*/.*'")
            files = []
            for line in output.strip().splitlines():
                if not line.strip(): continue
                rel = line.replace(self.root_dir, "").lstrip("/")
                if rel: files.append(CodebaseFile(path=rel))
            return files
        return []

    def read_file(self, path: str) -> Optional[str]:
        if self.api_client:
            return self.api_client.read_code_file(path).get("content")
        if self.shell_client:
            return self._run_shell(f"cat {self.root_dir}/{path.lstrip('/')}")
        return None

    def search_code(self, pattern: str) -> List[Dict[str, Any]]:
        if self.api_client:
            return self.api_client.search_code(pattern).get("matches", [])
        if self.shell_client:
            p = pattern.replace("'", "'\\\"'\\\"'")
            output = self._run_shell(f"grep -rnE '{p}' {self.root_dir} --exclude-dir=.*")
            matches = []
            for line in output.splitlines():
                if ":" in line:
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        matches.append({
                            "path": parts[0].replace(self.root_dir, "").lstrip("/"),
                            "line": parts[1],
                            "content": parts[2]
                        })
            return matches
        return []

    def write_file(self, path: str, content: str) -> bool:
        if self.api_client:
            return bool(self.api_client.write_code_file(path, content=content).get("success"))
        if self.shell_client:
            if path not in self._backups:
                self._backups[path] = self.read_file(path) or ""
            safe_content = content.replace("'", "'\\\"'\\\"'")
            # Use heredoc for robust multi-line writes
            cmd = f"cat > {self.root_dir}/{path.lstrip('/')} <<'GBQA_CODE_EOF'\n{content}\nGBQA_CODE_EOF"
            self._run_shell(cmd)
            return True
        return False

    def restore_file(self, path: str) -> bool:
        if self.api_client:
            return bool(self.api_client.restore_code_file(path).get("success"))
        if path in self._backups:
            success = self.write_file(path, self._backups[path])
            if success: del self._backups[path]
            return success
        return False

    def _run_shell(self, command: str) -> str:
        if not self.shell_client: return ""
        try:
            if hasattr(self.shell_client, "shell"):
                res = self.shell_client._run_async(self.shell_client.shell.run(command))
                return getattr(res, "stdout", str(res))
            if hasattr(self.shell_client, "_run_command"):
                return str(self.shell_client._run_command(command))
        except Exception: pass
        return ""
