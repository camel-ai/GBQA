"""Versioned run specification exported with QA agent reports."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


def build_run_spec(
    *,
    task_id: str,
    task_slug: str,
    environment_id: str,
    harness_mode: str,
    interaction_mode: str,
    interaction_profile: str,
    enabled_interaction_modes: list[str],
    backend_type: str,
    model: str,
    model_platform: str,
    llm_config: Dict[str, Any],
    agent_config: Dict[str, Any],
    operator_config: Dict[str, Any],
    memory_config: Dict[str, Any],
    tool_policy: Dict[str, Any],
    hook_policy: Dict[str, Any],
    tool_registry_policy: Dict[str, Any],
    subagent_policy: Dict[str, Any] | None = None,
    config_resolution: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a serializable run spec for reproducible harness experiments."""

    return {
        "schema_version": "0.1",
        "task": {
            "id": task_id,
            "slug": task_slug,
            "environment_id": environment_id,
        },
        "interaction": {
            "profile": interaction_profile,
            "mode": interaction_mode,
            "enabled_modes": list(enabled_interaction_modes),
            "backend_type": backend_type,
        },
        "harness": {
            "mode": harness_mode,
        },
        "roles": {
            "planner": _role_model("planner", model, model_platform, llm_config),
            "operator": _role_model("operator", model, model_platform, llm_config),
            "reflection": _role_model("reflection", model, model_platform, llm_config),
            "bug_review": _role_model("bug_review", model, model_platform, llm_config),
            "summary": _role_model("summary", model, model_platform, llm_config),
        },
        "agent_policy": deepcopy(agent_config),
        "operator_policy": deepcopy(operator_config),
        "memory_policy": deepcopy(memory_config),
        "tool_policy": deepcopy(tool_policy),
        "hook_policy": deepcopy(hook_policy),
        "subagent_policy": deepcopy(subagent_policy or {}),
        "tool_registry": deepcopy(tool_registry_policy),
        "config": deepcopy(config_resolution or {}),
    }


def _role_model(
    role: str,
    model: str,
    platform: str,
    llm_config: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "role": role,
        "model": model,
        "platform": platform,
        "temperature": llm_config.get("temperature"),
        "max_tokens": llm_config.get("max_tokens"),
        "input_token_limit": llm_config.get("input_token_limit"),
        "reasoning": deepcopy(llm_config.get("reasoning", {})),
        "timeout": llm_config.get("timeout"),
    }
