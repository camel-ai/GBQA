"""Configuration rendering for Harbor-run GBQA agent trials."""

from __future__ import annotations

from typing import Any

import yaml

from gbqa.spec import GBQAMetadata


def render_agent_config(
    *,
    metadata: GBQAMetadata,
    interaction_mode: str,
    max_steps: int,
    report_output_dir: str = "/logs/agent/gbqa/raw_reports",
    prompt_dir: str = "/sandbox/agent/prompts",
    screenshot_dir: str = "/logs/agent/gbqa/artifacts/screenshots",
) -> str:
    """Render an agent config that targets services inside the sandbox."""

    if interaction_mode not in metadata.supported_interaction_modes:
        raise ValueError(f"Unsupported GBQA interaction mode: {interaction_mode}")

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
    backend_by_mode = {
        "api": "api",
        "browser": "playwright_mcp",
        "computer_use": "computer_use",
    }
    backend_type = backend_by_mode.get(interaction_mode)
    if backend_type is None:
        raise ValueError(f"Unsupported GBQA interaction mode: {interaction_mode}")

    payload: dict[str, Any] = {
        "run": {
            "task_id": metadata.task_id,
            "interaction_mode": interaction_mode,
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
            "primary": backend_type,
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
                    "enabled": False,
                    "base_url": base_url,
                    "timeout": 60,
                },
                "logs": {
                    "enabled": True,
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
    return yaml.safe_dump(payload, sort_keys=False)
