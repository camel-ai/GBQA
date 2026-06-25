"""Install Rewardkit verifier layouts for GBQA Harbor task packages."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


TEMPLATE_TESTS_ROOT = (
    Path(__file__).resolve().parent.parent / "tasks" / "_template" / "tests"
)
GBQA_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_BUNDLE_DIR = "_gbqa_runtime"
RUNTIME_PACKAGE_DIRS = ("protocol", "rewards")
RUNTIME_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def install_task_verifier_tests(
    destination: Path,
    *,
    ground_truth_path: str = "/tests/bugs/ground_truth.json",
) -> None:
    """Copy the shared Rewardkit verifier template into a task package.

    Harbor always uploads a task's ``tests/`` directory before verification,
    regardless of which agent runner was used. Bundling the small GBQA verifier
    runtime here keeps scoring independent from GBQAHarborAgent.setup().
    """

    if not TEMPLATE_TESTS_ROOT.is_dir():
        raise FileNotFoundError(
            f"Missing verifier template at {TEMPLATE_TESTS_ROOT}"
        )

    with tempfile.TemporaryDirectory(prefix="gbqa-tests-preserve-") as temp_dir:
        preserved_bugs = Path(temp_dir) / "bugs"
        source_bugs = destination / "bugs"
        has_bugs = source_bugs.is_dir()
        if has_bugs:
            shutil.copytree(source_bugs, preserved_bugs)

        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(TEMPLATE_TESTS_ROOT, destination, ignore=RUNTIME_IGNORE)

        if has_bugs:
            shutil.copytree(preserved_bugs, destination / "bugs", dirs_exist_ok=True)

    _install_runtime_bundle(destination)

    for relative in ("test.sh",):
        target = destination / relative
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        text = text.replace("__GBQA_GROUND_TRUTH__", ground_truth_path)
        target.write_text(text, encoding="utf-8", newline="\n")


def _install_runtime_bundle(destination: Path) -> None:
    runtime_root = destination / RUNTIME_BUNDLE_DIR
    runtime_package = runtime_root / "gbqa"
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_package.mkdir(parents=True, exist_ok=True)

    shutil.copy2(GBQA_PACKAGE_ROOT / "__init__.py", runtime_package / "__init__.py")
    for package_dir in RUNTIME_PACKAGE_DIRS:
        source = GBQA_PACKAGE_ROOT / package_dir
        target = runtime_package / package_dir
        if not source.is_dir():
            raise FileNotFoundError(f"Missing GBQA verifier runtime package: {source}")
        shutil.copytree(source, target, ignore=RUNTIME_IGNORE)
