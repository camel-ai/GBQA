"""Ground-truth location helpers."""

from __future__ import annotations

import os

from .config import Config


DEFAULT_GROUND_TRUTH_TEMPLATE = os.path.join(
    "..",
    "hub",
    "{game_id}",
    "bugs",
    "{bug_version}.json",
)


def resolve_ground_truth_path(
    config: Config,
    game_id: str,
    explicit_path: str | None = None,
) -> str:
    """Resolve the ground-truth file path for a game."""
    if explicit_path:
        return config.resolve_path(explicit_path)

    game_config = config.get_game(game_id) or {}
    bug_version = str(game_config.get("bug_version", game_id))
    template = str(
        game_config.get("ground_truth_path", DEFAULT_GROUND_TRUTH_TEMPLATE)
    )
    return config.resolve_path(
        template.format(game_id=game_id, bug_version=bug_version)
    )
