"""Run Harbor with GBQA's root `.env` loaded first."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from gbqa.env import load_root_dotenv


def build_harbor_command(argv: Sequence[str]) -> list[str]:
    """Build the Harbor CLI command preserving caller arguments."""

    return ["harbor", *_rewrite_backend_environment(list(argv))]


def _rewrite_backend_environment(argv: list[str]) -> list[str]:
    interaction_mode = _agent_kwarg(argv, "interaction_mode")
    if interaction_mode != "computer_use":
        return argv
    path_index = _task_path_index(argv)
    if path_index is None:
        return argv
    task_path = Path(argv[path_index]).expanduser()
    if not task_path.exists():
        return argv
    computer_environment = task_path / "environment-computer-use"
    if not computer_environment.exists():
        return argv
    overlay = _prepare_computer_use_task_overlay(task_path, computer_environment)
    rewritten = list(argv)
    rewritten[path_index] = str(overlay)
    return rewritten


def _task_path_index(argv: list[str]) -> int | None:
    for index, item in enumerate(argv):
        if item in {"-p", "--path", "--task-path"} and index + 1 < len(argv):
            return index + 1
        for prefix in ("--path=", "--task-path="):
            if item.startswith(prefix):
                value = item.split("=", maxsplit=1)[1]
                argv[index] = item.split("=", maxsplit=1)[0]
                argv.insert(index + 1, value)
                return index + 1
    return None


def _agent_kwarg(argv: list[str], key: str) -> str:
    for index, item in enumerate(argv):
        if item == "--ak" and index + 1 < len(argv):
            name, _, value = argv[index + 1].partition("=")
            if name == key:
                return value
        if item.startswith("--ak="):
            name, _, value = item.split("=", maxsplit=1)[1].partition("=")
            if name == key:
                return value
    return ""


def _prepare_computer_use_task_overlay(
    task_path: Path,
    computer_environment: Path,
) -> Path:
    # TODO: Discuss with the team whether backend-specific environment selection
    # should become a first-class Harbor/GBQA task mechanism instead of this overlay.
    repo_root = Path(__file__).resolve().parents[2]
    overlay_root = repo_root / "tmp" / "harbor_task_overlays"
    overlay = overlay_root / f"{task_path.name}-computer-use"
    if overlay.exists():
        shutil.rmtree(overlay)
    ignore = shutil.ignore_patterns("environment", "environment-computer-use")
    shutil.copytree(task_path, overlay, ignore=ignore)
    shutil.copytree(computer_environment, overlay / "environment")
    return overlay


def main(argv: Sequence[str] | None = None) -> int:
    """Load root `.env`, then delegate to Harbor."""

    load_root_dotenv()
    command = build_harbor_command(sys.argv[1:] if argv is None else argv)
    return subprocess.call(command, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
