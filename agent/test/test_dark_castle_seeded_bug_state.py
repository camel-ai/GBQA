"""Smoke checks for the released Dark Castle benchmark instances."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import yaml  # noqa: E402


INSTANCE_SLUGS = [
    "dark-castle-key-fragment-combine",
    "dark-castle-dropped-hidden-item",
]


def test_dark_castle_instances_use_latest_minus_one_github_release() -> None:
    for slug in INSTANCE_SLUGS:
        metadata_path = ROOT_DIR / "gbqa" / "tasks" / slug / "gbqa.yaml"
        metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
        software = metadata["software"]

        assert metadata["task"]["id"] == f"gbqa/{slug}"
        assert metadata["task"]["application_id"] == "dark-castle"
        assert metadata["task"]["instance_id"] == slug
        assert software["type"] == "github_release"
        assert software["repository"] == "https://github.com/Tsumugii24/dark-castle"
        assert software["selected_release_role"] == "latest_minus_one"
        assert software["selected_version"] == "v0.1.0"
        assert software["latest_version"] == "v0.2.0"
        assert software["archive_url"].endswith("/archive/refs/tags/v0.1.0.tar.gz")
        assert urlparse(software["archive_url"]).scheme == "https"
        assert software["install_dir"] == "/sandbox/software/dark-castle"


def test_ground_truth_files_define_one_patch_backed_target_bug() -> None:
    for slug in INSTANCE_SLUGS:
        paths = [
            ROOT_DIR / "gbqa" / "tasks" / slug / "bugs" / "dark-castle.json",
            ROOT_DIR / "gbqa" / "tasks" / slug / "tests" / "bugs" / "dark-castle.json",
        ]
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            target = payload["target_bug"]
            assert payload["task_id"] == f"gbqa/{slug}"
            assert target["id"] == slug
            assert str(target.get("hint", "")).strip()
            assert str(target.get("expected_behavior", "")).strip()
            assert str(target.get("observed_fault", "")).strip()
            assert target.get("reproduction")
            assert target.get("pinpoint", {}).get("function")
            assert target.get("pinpoint", {}).get("file")
            assert target.get("golden_patch", {}).get("functions")
            assert target.get("golden_patch", {}).get("hunks")


def main() -> None:
    test_dark_castle_instances_use_latest_minus_one_github_release()
    test_ground_truth_files_define_one_patch_backed_target_bug()
    print("dark castle instance metadata smoke test passed")


if __name__ == "__main__":
    main()
