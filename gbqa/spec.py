"""GBQA task metadata loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import yaml

from gbqa.protocol.interaction import (
    SUPPORTED_INTERACTION_MODES,
    normalize_interaction_mode,
)


class GBQAMetadataError(ValueError):
    """Raised when a GBQA metadata file is missing required fields."""


@dataclass(frozen=True)
class GBQAMetadata:
    """Minimal GBQA metadata carried alongside a Harbor task."""

    path: Path
    raw: dict[str, Any]

    @property
    def task_id(self) -> str:
        return str(self.raw["task"]["id"])

    @property
    def task_slug(self) -> str:
        return self.task_id.rsplit("/", maxsplit=1)[-1]

    @property
    def instance_id(self) -> str:
        return str(self.raw["task"].get("instance_id") or self.task_slug)

    @property
    def application_id(self) -> str:
        return str(self.raw["task"].get("application_id") or self.task_slug)

    @property
    def task_title(self) -> str:
        return str(self.raw["task"].get("title") or self.task_slug)

    @property
    def agent_profile(self) -> str:
        return str(self.raw["task"].get("profile") or self.task_title)

    @property
    def software_type(self) -> str:
        return str(self.raw["software"]["type"])

    @property
    def software_repository(self) -> str:
        return str(self.raw["software"]["repository"])

    @property
    def software_release_page(self) -> str:
        return str(self.raw["software"].get("release_page") or "")

    @property
    def software_archive_url(self) -> str:
        return str(self.raw["software"]["archive_url"])

    @property
    def software_selected_version(self) -> str:
        return str(self.raw["software"]["selected_version"])

    @property
    def software_selected_release_role(self) -> str:
        return str(self.raw["software"].get("selected_release_role") or "")

    @property
    def software_latest_version(self) -> str:
        return str(self.raw["software"].get("latest_version") or "")

    @property
    def software_install_dir(self) -> str:
        return str(self.raw["software"].get("install_dir") or f"/sandbox/software/{self.task_slug}")

    @property
    def software_ready_path(self) -> str:
        return str(self.raw["software"].get("ready_path") or ".")

    @property
    def default_provider(self) -> str:
        return str(self.raw["runtime"]["default_provider"])

    @property
    def internal_log_sources(self) -> list[dict[str, Any]]:
        sources = self.raw.get("runtime", {}).get("internal_log_sources", [])
        if not isinstance(sources, list):
            return []
        return [dict(item) for item in sources if isinstance(item, dict)]

    @property
    def runtime_startup(self) -> dict[str, Any]:
        startup = self.raw.get("runtime", {}).get("startup", {})
        return dict(startup) if isinstance(startup, dict) else {}

    @property
    def runtime_start_command(self) -> str:
        return str(self.runtime_startup.get("command") or "")

    @property
    def runtime_start_workdir(self) -> str:
        return str(
            self.runtime_startup.get("workdir")
            or self.software_install_dir
        )

    @property
    def runtime_stdout_path(self) -> str:
        return str(
            self.runtime_startup.get("stdout_path")
            or "/logs/runtime/software.log"
        )

    @property
    def runtime_pid_file(self) -> str:
        return str(
            self.runtime_startup.get("pid_file")
            or f"{self.agent_artifact_dir}/software-service.pid"
        )

    @property
    def runtime_artifact_exports(self) -> list[dict[str, str]]:
        exports = self.raw.get("runtime", {}).get("artifact_exports", [])
        if not isinstance(exports, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in exports:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            destination = str(item.get("destination") or "").strip()
            if source and destination:
                normalized.append(
                    {
                        "source": source,
                        "destination": destination,
                    }
                )
        return normalized

    @property
    def default_interaction_mode(self) -> str:
        return normalize_interaction_mode(self.raw["interaction"]["default_mode"])

    @property
    def supported_interaction_modes(self) -> list[str]:
        return [
            normalize_interaction_mode(item)
            for item in self.raw["interaction"]["supported_modes"]
        ]

    @property
    def interaction_adapters(self) -> dict[str, Any]:
        adapters = self.raw["interaction"].get("adapters", {})
        return adapters if isinstance(adapters, dict) else {}

    def interaction_adapter(self, name: str) -> dict[str, Any]:
        name = normalize_interaction_mode(name)
        adapter = self.interaction_adapters.get(name, {})
        if not adapter and name == "computer":
            adapter = self.interaction_adapters.get("computer_use", {})
        return dict(adapter) if isinstance(adapter, dict) else {}

    @property
    def interaction_surfaces(self) -> list[dict[str, Any]]:
        metadata = self.raw.get("metadata", {})
        if not isinstance(metadata, dict):
            return []
        surfaces = metadata.get("interaction_surfaces", [])
        if not isinstance(surfaces, list):
            return []
        normalized: list[dict[str, Any]] = []
        for surface in surfaces:
            if not isinstance(surface, dict):
                continue
            item = dict(surface)
            modes = item.get("modes", [])
            if isinstance(modes, list):
                item["modes"] = [normalize_interaction_mode(mode) for mode in modes]
            elif modes:
                item["modes"] = [normalize_interaction_mode(modes)]
            else:
                item["modes"] = []
            normalized.append(item)
        return normalized

    @property
    def computer_use_server_url(self) -> str:
        return str(
            self.interaction_adapter("computer").get(
                "server_url",
                "http://127.0.0.1:8030",
            )
        )

    @property
    def agent_artifact_dir(self) -> str:
        return str(self.raw["artifacts"]["agent_dir"])

    @property
    def verifier_artifact_dir(self) -> str:
        return str(self.raw["artifacts"]["verifier_dir"])

    @property
    def service_host(self) -> str:
        return str(self.raw["service"]["host"])

    @property
    def service_port(self) -> int:
        return int(self.raw["service"]["port"])

    @property
    def service_health_path(self) -> str:
        return str(self.raw["service"].get("health_path", "/"))

    @property
    def service_api_base_path(self) -> str:
        return str(self.raw["service"].get("api_base_path", "/"))

    @property
    def service_frontend_path(self) -> str:
        return str(self.raw["service"].get("frontend_path", "/"))

    @property
    def service_session_id_field(self) -> str:
        return str(self.raw["service"].get("session_id_field", "session_id"))

    @property
    def service_terminal_field(self) -> str:
        return str(self.raw["service"].get("terminal_field", "terminal"))

    @property
    def service_origin(self) -> str:
        return f"http://{self.service_host}:{self.service_port}"

    @property
    def service_api_base_url(self) -> str:
        return urljoin(self.service_origin + "/", self.service_api_base_path.lstrip("/"))

    @property
    def service_frontend_url(self) -> str:
        return urljoin(self.service_origin + "/", self.service_frontend_path.lstrip("/"))

    @property
    def ground_truth_path(self) -> Path:
        return (self.path.parent / str(self.raw["ground_truth"]["path"])).resolve()

    @property
    def evaluation_method(self) -> str:
        return str(self.raw.get("evaluation", {}).get("method", "targeted_bug"))

    @property
    def target_bug_id(self) -> str:
        return str(self.raw.get("evaluation", {}).get("target_bug_id", ""))

    @property
    def target_hint_level(self) -> str:
        level = (
            str(self.raw.get("evaluation", {}).get("hint_level") or "medium")
            .strip()
            .lower()
            .replace("-", "_")
        )
        if level not in {"weak", "medium", "strong"}:
            return "medium"
        return level

    @property
    def target_hints(self) -> dict[str, str]:
        evaluation = self.raw.get("evaluation", {})
        if not isinstance(evaluation, dict):
            return {}

        hints: dict[str, str] = {}
        raw_hints = evaluation.get("hints", {})
        if isinstance(raw_hints, dict):
            for level in ("weak", "medium", "strong"):
                value = str(raw_hints.get(level) or "").strip()
                if value:
                    hints[level] = value

        legacy_hint = str(evaluation.get("hint") or "").strip()
        if legacy_hint:
            hints.setdefault("medium", legacy_hint)
        return hints

    @property
    def target_hint(self) -> str:
        hints = self.target_hints
        selected = hints.get(self.target_hint_level, "")
        if selected:
            return selected
        for level in ("medium", "weak", "strong"):
            if hints.get(level):
                return hints[level]
        return ""


def load_gbqa_metadata(path: str | Path) -> GBQAMetadata:
    """Load and validate the minimal GBQA task metadata contract."""

    metadata_path = Path(path)
    with metadata_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise GBQAMetadataError("gbqa.yaml must contain a mapping at the top level")

    required = {
        "schema_version": (),
        "task.id": ("task", "id"),
        "software.type": ("software", "type"),
        "software.repository": ("software", "repository"),
        "software.archive_url": ("software", "archive_url"),
        "software.selected_version": ("software", "selected_version"),
        "runtime.default_provider": ("runtime", "default_provider"),
        "interaction.default_mode": ("interaction", "default_mode"),
        "interaction.supported_modes": ("interaction", "supported_modes"),
        "service.host": ("service", "host"),
        "service.port": ("service", "port"),
        "service.api_base_path": ("service", "api_base_path"),
        "service.frontend_path": ("service", "frontend_path"),
        "ground_truth.path": ("ground_truth", "path"),
        "artifacts.agent_dir": ("artifacts", "agent_dir"),
        "artifacts.verifier_dir": ("artifacts", "verifier_dir"),
    }
    for label, keys in required.items():
        value: Any = raw
        if not keys:
            if label not in raw:
                raise GBQAMetadataError(f"Missing required metadata field: {label}")
            continue
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                raise GBQAMetadataError(f"Missing required metadata field: {label}")
            value = value[key]

    modes = raw["interaction"]["supported_modes"]
    if not isinstance(modes, list) or not modes:
        raise GBQAMetadataError("interaction.supported_modes must be a non-empty list")
    normalized_modes = [normalize_interaction_mode(item) for item in modes]
    invalid_modes = [
        mode for mode in normalized_modes if mode not in SUPPORTED_INTERACTION_MODES
    ]
    if invalid_modes:
        raise GBQAMetadataError(
            "interaction.supported_modes contains unsupported modes: "
            + ", ".join(invalid_modes)
        )
    raw["interaction"]["supported_modes"] = list(dict.fromkeys(normalized_modes))
    default_mode = normalize_interaction_mode(raw["interaction"]["default_mode"])
    raw["interaction"]["default_mode"] = default_mode
    if default_mode not in normalized_modes:
        raise GBQAMetadataError(
            "interaction.default_mode must be included in interaction.supported_modes"
        )

    return GBQAMetadata(path=metadata_path, raw=raw)
