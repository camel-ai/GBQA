from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from environment.sourcing.utils import slugify
from gbqa.rewards.template import install_task_verifier_tests


def generate_task_packages(*, input_path: Path, output_dir: Path) -> list[Path]:
    generated: list[Path] = []
    for seed in _load_seeds(input_path):
        task_root = _safe_task_root(output_dir, seed)
        if task_root.exists():
            shutil.rmtree(task_root)
        _write_task_package(task_root, seed)
        generated.append(task_root)
    return generated


def _load_seeds(input_path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in input_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _write_task_package(task_root: Path, seed: dict[str, Any]) -> None:
    seed["slug"] = task_root.name
    (task_root / "environment").mkdir(parents=True, exist_ok=True)
    (task_root / "bugs").mkdir(parents=True, exist_ok=True)
    (task_root / "solution").mkdir(parents=True, exist_ok=True)
    (task_root / "task.toml").write_text(_render_task_toml(seed), encoding="utf-8")
    (task_root / "gbqa.yaml").write_text(_render_gbqa_yaml(seed), encoding="utf-8")
    (task_root / "instruction.md").write_text(_render_instruction(seed), encoding="utf-8")
    (task_root / "environment" / "Dockerfile").write_text(_render_dockerfile(seed), encoding="utf-8")
    (task_root / "bugs" / "ground_truth.json").write_text('{"bugs": []}\n', encoding="utf-8")
    (task_root / "tests" / "bugs").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        task_root / "bugs" / "ground_truth.json",
        task_root / "tests" / "bugs" / "ground_truth.json",
    )
    install_task_verifier_tests(
        task_root / "tests",
        ground_truth_path="/tests/bugs/ground_truth.json",
    )


def _render_task_toml(seed: dict[str, Any]) -> str:
    return f"""id = "{seed['task_id']}"
name = "{seed['slug']}"
description = "Draft GBQA task generated from environment sourcing."
agent_timeout_sec = 600
verifier_timeout_sec = 120

[verifier.env]
REWARDKIT_JUDGE = "${{REWARDKIT_JUDGE}}"
ANTHROPIC_API_KEY = "${{ANTHROPIC_API_KEY}}"
OPENAI_API_KEY = "${{OPENAI_API_KEY}}"
OPENAI_API_BASE = "${{OPENAI_API_BASE}}"

[metadata]
benchmark_status = "{seed.get('benchmark_status', 'draft')}"
software_repository = "{seed['repository']}"
software_selected_version = "{seed['baseline_release']}"
software_fixed_reference_version = "{seed.get('fixed_release', '')}"
software_archive_url = "{seed['baseline_archive_url']}"

[environment]
provider = "daytona"
dockerfile = "environment/Dockerfile"
"""


def _render_gbqa_yaml(seed: dict[str, Any]) -> str:
    service = seed.get("service", {})
    modes = seed.get("interaction_modes", [])
    mode_lines = "".join(f'    - "{mode}"\n' for mode in modes)
    return f"""schema_version: "0.1"
task:
  id: "{seed['task_id']}"
  family: "software"
  title: "{seed['slug']}"
  benchmark_status: "{seed.get('benchmark_status', 'draft')}"
software:
  type: "github_release"
  repository: "{seed['repository']}"
  archive_url: "{seed['baseline_archive_url']}"
  selected_version: "{seed['baseline_release']}"
  selected_release_role: "latest_minus_one"
  fixed_reference_version: "{seed.get('fixed_release', '')}"
  install_dir: "/sandbox/software/{seed['slug']}"
runtime:
  default_provider: "daytona"
  local_docker_supported: false
interaction:
  default_mode: "{seed.get('primary_interaction_mode', 'api')}"
  supported_modes:
{mode_lines if mode_lines else '    - "api"\\n'}service:
  host: "{service.get('host', '127.0.0.1')}"
  port: {int(service.get('port', 8000))}
  health_path: "{service.get('health_path', '/health')}"
  api_base_path: "{service.get('api_base_path', '/')}"
ground_truth:
  path: "bugs/ground_truth.json"
artifacts:
  agent_dir: "/logs/agent/gbqa"
  verifier_dir: "/logs/verifier"
"""


def _render_instruction(seed: dict[str, Any]) -> str:
    return f"""# {seed['slug']}

Explore the target software environment and report reproducible quality issues.

This is a generated draft task. Review deployment, interaction contract, and
ground-truth bugs before adding it to an official benchmark set.
"""


def _render_dockerfile(seed: dict[str, Any]) -> str:
    archive_url = seed["baseline_archive_url"]
    slug = seed["slug"]
    return f"""FROM python:3.12-slim

ARG SOFTWARE_ARCHIVE_URL="{archive_url}"
ARG SOFTWARE_INSTALL_DIR="/sandbox/software/{slug}"

RUN apt-get update \\
    && apt-get install -y --no-install-recommends curl ca-certificates tar gzip \\
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p "$SOFTWARE_INSTALL_DIR" /sandbox/agent /sandbox/gbqa /sandbox/runtime /logs/agent /logs/verifier /logs/artifacts \\
    && curl -L "$SOFTWARE_ARCHIVE_URL" -o /tmp/software.tar.gz \\
    && tar -xzf /tmp/software.tar.gz -C "$SOFTWARE_INSTALL_DIR" --strip-components=1 \\
    && rm /tmp/software.tar.gz \\
    && pip install harbor-rewardkit

WORKDIR /sandbox/software/{slug}
"""


def _safe_task_root(output_dir: Path, seed: dict[str, Any]) -> Path:
    raw_slug = str(seed.get("slug") or seed.get("task_id", "environment")).rsplit("/", 1)[-1]
    safe_slug = slugify(raw_slug)
    root = output_dir.resolve()
    target = (output_dir / safe_slug).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"refusing to generate task outside output directory: {target}")
    return output_dir / safe_slug


