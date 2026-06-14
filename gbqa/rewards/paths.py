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


def resolve_baseline_values_path(
    *,
    baseline_values_path: str | Path | None = None,
    fallback_path: str | Path = "/tests/value/baseline_values.json",
) -> Path:
    return Path(
        str(
            baseline_values_path
            or os.environ.get("GBQA_BASELINE_VALUES", str(fallback_path))
        )
    )


def resolve_validation_cases_path(
    *,
    validation_cases_path: str | Path | None = None,
    fallback_path: str | Path = "/tests/value/validation_cases.json",
) -> Path:
    return Path(
        str(
            validation_cases_path
            or os.environ.get("GBQA_BUG_VALIDATION_CASES", str(fallback_path))
        )
    )
