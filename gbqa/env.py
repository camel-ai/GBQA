"""Shared environment loading for GBQA commands and harnesses."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def repo_root() -> Path:
    """Return the GBQA repository root."""

    return Path(__file__).resolve().parents[1]


def root_env_path() -> Path:
    """Return the single project-level `.env` path."""

    override = os.getenv("GBQA_ENV_FILE")
    if override:
        return Path(override).expanduser().resolve()
    return repo_root() / ".env"


def load_root_dotenv(*, override: bool = False) -> Path:
    """Load GBQA's root `.env` into the current process."""

    path = root_env_path()
    load_dotenv(dotenv_path=path, override=override)
    return path
