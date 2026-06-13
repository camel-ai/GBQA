"""Configuration rendering for Harbor-run GBQA agent trials."""

from __future__ import annotations

import json
import re
from typing import Any

from gbqa.spec import GBQAMetadata

_BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(key: str) -> str:
    if _BARE_TOML_KEY.match(key):
        return key
    return json.dumps(key)


def _toml_path(path: list[str]) -> str:
    return ".".join(_toml_key(part) for part in path)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        if any(isinstance(item, dict) for item in value):
            raise TypeError("Lists of tables must be emitted as TOML array tables")
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML value type: {type(value).__name__}")


def _is_array_table(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def _emit_toml_table(payload: dict[str, Any], path: list[str], lines: list[str]) -> None:
    for key, value in payload.items():
        if isinstance(value, dict) or _is_array_table(value):
            continue
        lines.append(f"{_toml_key(str(key))} = {_toml_value(value)}")

    for key, value in payload.items():
        key_path = [*path, str(key)]
        if isinstance(value, dict):
            lines.append("")
            lines.append(f"[{_toml_path(key_path)}]")
            _emit_toml_table(value, key_path, lines)
        elif _is_array_table(value):
            for item in value:
                lines.append("")
                lines.append(f"[[{_toml_path(key_path)}]]")
                _emit_toml_table(item, key_path, lines)


def _dumps_toml(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    _emit_toml_table(payload, [], lines)
    return "\n".join(lines).strip() + "\n"


_BACKEND_BY_INTERACTION_MODE = {
    "api": "api",
    "browser": "playwright_mcp",
    "computer_use": "computer_use",
}


def _normalize_interaction_profile(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return text or "default"


def _resolve_interaction_profile(
    *,
    requested: str,
    metadata: GBQAMetadata,
) -> tuple[str, str, list[str]]:
    profile = _normalize_interaction_profile(requested)
    supported_modes = [
        _normalize_interaction_profile(mode)
        for mode in metadata.supported_interaction_modes
    ]
    default_mode = _normalize_interaction_profile(metadata.default_interaction_mode)
    if profile == "default":
        return "default", default_mode, supported_modes
    if profile not in supported_modes:
        raise ValueError(f"Unsupported GBQA interaction profile: {requested}")
    return profile, profile, [profile]


def _normalize_harness_mode(value: str) -> str:
    mode = str(value or "minimal").strip().lower().replace("-", "_")
    if mode == "bare":
        mode = "minimal"
    if mode not in {"minimal", "full"}:
        raise ValueError("harness_mode must be one of: minimal, full")
    return mode


def render_agent_config(
    *,
    metadata: GBQAMetadata,
    interaction_mode: str,
    max_steps: int,
    harness_mode: str = "minimal",
    report_output_dir: str = "/logs/agent/gbqa/raw_reports",
    prompt_dir: str = "/sandbox/agent/prompts",
    screenshot_dir: str = "/logs/agent/gbqa/artifacts/screenshots",
) -> str:
    """Render an agent config that targets services inside the sandbox."""

    interaction_profile, primary_mode, enabled_modes = _resolve_interaction_profile(
        requested=interaction_mode,
        metadata=metadata,
    )
    harness_mode = _normalize_harness_mode(harness_mode)
    diagnostics_enabled = harness_mode == "full"

    base_url = metadata.service_api_base_url
    frontend_url = metadata.service_frontend_url
    computer_use_settings = {
        "server_url": "http://127.0.0.1:8030",
        "startup_timeout": 30,
        "sandbox_name": "gbqa-local-computer",
        "display": {
            "width": 1280,
            "height": 720,
        },
        **metadata.interaction_adapter("computer_use"),
        "frontend_url": frontend_url,
        "screenshot_dir": screenshot_dir,
    }
    backend_type = _BACKEND_BY_INTERACTION_MODE.get(primary_mode)
    if backend_type is None:
        raise ValueError(f"Unsupported GBQA interaction mode: {primary_mode}")

    payload: dict[str, Any] = {
        "run": {
            "task_id": metadata.task_id,
            "task_metadata_path": f"/sandbox/gbqa/tasks/{metadata.task_slug}/gbqa.yaml",
            "harness_mode": harness_mode,
            "interaction_profile": interaction_profile,
            "interaction_mode": primary_mode,
            "enabled_interaction_modes": list(enabled_modes),
        },
        "harness": {
            "mode": harness_mode,
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
            "max_steps": max_steps,
            "max_consecutive_failures": 5,
            "reflection_threshold": 3,
            "reflection_interval": 10,
            "log_analysis_interval": 20,
            "auto_summarize": True,
            "summary_threshold": 15,
            "summary_interval": 40,
            "confidence_threshold": 0.7,
            "verbose": True,
            "prompt_dir": prompt_dir,
        },
        "interaction": {
            "profile": interaction_profile,
            "primary_mode": primary_mode,
            "primary": backend_type,
            "enabled_modes": list(enabled_modes),
            "enabled_backends": [
                _BACKEND_BY_INTERACTION_MODE[mode]
                for mode in enabled_modes
            ],
            "adapters": {
                "api": {
                    "base_url": base_url,
                    "timeout": 60,
                    "session_id_field": metadata.service_session_id_field,
                    "terminal_field": metadata.service_terminal_field,
                },
                "playwright_mcp": {
                    "command": [
                        "npx",
                        "-y",
                        "@playwright/mcp@latest",
                        "--headless",
                        "--browser",
                        "chromium",
                    ],
                    "startup_timeout": 30,
                    "frontend_url": frontend_url,
                    "snapshot_tool": "browser_snapshot",
                    "screenshot_tool": "browser_take_screenshot",
                    "navigate_tool": "browser_navigate",
                    "click_tool": "browser_click",
                    "type_tool": "browser_type",
                    "press_tool": "browser_press_key",
                    "wait_tool": "browser_wait_for",
                    "screenshot_dir": screenshot_dir,
                },
                "computer_use": computer_use_settings,
                "code": {
                    "enabled": diagnostics_enabled,
                    "base_url": base_url,
                    "root_dir": metadata.software_install_dir,
                    "timeout": 60,
                },
                "logs": {
                    "enabled": diagnostics_enabled,
                    "base_url": base_url,
                    "timeout": 60,
                    "session_id_field": metadata.service_session_id_field,
                    "sources": metadata.internal_log_sources,
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
                "enabled": diagnostics_enabled,
                "interval_steps": 20,
                "on_findings": True,
                "consecutive_failures_threshold": 3,
            },
            "auto_code_lookup": {
                "enabled": diagnostics_enabled,
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
            "diagnostics": diagnostics_enabled,
            "context_injection": diagnostics_enabled,
        },
        "subagents": {
            "enabled": diagnostics_enabled,
            "context_isolation": "per_invocation",
            "share_full_trace": False,
            "max_prompt_chars": 6000,
            "record_prompts": False,
            "explorer": {
                "enabled": diagnostics_enabled,
                "interval_steps": 5,
            },
            "reproducer": {
                "enabled": diagnostics_enabled,
                "on_new_hypothesis": True,
            },
            "log_analyst": {
                "enabled": diagnostics_enabled,
                "read_logs": True,
            },
            "code_localizer": {
                "enabled": diagnostics_enabled,
                "read_code": True,
            },
        },
        "memory": {
            "max_short_term": 100,
            "memory_context_token_limit": 12000,
            "long_term_file": "/logs/agent/gbqa/memory/{task_slug}/long_term.json",
            "load_persistent_long_term": False,
            "cross_session_enabled": False,
            "cross_session_top_k": 3,
            "cross_session_similarity": 0.2,
        },
        "tasks": {
            metadata.task_slug: {
                "id": metadata.task_id,
                "slug": metadata.task_slug,
                "port": metadata.service_port,
                "base_url": base_url,
                "frontend_url": frontend_url,
                "session_id_field": metadata.service_session_id_field,
                "terminal_field": metadata.service_terminal_field,
                "name": metadata.task_title,
                "ground_truth": False,
                "profile": metadata.agent_profile,
            }
        },
        "report": {
            "output_dir": report_output_dir,
            "format": "both",
            "auto_save": True,
        },
        "evaluation": {
            "match_threshold": 0.65,
            "llm_threshold": 0.6,
            "use_llm": False,
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
    return _dumps_toml(payload)
