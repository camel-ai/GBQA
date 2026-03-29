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

    def new_game(self) -> Dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/agent/new", timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()

    def send_command(self, game_id: str, command: str) -> Dict[str, Any]:
        response = self._session.post(
            f"{self._base_url}/agent/command",
            json={"game_id": game_id, "command": command},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_state(self, game_id: str) -> Dict[str, Any]:
        response = self._session.get(
            f"{self._base_url}/agent/state/{game_id}", timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._session.close()


def create_http_game_client(config: GameClientConfig) -> HttpGameClient:
    """Build a standardized HTTP game client."""
    return HttpGameClient(base_url=config.base_url, timeout=config.timeout)


DarkCastleGameClient = HttpGameClient
CastleGameClient = DarkCastleGameClient
