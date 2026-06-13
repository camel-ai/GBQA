"""
Data types and protocols for codebase reading and white-box debugging.
Focuses on sandbox-based filesystem interactions via standard shell contracts.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


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
        
        # Double-check against root_dir to prevent advanced traversal
        if not os.path.abspath(full_path).startswith(self.root_dir):
            return None
            
        return full_path

    def list_files(self, path: str = ".") -> List[CodebaseFile]:
        target = self._safe_path(path)
        if not target:
            return []
        if not self.shell_client:
            return self._list_local_files(target)
            
        # Use find with depth limit for discovery
        output = self._run_shell(f"find {target} -maxdepth 2 -not -path '*/.*'")
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
        
        return self._run_shell(f"cat {full_path}")

    def search_code(self, pattern: str) -> List[Dict[str, Any]]:
        if not self.shell_client:
            return self._search_local_code(pattern)
        # Escape single quotes for shell safety
        p = pattern.replace("'", "'\\\"'\\\"'")
        output = self._run_shell(f"grep -rnE '{p}' {self.root_dir} --exclude-dir=.* --max-count=100")
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
            self._backups[path] = self._run_shell(f"cat {full_path}")
        
        cmd = f"cat > {full_path} <<'GBQA_CODE_EOF'\n{content}\nGBQA_CODE_EOF"
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
            cmd = f"cat > {full_path} <<'GBQA_CODE_EOF'\n{content}\nGBQA_CODE_EOF"
            self._run_shell(cmd)
            return True

        backup_path = f"{self._backups_dir}/{path.replace('/', '_')}.bak"
        res = self._run_shell(f"test -f {backup_path} && cp {backup_path} {full_path} && rm {backup_path} && echo ok || echo fail")
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
                
        except Exception: pass
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
