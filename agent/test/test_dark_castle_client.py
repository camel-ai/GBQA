"""Smoke test for the dark-castle API client."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.game_clients import DarkCastleGameClient


def main() -> None:
    base_url = os.getenv("DARK_CASTLE_BASE_URL") or os.getenv(
        "CASTLE_BASE_URL", "http://localhost:5000/api"
    )
    client = DarkCastleGameClient(base_url)
    data = client.new_game()
    game_id = data.get("game_id", "")
    print("New game:", game_id)
    response = client.send_command(game_id, "look")
    print("Look response:", response.get("message", ""))


if __name__ == "__main__":
    main()
