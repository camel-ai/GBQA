"""Smoke checks for the released Dark Castle benchmark baseline metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import yaml  # noqa: E402


def test_dark_castle_baseline_uses_latest_minus_one_github_release() -> None:
    metadata_path = ROOT_DIR / "gbqa" / "tasks" / "dark-castle" / "gbqa.yaml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    software = metadata["software"]

    assert software["type"] == "github_release"
    assert software["repository"] == "https://github.com/Tsumugii24/dark-castle"
    assert software["selected_release_role"] == "latest_minus_one"
    assert software["selected_version"] == "v0.1.0"
    assert software["latest_version"] == "v0.2.0"
    assert software["archive_url"].endswith("/archive/refs/tags/v0.1.0.tar.gz")
    assert urlparse(software["archive_url"]).scheme == "https"
    assert software["install_dir"] == "/sandbox/software/dark-castle"


def test_bug_ids_are_zero_based_in_ground_truth_files() -> None:
    paths = [
        ROOT_DIR / "gbqa" / "tasks" / "dark-castle" / "bugs" / "dark-castle.json",
        ROOT_DIR
        / "gbqa"
        / "tasks"
        / "dark-castle"
        / "tests"
        / "bugs"
        / "dark-castle.json",
        ROOT_DIR / "gbqa" / "tasks" / "dark-castle" / "solution" / "oracle_bugs.json",
    ]
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert [bug["id"] for bug in payload["bugs"]] == [0, 1, 2]


def test_ground_truth_files_include_expected_behavior() -> None:
    paths = [
        ROOT_DIR / "gbqa" / "tasks" / "dark-castle" / "bugs" / "dark-castle.json",
        ROOT_DIR
        / "gbqa"
        / "tasks"
        / "dark-castle"
        / "tests"
        / "bugs"
        / "dark-castle.json",
        ROOT_DIR / "gbqa" / "tasks" / "dark-castle" / "solution" / "oracle_bugs.json",
    ]
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for bug in payload["bugs"]:
            if isinstance(bug.get("evidence"), dict):
                assert str(bug["evidence"].get("expected_behavior", "")).strip()
            else:
                assert str(bug.get("expected_behavior", "")).strip()


def main() -> None:
    test_dark_castle_baseline_uses_latest_minus_one_github_release()
    test_bug_ids_are_zero_based_in_ground_truth_files()
    test_ground_truth_files_include_expected_behavior()
    print("dark castle release metadata smoke test passed")


if __name__ == "__main__":
    main()
