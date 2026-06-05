"""Install Rewardkit verifier layouts for GBQA Harbor task packages."""

from __future__ import annotations

import shutil
from pathlib import Path


TEMPLATE_TESTS_ROOT = (
    Path(__file__).resolve().parent.parent / "tasks" / "_template" / "tests"
)


def install_task_verifier_tests(
    destination: Path,
    *,
    ground_truth_path: str = "/tests/bugs/ground_truth.json",
) -> None:
    """Copy the shared Rewardkit verifier template into a task package."""

    if not TEMPLATE_TESTS_ROOT.is_dir():
        raise FileNotFoundError(
            f"Missing verifier template at {TEMPLATE_TESTS_ROOT}"
        )

    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(TEMPLATE_TESTS_ROOT, destination)

    test_sh = destination / "test.sh"
    text = test_sh.read_text(encoding="utf-8")
    text = text.replace("__GBQA_GROUND_TRUTH__", ground_truth_path)
    test_sh.write_text(text, encoding="utf-8", newline="\n")
