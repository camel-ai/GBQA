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
_HINT_LEVELS = ("weak", "medium", "strong")
_DEFAULT_DRAFT_HINTS = {
    "weak": "TODO: replace this draft weak hint with a broad behavioral clue for the target bug.",
    "medium": (
        "TODO: replace this draft medium hint with a target-bug hint derived "
        "from the golden patch."
    ),
    "strong": (
        "TODO: replace this draft strong hint with a concrete reproduction "
        "area and function-level localization clue."
    ),
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


def _normalize_hint_level(value: Any) -> str:
    level = str(value or "medium").strip().lower().replace("-", "_")
    if level not in _HINT_LEVELS:
        return "medium"
    return level


def _hint_level(seed: dict[str, Any]) -> str:
    return _normalize_hint_level(seed.get("hint_level") or seed.get("target_hint_level"))


def _hint_levels(seed: dict[str, Any]) -> dict[str, str]:
    hints = dict(_DEFAULT_DRAFT_HINTS)
    raw_hints = seed.get("hints") or seed.get("target_hints") or {}
    if isinstance(raw_hints, dict):
        for level in _HINT_LEVELS:
            value = str(raw_hints.get(level) or "").strip()
            if value:
                hints[level] = value

    legacy_hint = str(seed.get("hint") or seed.get("target_hint") or "").strip()
    if legacy_hint:
        hints["medium"] = legacy_hint
    return hints


def _selected_hint(seed: dict[str, Any]) -> str:
    hints = _hint_levels(seed)
    return hints.get(_hint_level(seed)) or hints["medium"]


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
    (task_root / "bugs" / "ground_truth.json").write_text(
        _render_ground_truth(seed),
        encoding="utf-8",
    )
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
    hint_level = _hint_level(seed)
    hints = _hint_levels(seed)
    selected_hint = hints[hint_level]
    return f"""id = "{seed['task_id']}"
name = "{seed['slug']}"
description = "Draft GBQA task generated from environment sourcing."
agent_timeout_sec = 600
verifier_timeout_sec = 120

[verifier.env]
GBQA_EVAL_METHOD = "${{GBQA_EVAL_METHOD:-targeted_bug}}"

[metadata]
benchmark_status = "{seed.get('benchmark_status', 'draft')}"
instance_id = "{seed['slug']}"
runtime_provider = "daytona"
supported_runtime_providers = ["daytona", "modal"]
software_repository = "{seed['repository']}"
software_selected_version = "{seed['baseline_release']}"
software_fixed_reference_version = "{seed.get('fixed_release', '')}"
software_archive_url = "{seed['baseline_archive_url']}"
operating_system = "{seed.get('operating_system', 'linux')}"
supported_interaction_modes = {_toml_string_array(modes)}
default_interaction_mode = "{primary_mode}"
interaction_surfaces = {_toml_inline_surfaces(surfaces)}
evaluation_method = "targeted_bug"
target_bug_id = "{seed['slug']}"
target_hint_level = "{hint_level}"
target_hint = {_toml_string(selected_hint)}
target_hint_weak = {_toml_string(hints["weak"])}
target_hint_medium = {_toml_string(hints["medium"])}
target_hint_strong = {_toml_string(hints["strong"])}

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
    hint_level = _hint_level(seed)
    hints = _hint_levels(seed)
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
  supported_providers:
    - "daytona"
    - "modal"
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
evaluation:
  method: "targeted_bug"
  target_bug_id: "{seed['slug']}"
  hint_level: "{hint_level}"
  hints:
    weak: {_toml_string(hints["weak"])}
    medium: {_toml_string(hints["medium"])}
    strong: {_toml_string(hints["strong"])}
  hint: {_toml_string(hints[hint_level])}
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
    hint_level = _hint_level(seed)
    hint = _selected_hint(seed)
    return f"""# {seed['slug']}

Investigate one known target bug in the software environment. Use the selected
{hint_level} hint to reproduce and localize the issue, then write one issue report to
`/logs/agent/gbqa/issue.json`. In the GBQA harness, `end_task` triggers a final
fixed-format issue report pass; only end the task after collecting enough
reproduction evidence and localization detail.

The preferred issue artifact shape is:

```json
{{
  "report_status": "complete",
  "exit_status": "completed",
  "missing_fields": [],
  "issue": {{
    "title": "Short descriptive title",
    "description": "What goes wrong and why it is a bug.",
    "expected_behavior": "What correct behavior should look like.",
    "observed_fault": "The incorrect behavior you observed.",
    "reproduction": ["step 1", "step 2"],
    "pinpoint": {{
      "locations": [
        {{
          "file": "relative/path.py",
          "function": "function_or_method_name",
          "line": 123
        }}
      ],
      "patch": "optional minimal unified diff or patch hunk",
      "rationale": "Why this location or patch explains the fault."
    }},
    "root_cause": "Function-level explanation of the implementation defect."
  }}
}}
```

Hint:

{hint}

The issue report should include:

- `expected_behavior`
- `observed_fault`
- `reproduction`
- `pinpoint` or `root_cause` at function level

This is a generated draft task. Review deployment, interaction contract, and
target-bug ground truth before adding it to an official benchmark set.
"""


def _render_ground_truth(seed: dict[str, Any]) -> str:
    hint_level = _hint_level(seed)
    hints = _hint_levels(seed)
    payload = {
        "schema_version": "gbqa-target-bug-v1",
        "task_id": seed["task_id"],
        "target_bug": {
            "id": seed["slug"],
            "title": "TODO: target bug title",
            "hint_level": hint_level,
            "hints": hints,
            "hint": hints[hint_level],
            "expected_behavior": "TODO",
            "observed_fault": "TODO",
            "reproduction": [],
            "pinpoint": {
                "file": "TODO",
                "function": "TODO",
            },
            "golden_patch": {
                "functions": [],
                "hunks": [],
            },
        },
    }
    return json.dumps(payload, indent=2) + "\n"


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
