"""
Data types and protocols for codebase reading and white-box debugging.
Focuses on sandbox-based filesystem interactions via standard shell contracts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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

    def _safe_path(self, user_path: str) -> Optional[str]:
        """Convert user path to absolute path and verify it stays within root_dir."""
        # Remove leading slashes and resolve '.' and '..'
        clean_path = os.path.normpath(user_path.lstrip("/"))
        if clean_path.startswith(".."):
            return None
        
        full_path = os.path.join(self.root_dir, clean_path)
        
        # Double-check against root_dir to prevent advanced traversal
        if not os.path.abspath(full_path).startswith(self.root_dir):
            return None
            
        return full_path

    def list_files(self, path: str = ".") -> List[CodebaseFile]:
        target = self._safe_path(path)
        if not target or not self.shell_client:
            return []
            
        # Use find with depth limit for discovery
        output = self._run_shell(f"find {target} -maxdepth 2 -not -path '*/.*'")
        files = []
        for line in output.strip().splitlines():
            if not line.strip(): continue
            # Relative path for the agent
            rel = os.path.relpath(line, self.root_dir)
            if rel != ".":
                files.append(CodebaseFile(path=rel))
        return files

    def read_file(self, path: str) -> Optional[str]:
        full_path = self._safe_path(path)
        if not full_path or not self.shell_client:
            return None
        
        # Verification: check if it's a file first
        if "yes" != self._run_shell(f"test -f {full_path} && echo yes || echo no").strip():
            return None
            
        return self._run_shell(f"cat {full_path}")

    def search_code(self, pattern: str) -> List[Dict[str, Any]]:
        if not self.shell_client: return []
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
        if not full_path or not self.shell_client:
            return False
            
        # 1. Create persistent backup in sandbox
        backup_path = f"{self._backups_dir}/{path.replace('/', '_')}.bak"
        self._run_shell(f"mkdir -p {self._backups_dir}")
        self._run_shell(f"test ! -f {backup_path} && cp {full_path} {backup_path} || true")
        
        # 2. Write content safely
        safe_content = content.replace("'", "'\\\"'\\\"'")
        cmd = f"cat > {full_path} <<'GBQA_CODE_EOF'\n{content}\nGBQA_CODE_EOF"
        self._run_shell(cmd)
        return True

    def restore_file(self, path: str) -> bool:
        full_path = self._safe_path(path)
        backup_path = f"{self._backups_dir}/{path.replace('/', '_')}.bak"
        if not full_path: return False
        
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
