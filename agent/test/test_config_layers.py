"""Smoke tests for layered QA harness configuration."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config_layers import build_config_resolution, config_resolution_for_run_spec


def main() -> None:
    temp_root = ROOT_DIR / "test" / "_tmp_config_layers"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    repo_default = temp_root / "repo-default.toml"
    trial_config = temp_root / "trial.toml"
    repo_default.write_text(
        """
[llm]
api_key = "repo-secret"
max_tokens = 1000

[agent]
max_steps = 10

[interaction.adapters.api]
base_url = "http://repo-default.test/api"
""".strip(),
        encoding="utf-8",
    )
    trial_config.write_text(
        """
[llm]
max_tokens = 2000

[agent]
max_steps = 20

[interaction.adapters.api]
base_url = "http://trial.test/api"
""".strip(),
        encoding="utf-8",
    )
    try:
        resolution = build_config_resolution(
            config_path=str(trial_config),
            repo_default_path=str(repo_default),
            task_metadata_source="gbqa/tasks/example/gbqa.yaml",
            task_metadata_config={
                "run": {"interaction_mode": "browser"},
                "interaction": {
                    "adapters": {
                        "api": {"base_url": "http://task.test/api"},
                    },
                },
            },
            cli_overrides={
                "agent": {"max_steps": 30},
                "run": {"interaction_profile": "api"},
            },
        )
        assert resolution.resolved["agent"]["max_steps"] == 30
        assert resolution.resolved["run"]["interaction_profile"] == "api"
        assert resolution.resolved["run"]["interaction_mode"] == "browser"
        assert resolution.resolved["llm"]["max_tokens"] == 2000
        assert resolution.resolved["llm"]["api_key"] == "repo-secret"
        assert (
            resolution.resolved["interaction"]["adapters"]["api"]["base_url"]
            == "http://trial.test/api"
        )
        run_spec_config = config_resolution_for_run_spec(
            resolution,
            final_config=resolution.resolved,
            normalizers=["task_metadata_profile_resolution"],
        )
        assert run_spec_config["precedence"] == [
            "cli_overrides",
            "trial_run_config",
            "task_package_gbqa_yaml",
            "repo_harness_default_config",
            "built_in_defaults",
        ]
        assert run_spec_config["normalizers"] == ["task_metadata_profile_resolution"]
        assert run_spec_config["resolved"]["llm"]["api_key"] == "<redacted>"
        cli_layer = next(
            layer
            for layer in run_spec_config["layers"]
            if layer["name"] == "cli_overrides"
        )
        assert "agent.max_steps" in cli_layer["key_paths"]

        example_resolution = build_config_resolution(
            config_path=str(trial_config),
            repo_default_path=str(ROOT_DIR / "config.toml.example"),
        )
        assert (
            example_resolution.resolved["run"]["interaction_profile"]
            == "default"
        )
        assert (
            example_resolution.resolved["interaction"]["enabled_modes"]
            == ["api", "browser", "computer_use"]
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    print("config layer smoke test passed")


if __name__ == "__main__":
    main()
