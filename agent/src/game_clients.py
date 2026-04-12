"""Game API clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol
import requests


class GameClient(Protocol):
    """Protocol shared by game API clients."""

    def new_game(self) -> Dict[str, Any]:
        ...

    def send_command(self, game_id: str, command: str) -> Dict[str, Any]:
        ...

    def get_state(self, game_id: str) -> Dict[str, Any]:
        ...

    def list_code_files(self) -> Dict[str, Any]:
        ...

    def read_code_file(
        self, path: str, start_line: int = 0, end_line: int = 0
    ) -> Dict[str, Any]:
        ...

    def search_code(self, pattern: str) -> Dict[str, Any]:
        ...

    def write_code_file(
        self, path: str, content: str = "", patch: Dict[str, str] = None
    ) -> Dict[str, Any]:
        ...

    def read_debug_logs(self, game_id: str, clear: bool = False) -> Dict[str, Any]:
        ...

    def restore_code_file(self, path: str) -> Dict[str, Any]:
        ...

    def get_current_log(self, game_id: str) -> Dict[str, Any]:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class GameClientConfig:
    """Configuration for HTTP game clients."""

    base_url: str
    timeout: int = 30


class HttpGameClient:
    """Generic HTTP client for GBQA game agent APIs."""

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

    def new_game(self) -> Dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/new", timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()

    def send_command(self, game_id: str, command: str) -> Dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/command",
            json={"game_id": game_id, "command": command},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_state(self, game_id: str) -> Dict[str, Any]:
        response = self._session.get(
            f"{self._base_url}/state/{game_id}", timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()

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
        self, path: str, content: str = "", patch: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """Modify or overwrite a source code file."""
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

    def read_debug_logs(self, game_id: str, clear: bool = False) -> Dict[str, Any]:
        """Retrieve the captured debug/print logs."""
        method = "DELETE" if clear else "GET"
        response = self._session.request(
            method,
            f"{self._base_url}/code/debug_logs",
            params={"game_id": game_id},
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            return response.json()
        response.raise_for_status()
        return response.json()

    def restore_code_file(self, path: str) -> Dict[str, Any]:
        """Restore a previously backed-up source code file."""
        response = self._session.post(
            f"{self._base_url}/code/restore",
            json={"path": path},
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            return response.json()
        response.raise_for_status()
        return response.json()

    def get_current_log(self, game_id: str) -> Dict[str, Any]:
        """Fetch the active session log via the existing /api/logs/current/<game_id> endpoint."""
        # This endpoint is under /api/logs, not /api/agent, so derive the base.
        api_base = self._base_url.rsplit("/agent", 1)[0]
        response = self._session.get(
            f"{api_base}/logs/current/{game_id}",
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            return response.json()
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._session.close()


def create_http_game_client(config: GameClientConfig) -> HttpGameClient:
    """Build a standardized HTTP game client."""
    return HttpGameClient(base_url=config.base_url, timeout=config.timeout)


DarkCastleGameClient = HttpGameClient
CastleGameClient = DarkCastleGameClient
