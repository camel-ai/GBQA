"""Resolve verifier input paths for Harbor task containers."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_bugs_path(
    *,
    bugs_path: str | Path | None = None,
    fallback_path: str | Path = "/tests/empty_bugs.json",
) -> Path:
    candidate = Path(
        str(bugs_path or os.environ.get("GBQA_BUGS_PATH", "/logs/agent/gbqa/bugs.json"))
    )
    if candidate.is_file():
        return candidate
    return Path(fallback_path)


def resolve_ground_truth_path(
    *,
    ground_truth_path: str | Path | None = None,
    default_name: str = "ground_truth.json",
) -> Path:
    candidate = Path(
        str(
            ground_truth_path
            or os.environ.get("GBQA_GROUND_TRUTH", f"/tests/bugs/{default_name}")
        )
    )
    return candidate
