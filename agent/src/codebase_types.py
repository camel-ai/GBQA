"""
Data types and protocols for codebase reading and white-box debugging.
Focuses on sandbox-based filesystem interactions via standard shell contracts.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from uuid import uuid4


@dataclass(frozen=True)
class CodebaseFile:
    path: str
    is_dir: bool = False


class UniversalCodebaseAdapter:
    """
    A robust and secure adapter for interacting with the codebase.
    """

    def __init__(self, shell_client: Any, root_dir: str = "/sandbox/software"):
        self.shell_client = shell_client
        # Ensure root_dir is absolute and clean
        self.root_dir = os.path.abspath(root_dir)
        self._backups_dir = "/tmp/gbqa_code_backups"
        self._backups: Dict[str, str] = {}

    def _safe_path(self, user_path: str) -> Optional[str]:
        """Convert user path to absolute path and verify it stays within root_dir."""
        # Remove leading slashes and resolve '.' and '..'
        clean_path = os.path.normpath(user_path.lstrip("/"))
        if clean_path.startswith(".."):
            return None

        full_path = self.root_dir if clean_path == "." else os.path.join(self.root_dir, clean_path)
        root = os.path.abspath(self.root_dir)
        candidate = os.path.abspath(full_path)
        try:
            if os.path.commonpath([root, candidate]) != root:
                return None
        except ValueError:
            return None

        return candidate

    def list_files(self, path: str = ".") -> List[CodebaseFile]:
        target = self._safe_path(path)
        if not target:
            return []
        if not self.shell_client:
            return self._list_local_files(target)
            
        # Use find with depth limit for discovery
        output = self._run_shell(
            f"find {shlex.quote(target)} -maxdepth 2 -not -path '*/.*'"
        )
        files = []
        for line in output.strip().splitlines():
            if not line.strip(): continue
            # Relative path for the agent
            rel = (
                os.path.relpath(line, self.root_dir)
                if os.path.isabs(line)
                else line.strip()
            )
            if rel != ".":
                files.append(CodebaseFile(path=rel))
        return files

    def read_file(self, path: str) -> Optional[str]:
        full_path = self._safe_path(path)
        if not full_path:
            return None
        if not self.shell_client:
            try:
                return Path(full_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        
        return self._run_shell(f"cat {shlex.quote(full_path)}")

    def search_code(self, pattern: str) -> List[Dict[str, Any]]:
        if not self.shell_client:
            return self._search_local_code(pattern)
        output = self._run_shell(
            "grep -rnE --exclude-dir=.* --max-count=100 "
            f"{shlex.quote(pattern)} {shlex.quote(self.root_dir)}"
        )
        matches = []
        for line in output.splitlines():
            if ":" in line:
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    matches.append({
                        "path": os.path.relpath(parts[0], self.root_dir),
                        "line": parts[1],
                        "content": parts[2]
                    })
        return matches

    def write_file(self, path: str, content: str) -> bool:
        full_path = self._safe_path(path)
        if not full_path:
            return False
        if not self.shell_client:
            target = Path(full_path)
            if not target.exists() or not target.is_file():
                return False
            if path not in self._backups:
                try:
                    self._backups[path] = target.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                except OSError:
                    return False
            try:
                target.write_text(content, encoding="utf-8")
            except OSError:
                return False
            return True
            
        if path not in self._backups:
            self._backups[path] = self._run_shell(f"cat {shlex.quote(full_path)}")

        delimiter = _heredoc_delimiter(content)
        cmd = (
            f"cat > {shlex.quote(full_path)} <<'{delimiter}'\n"
            f"{content}\n"
            f"{delimiter}"
        )
        self._run_shell(cmd)
        return True

    def restore_file(self, path: str) -> bool:
        full_path = self._safe_path(path)
        if not full_path: return False

        if path in self._backups:
            content = self._backups.pop(path)
            if not self.shell_client:
                try:
                    Path(full_path).write_text(content, encoding="utf-8")
                except OSError:
                    return False
                return True
            delimiter = _heredoc_delimiter(content)
            cmd = (
                f"cat > {shlex.quote(full_path)} <<'{delimiter}'\n"
                f"{content}\n"
                f"{delimiter}"
            )
            self._run_shell(cmd)
            return True

        backup_path = f"{self._backups_dir}/{path.replace('/', '_')}.bak"
        quoted_backup = shlex.quote(backup_path)
        quoted_target = shlex.quote(full_path)
        res = self._run_shell(
            f"test -f {quoted_backup} && "
            f"cp {quoted_backup} {quoted_target} && "
            f"rm {quoted_backup} && echo ok || echo fail"
        )
        return "ok" in res

    def _run_shell(self, command: str) -> str:
        """Execute command through backend, trying multiple known execution interfaces."""
        try:
            # 1. Standard CUA/Daytona async interface
            if hasattr(self.shell_client, "shell") and hasattr(self.shell_client.shell, "run"):
                res = self.shell_client._run_async(self.shell_client.shell.run(command))
                return getattr(res, "stdout", str(res))
            
            # 2. Simplified/Internal sync execution interface
            if hasattr(self.shell_client, "execute_shell"):
                return str(self.shell_client.execute_shell(command))
                
            # 3. Direct execution (for local testing/mocking)
            if hasattr(self.shell_client, "_run_command"):
                return str(self.shell_client._run_command(command))
                
        except Exception:
            pass
        return ""

    def _list_local_files(self, target: str) -> List[CodebaseFile]:
        root = Path(target)
        if not root.exists():
            return []
        files: List[CodebaseFile] = []
        for item in root.rglob("*"):
            if any(part.startswith(".") for part in item.relative_to(root).parts):
                continue
            try:
                rel = item.relative_to(self.root_dir).as_posix()
            except ValueError:
                continue
            files.append(CodebaseFile(path=rel, is_dir=item.is_dir()))
            if len(files) >= 500:
                break
        return files

    def _search_local_code(self, pattern: str) -> List[Dict[str, Any]]:
        root = Path(self.root_dir)
        if not root.exists():
            return []
        try:
            compiled = re.compile(pattern)
        except re.error:
            return []
        matches: List[Dict[str, Any]] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            try:
                lines = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if compiled.search(line):
                    matches.append(
                        {
                            "path": path.relative_to(root).as_posix(),
                            "line": line_number,
                            "content": line,
                        }
                    )
                    if len(matches) >= 100:
                        return matches
        return matches


def _heredoc_delimiter(content: str) -> str:
    delimiter = f"GBQA_CODE_EOF_{uuid4().hex}"
    while delimiter in content:
        delimiter = f"GBQA_CODE_EOF_{uuid4().hex}"
    return delimiter
