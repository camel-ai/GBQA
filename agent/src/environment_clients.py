"""HTTP clients and protocols for environment actions and code tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

import requests


class EnvironmentActionClient(Protocol):
    """Protocol for command-style environment action APIs."""

    def start_session(self) -> Dict[str, Any]:
        ...

    def send_command(self, session_id: str, command: str) -> Dict[str, Any]:
        ...

    def get_state(self, session_id: str) -> Dict[str, Any]:
        ...

    def close(self) -> None:
        ...


class CodeToolAdapter(Protocol):
    """Protocol for white-box source-code interaction tools."""

    def list_code_files(self) -> Dict[str, Any]:
        ...

    def read_code_file(
        self, path: str, start_line: int = 0, end_line: int = 0
    ) -> Dict[str, Any]:
        ...

    def search_code(self, pattern: str) -> Dict[str, Any]:
        ...

    def write_code_file(
        self, path: str, content: str = "", patch: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        ...

    def restore_code_file(self, path: str) -> Dict[str, Any]:
        ...


@dataclass(frozen=True)
class EnvironmentClientConfig:
    """Configuration for HTTP clients."""

    base_url: str
    timeout: int = 30
    session_id_field: str = "session_id"
    terminal_field: str = "terminal"


class _HttpBaseClient:
    """Shared HTTP session setup for API-backed providers."""

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=10,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def close(self) -> None:
        self._session.close()


class HttpEnvironmentActionClient(_HttpBaseClient):
    """Generic HTTP client for GBQA command-style action APIs."""

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        *,
        session_id_field: str = "session_id",
        terminal_field: str = "terminal",
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        self._session_id_field = session_id_field
        self._terminal_field = terminal_field

    def start_session(self) -> Dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/new", timeout=self._timeout
        )
        response.raise_for_status()
        return self._normalize_payload(response.json())

    def send_command(self, session_id: str, command: str) -> Dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/command",
            json={self._session_id_field: session_id, "command": command},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return self._normalize_payload(response.json())

    def get_state(self, session_id: str) -> Dict[str, Any]:
        response = self._session.get(
            f"{self._base_url}/state/{session_id}", timeout=self._timeout
        )
        response.raise_for_status()
        return self._normalize_payload(response.json())

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(payload)
        if self._session_id_field in payload:
            normalized.setdefault("session_id", payload[self._session_id_field])
        if self._terminal_field in payload:
            normalized.setdefault("terminal", payload[self._terminal_field])
        return normalized


class HttpCodeToolApiClient(_HttpBaseClient):
    """HTTP client for environment-side code tool APIs."""

    def list_code_files(self) -> Dict[str, Any]:
        response = self._session.get(
            f"{self._base_url}/code/files", timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()

    def read_code_file(
        self, path: str, start_line: int = 0, end_line: int = 0
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"path": path}
        if start_line > 0:
            payload["start_line"] = start_line
        if end_line > 0:
            payload["end_line"] = end_line
        response = self._session.post(
            f"{self._base_url}/code/read",
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def search_code(self, pattern: str) -> Dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/code/search",
            json={"pattern": pattern},
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            return response.json()
        response.raise_for_status()
        return response.json()

    def write_code_file(
        self, path: str, content: str = "", patch: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"path": path}
        if patch:
            payload["patch"] = patch
        else:
            payload["content"] = content

        response = self._session.post(
            f"{self._base_url}/code/write",
            json=payload,
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            return response.json()
        response.raise_for_status()
        return response.json()

    def restore_code_file(self, path: str) -> Dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/code/restore",
            json={"path": path},
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            return response.json()
        response.raise_for_status()
        return response.json()


def create_http_environment_action_client(
    config: EnvironmentClientConfig,
) -> HttpEnvironmentActionClient:
    """Build a standardized HTTP environment-action client."""
    return HttpEnvironmentActionClient(
        base_url=config.base_url,
        timeout=config.timeout,
        session_id_field=config.session_id_field,
        terminal_field=config.terminal_field,
    )


def create_http_code_tool_adapter(
    config: EnvironmentClientConfig,
) -> HttpCodeToolApiClient:
    """Build a standardized HTTP code-tool adapter."""
    return HttpCodeToolApiClient(base_url=config.base_url, timeout=config.timeout)
