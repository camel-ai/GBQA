"""Layered configuration resolution for the QA agent harness."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable
import os
import tomllib


@dataclass(frozen=True)
class ConfigLayer:
    """One configuration input in the harness precedence stack."""

    name: str
    source: str
    data: Dict[str, Any]


@dataclass(frozen=True)
class ConfigResolution:
    """Final resolved config plus enough provenance for run_spec export."""

    layers: list[ConfigLayer]
    resolved: Dict[str, Any]
    root_dir: str
    config_path: str

    @property
    def precedence(self) -> list[str]:
        """Return layer names from highest to lowest precedence."""

        return [layer.name for layer in reversed(self.layers)]


def load_toml_dict(
    path: str | os.PathLike[str],
    *,
    require_toml_suffix: bool = True,
) -> Dict[str, Any]:
    """Load a TOML file as a top-level dict."""

    resolved_path = Path(path).expanduser().resolve()
    if require_toml_suffix and resolved_path.suffix != ".toml":
        raise ValueError("Agent config must be a .toml file")
    with resolved_path.open("rb") as file_handle:
        payload = tomllib.load(file_handle)
    if not isinstance(payload, dict):
        raise ValueError("Agent config must contain a TOML table at the top level")
    return payload


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge dicts, with ``overlay`` taking precedence."""

    merged = deepcopy(base)
    for key, value in overlay.items():
        if (
            isinstance(value, dict)
            and isinstance(merged.get(key), dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def build_config_resolution(
    *,
    config_path: str,
    repo_default_path: str | None = None,
    task_metadata_config: Dict[str, Any] | None = None,
    task_metadata_source: str | None = None,
    cli_overrides: Dict[str, Any] | None = None,
) -> ConfigResolution:
    """Resolve the GBQA harness config using the documented precedence stack."""

    resolved_config_path = Path(config_path).expanduser().resolve()
    layers = [
        ConfigLayer(
            name="built_in_defaults",
            source="agent.src.config_layers.built_in_defaults",
            data=built_in_defaults(),
        ),
        ConfigLayer(
            name="repo_harness_default_config",
            source=str(Path(repo_default_path).expanduser().resolve())
            if repo_default_path
            else "",
            data=_load_optional_toml(repo_default_path),
        ),
        ConfigLayer(
            name="task_package_gbqa_yaml",
            source=task_metadata_source or "",
            data=task_metadata_config or {},
        ),
        ConfigLayer(
            name="trial_run_config",
            source=str(resolved_config_path),
            data=load_toml_dict(resolved_config_path),
        ),
        ConfigLayer(
            name="cli_overrides",
            source="run_agent.py argv; Harbor --ak values are materialized in trial_run_config",
            data=cli_overrides or {},
        ),
    ]
    resolved: Dict[str, Any] = {}
    for layer in layers:
        resolved = deep_merge(resolved, layer.data)
    return ConfigResolution(
        layers=layers,
        resolved=resolved,
        root_dir=str(resolved_config_path.parent),
        config_path=str(resolved_config_path),
    )


def config_resolution_for_run_spec(
    resolution: ConfigResolution,
    *,
    final_config: Dict[str, Any] | None = None,
    normalizers: Iterable[str] = (),
) -> Dict[str, Any]:
    """Build a redacted run_spec payload for config reproducibility."""

    return {
        "schema_version": "0.1",
        "precedence": resolution.precedence,
        "merge_order": [layer.name for layer in resolution.layers],
        "config_path": resolution.config_path,
        "root_dir": resolution.root_dir,
        "normalizers": list(normalizers),
        "layers": [
            {
                "name": layer.name,
                "source": layer.source,
                "active": bool(layer.data),
                "key_paths": sorted(_key_paths(layer.data)),
            }
            for layer in reversed(resolution.layers)
        ],
        "resolved": redact_config(
            final_config if final_config is not None else resolution.resolved
        ),
    }


def redact_config(value: Any) -> Any:
    """Return a config copy safe for reports and run artifacts."""

    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for child_key, child_value in value.items():
            if _is_secret_key(str(child_key)):
                redacted[child_key] = "<redacted>"
            else:
                redacted[child_key] = redact_config(child_value)
        return redacted
    if isinstance(value, list):
        return [redact_config(item) for item in value]
    return deepcopy(value)


def built_in_defaults() -> Dict[str, Any]:
    """Hard-coded fallback defaults before repo/task/trial/CLI layers."""

    return {
        "run": {
            "harness_mode": "minimal",
            "interaction_profile": "default",
            "interaction_mode": "terminal",
        },
        "harness": {
            "mode": "minimal",
        },
        "llm": {
            "platform": "auto",
            "temperature": 0.5,
            "max_tokens": 4096,
            "input_token_limit": 12000,
            "reasoning": {
                "mode": "auto",
                "effort": "",
            },
            "timeout": 60,
        },
        "agent": {
            "max_steps": 50,
            "max_consecutive_failures": 5,
            "reflection_threshold": 3,
            "reflection_interval": 10,
            "log_analysis_interval": 20,
            "auto_summarize": True,
            "summary_threshold": 15,
            "summary_interval": 40,
            "confidence_threshold": 0.7,
            "verbose": True,
            "prompt_dir": "prompts",
        },
        "interaction": {
            "profile": "default",
            "primary_mode": "terminal",
            "primary": "api",
            "enabled_modes": ["terminal"],
            "enabled_backends": ["api"],
            "adapters": {
                "api": {},
                "playwright_mcp": {},
                "computer_use": {},
                "logs": {
                    "enabled": False,
                },
                "code": {
                    "enabled": False,
                },
            },
        },
        "operator": {
            "max_retries": 2,
            "retryable_error_kinds": [
                "tool_not_found",
                "element_not_found",
                "timeout",
                "not_visible",
            ],
        },
        "tool_policy": {
            "auto_log_analysis": {
                "enabled": False,
                "interval_steps": 20,
                "on_findings": True,
                "consecutive_failures_threshold": 3,
            },
            "auto_code_lookup": {
                "enabled": False,
                "min_confidence": 0.7,
            },
            "end_conditions": {
                "end_on_terminal": False,
            },
        },
        "hooks": {
            "enabled": True,
            "run": True,
            "planner": True,
            "tool_calls": True,
            "steps": True,
            "lifecycle": True,
            "bugs": True,
            "summaries": True,
            "coverage_recording": True,
            "artifact_export": True,
            "diagnostics": False,
            "context_injection": False,
        },
        "subagents": {
            "enabled": False,
            "context_isolation": "per_invocation",
            "share_full_trace": False,
            "max_prompt_chars": 6000,
            "record_prompts": False,
            "explorer": {
                "enabled": False,
                "interval_steps": 5,
            },
            "reproducer": {
                "enabled": False,
                "on_new_hypothesis": True,
            },
            "log_analyst": {
                "enabled": False,
                "read_logs": True,
            },
            "code_localizer": {
                "enabled": False,
                "read_code": True,
            },
        },
        "memory": {
            "max_short_term": 100,
            "memory_context_token_limit": 12000,
            "long_term_file": "memory/{task_slug}/long_term.json",
            "load_persistent_long_term": False,
            "cross_session_enabled": False,
            "cross_session_top_k": 3,
            "cross_session_similarity": 0.2,
        },
        "report": {
            "output_dir": "reports",
            "format": "both",
            "auto_save": True,
        },
        "bug_detection": {
            "enable_llm_analysis": True,
            "auto_confirm_threshold": 0.8,
            "rules": [
                "error_message",
                "state_consistency",
                "response_format",
                "duplicate_item",
            ],
        },
    }


def _load_optional_toml(path: str | None) -> Dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return {}
    return load_toml_dict(candidate, require_toml_suffix=False)


def _key_paths(value: Any, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return {prefix} if prefix else set()
    paths: set[str] = set()
    for key, child in value.items():
        child_prefix = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            child_paths = _key_paths(child, child_prefix)
            if child_paths:
                paths.update(child_paths)
            else:
                paths.add(child_prefix)
        else:
            paths.add(child_prefix)
    return paths


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "password",
        "authorization",
    }:
        return True
    return normalized.endswith(("_api_key", "_token", "_secret", "_password"))
