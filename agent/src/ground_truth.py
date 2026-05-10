"""Ground-truth location helpers."""

from __future__ import annotations

import os

from .config import Config


DEFAULT_GROUND_TRUTH_TEMPLATE = os.path.join(
    "..",
    "gbqa",
    "tasks",
    "{task_slug}",
    "bugs",
    "{bug_version}.json",
)


def resolve_ground_truth_path(
    config: Config,
    task_id: str,
    explicit_path: str | None = None,
) -> str:
    """Resolve the ground-truth file path for a benchmark task."""
    if explicit_path:
        return config.resolve_path(explicit_path)

    task_config = config.get_task(task_id) or {}
    task_slug = str(task_config.get("slug") or task_id.rsplit("/", maxsplit=1)[-1])
    bug_version = str(task_config.get("bug_version", task_slug))
    template = str(
        task_config.get("ground_truth_path", DEFAULT_GROUND_TRUTH_TEMPLATE)
    )
    return config.resolve_path(
        template.format(
            task_id=task_id,
            task_slug=task_slug,
            bug_version=bug_version,
        )
    )
