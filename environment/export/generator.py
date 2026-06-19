from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from environment.sourcing.utils import slugify
from gbqa.rewards.template import install_task_verifier_tests

_MODE_ALIASES = {
    "api": "terminal",
    "cli": "terminal",
    "shell": "terminal",
    "code": "terminal",
    "computer_use": "computer",
    "computeruse": "computer",
    "gui": "computer",
}


def _normalize_mode(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return _MODE_ALIASES.get(text, text)


def _unique_modes(values: list[Any]) -> list[str]:
    modes: list[str] = []
    for value in values:
        mode = _normalize_mode(value)
        if mode in {"terminal", "browser", "computer"} and mode not in modes:
            modes.append(mode)
    return modes or ["terminal"]


def _interaction_surfaces(seed: dict[str, Any], modes: list[str]) -> list[dict[str, Any]]:
    configured = seed.get("interaction_surfaces")
    if isinstance(configured, list) and configured:
        surfaces: list[dict[str, Any]] = []
        for surface in configured:
            if not isinstance(surface, dict):
                continue
            item = dict(surface)
            item_modes = item.get("modes") or modes
            item["modes"] = _unique_modes(item_modes if isinstance(item_modes, list) else [item_modes])
            surfaces.append(item)
        return surfaces

    service = seed.get("service", {})
    surfaces = []
    if "terminal" in modes:
        surfaces.append(
            {
                "id": "terminal_api",
                "kind": "http_api",
                "modes": ["terminal"],
                "base_path": service.get("api_base_path", "/"),
            }
        )
    if "browser" in modes or "computer" in modes:
        surface_modes = [mode for mode in ("browser", "computer") if mode in modes]
        surfaces.append(
            {
                "id": "web_ui",
                "kind": "web_ui",
                "modes": surface_modes,
                "path": service.get("frontend_path", "/"),
            }
        )
    return surfaces


def _toml_string(value: Any) -> str:
    return json.dumps(str(value))


def _toml_string_array(values: list[Any]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _toml_inline_surfaces(surfaces: list[dict[str, Any]]) -> str:
    tables: list[str] = []
    for surface in surfaces:
        parts: list[str] = []
        for key, value in surface.items():
            if isinstance(value, list):
                parts.append(f"{key} = {_toml_string_array(value)}")
            else:
                parts.append(f"{key} = {_toml_string(value)}")
        tables.append("{ " + ", ".join(parts) + " }")
    return "[" + ", ".join(tables) + "]"


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
    modes = _unique_modes(seed.get("interaction_modes", []))
    primary_mode = _normalize_mode(seed.get("primary_interaction_mode", modes[0]))
    if primary_mode not in modes:
        primary_mode = modes[0]
    surfaces = _interaction_surfaces(seed, modes)
    return f"""id = "{seed['task_id']}"
name = "{seed['slug']}"
description = "Draft GBQA task generated from environment sourcing."
agent_timeout_sec = 600
verifier_timeout_sec = 120

[verifier.env]
REWARDKIT_JUDGE = "${{REWARDKIT_JUDGE:-openai/gpt-4o}}"
ANTHROPIC_API_KEY = "${{ANTHROPIC_API_KEY:-}}"
ANTHROPIC_BASE_URL = "${{ANTHROPIC_BASE_URL:-}}"
OPENAI_API_KEY = "${{OPENAI_API_KEY:-}}"
OPENAI_API_BASE = "${{OPENAI_API_BASE:-https://zenmux.ai/api/v1}}"
OPENAI_BASE_URL = "${{OPENAI_BASE_URL:-https://zenmux.ai/api/v1}}"
CLAUDE_CODE_OAUTH_TOKEN = "${{CLAUDE_CODE_OAUTH_TOKEN:-}}"
CODEX_AUTH_JSON_PATH = "${{CODEX_AUTH_JSON_PATH:-}}"
CODEX_AUTH_JSON_B64 = "${{CODEX_AUTH_JSON_B64:-}}"
CODEX_FORCE_AUTH_JSON = "${{CODEX_FORCE_AUTH_JSON:-}}"

[metadata]
benchmark_status = "{seed.get('benchmark_status', 'draft')}"
software_repository = "{seed['repository']}"
software_selected_version = "{seed['baseline_release']}"
software_fixed_reference_version = "{seed.get('fixed_release', '')}"
software_archive_url = "{seed['baseline_archive_url']}"
operating_system = "{seed.get('operating_system', 'linux')}"
supported_interaction_modes = {_toml_string_array(modes)}
default_interaction_mode = "{primary_mode}"
interaction_surfaces = {_toml_inline_surfaces(surfaces)}

[environment]
provider = "daytona"
dockerfile = "environment/Dockerfile"
"""


def _render_gbqa_yaml(seed: dict[str, Any]) -> str:
    service = seed.get("service", {})
    modes = _unique_modes(seed.get("interaction_modes", []))
    primary_mode = _normalize_mode(seed.get("primary_interaction_mode", modes[0]))
    if primary_mode not in modes:
        primary_mode = modes[0]
    mode_lines = "".join(f'    - "{mode}"\n' for mode in modes)
    surface_lines = _render_surfaces_yaml(_interaction_surfaces(seed, modes))
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
  default_mode: "{primary_mode}"
  supported_modes:
{mode_lines}metadata:
  operating_system:
    default: "{seed.get('operating_system', 'linux')}"
    supported:
      - "{seed.get('operating_system', 'linux')}"
  interaction_surfaces:
{surface_lines}service:
  host: "{service.get('host', '127.0.0.1')}"
  port: {int(service.get('port', 8000))}
  health_path: "{service.get('health_path', '/health')}"
  api_base_path: "{service.get('api_base_path', '/')}"
  frontend_path: "{service.get('frontend_path', '/')}"
ground_truth:
  path: "bugs/ground_truth.json"
artifacts:
  agent_dir: "/logs/agent/gbqa"
  verifier_dir: "/logs/verifier"
"""


def _render_surfaces_yaml(surfaces: list[dict[str, Any]]) -> str:
    if not surfaces:
        return "    []\n"
    lines: list[str] = []
    for surface in surfaces:
        lines.append(f'    - id: "{surface.get("id", "")}"')
        lines.append(f'      kind: "{surface.get("kind", "unknown")}"')
        lines.append("      modes:")
        for mode in _unique_modes(surface.get("modes", [])):
            lines.append(f'        - "{mode}"')
        for key, value in surface.items():
            if key in {"id", "kind", "modes"} or value in (None, ""):
                continue
            lines.append(f'      {key}: "{value}"')
    return "\n".join(lines) + "\n"


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

