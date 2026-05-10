"""GBQA task metadata loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import yaml


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
    def default_provider(self) -> str:
        return str(self.raw["runtime"]["default_provider"])

    @property
    def default_interaction_mode(self) -> str:
        return str(self.raw["interaction"]["default_mode"])

    @property
    def supported_interaction_modes(self) -> list[str]:
        return [str(item) for item in self.raw["interaction"]["supported_modes"]]

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
    default_mode = raw["interaction"]["default_mode"]
    if default_mode not in modes:
        raise GBQAMetadataError(
            "interaction.default_mode must be included in interaction.supported_modes"
        )

    return GBQAMetadata(path=metadata_path, raw=raw)
