"""Run the Agent against a target benchmark task."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bug_detector import BugDetector
from src.camel_runtime import resolve_model_platform
from src.config import Config
from src.config_layers import (
    build_config_resolution,
    config_resolution_for_run_spec,
    load_toml_dict,
)
from src.evaluator import Evaluator
from src.execution_backends import (
    MultiModeExecutionBackend,
    backend_type_for_interaction_mode,
    build_execution_backend,
    normalize_interaction_mode,
    resolve_backend_spec,
)
from src.environment_clients import (
    EnvironmentClientConfig,
    create_http_code_tool_adapter,
)
from src.ground_truth import resolve_ground_truth_path
from src.hooks import HookManager, normalize_hook_policy
from src.llm_client import DEFAULT_BASE_URL, LlmClient
from src.log_sources import AgentTrajectoryLogSource, build_log_sources
from src.memory import MemoryManager
from src.operator import Operator
from src.orchestrator import Orchestrator
from src.planner import ActionPlanner
from src.prompts import PromptLoader
from src.reflection import ReflectionAnalyzer
from src.reporter import Reporter
from src.log_analyzer import LogAnalyzer
from src.run_spec import build_run_spec
from src.subagents import SubagentManager, normalize_subagent_policy
from src.tool_registry import (
    Tool,
    ToolInvocationResult,
    ToolRegistry,
    register_code_tools,
    register_environment_action_tool,
    register_log_tools,
)
from src.codebase_types import UniversalCodebaseAdapter
from src.types import Action


_INTERACTION_TOOL_BY_MODE = {
    "api": "api_action",
    "browser": "browser_action",
    "computer_use": "computer_action",
}

_INTERACTION_TOOL_DESCRIPTIONS = {
    "api": (
        "Execute one semantic action through the task backend API interaction mode"
    ),
    "browser": (
        "Execute one semantic action through the browser UI interaction mode"
    ),
    "computer_use": (
        "Execute one semantic action through screenshot-based GUI computer-use mode"
    ),
}

_HARNESS_MODES = {"minimal", "full"}


def _normalize_harness_mode(value: Any) -> str:
    mode = str(value or "minimal").strip().lower().replace("-", "_")
    if mode == "bare":
        mode = "minimal"
    if mode not in _HARNESS_MODES:
        raise ValueError("harness_mode must be one of: minimal, full")
    return mode


def _resolve_harness_mode(config) -> str:  # noqa: ANN001
    run_section = config.get_section("run")
    harness_section = config.get_section("harness")
    return _normalize_harness_mode(
        run_section.get("harness_mode")
        or harness_section.get("mode")
        or "minimal"
    )


def _repo_harness_default_config_path() -> str:
    return str(Path(__file__).resolve().with_name("config.toml.example"))


def _cli_config_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.interaction_profile:
        overrides.setdefault("run", {})["interaction_profile"] = args.interaction_profile
    if args.harness_mode:
        overrides.setdefault("run", {})["harness_mode"] = args.harness_mode
        overrides.setdefault("harness", {})["mode"] = args.harness_mode
    if args.max_steps is not None:
        overrides.setdefault("agent", {})["max_steps"] = args.max_steps
    return overrides


def _resolve_config_relative_path(config_path: str, value: str) -> str:
    if os.path.isabs(value):
        return value
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(config_path)), value)
    )


def _resolve_task_metadata_path(
    *,
    config_path: str,
    requested_metadata_path: str | None,
) -> str | None:
    if requested_metadata_path:
        return _resolve_config_relative_path(config_path, requested_metadata_path)
    trial_config = load_toml_dict(config_path)
    run_section = trial_config.get("run", {})
    if not isinstance(run_section, dict):
        return None
    metadata_path = str(run_section.get("task_metadata_path") or "").strip()
    if not metadata_path:
        return None
    resolved_metadata_path = _resolve_config_relative_path(config_path, metadata_path)
    if os.path.exists(resolved_metadata_path):
        return resolved_metadata_path
    return None


def _apply_harness_mode(config, harness_mode: str) -> None:  # noqa: ANN001
    harness = config.raw.setdefault("harness", {})
    if not isinstance(harness, dict):
        harness = {}
        config.raw["harness"] = harness
    harness["mode"] = harness_mode
    run_section = config.raw.setdefault("run", {})
    if isinstance(run_section, dict):
        run_section["harness_mode"] = harness_mode

    interaction = config.raw.setdefault("interaction", {})
    adapters = interaction.setdefault("adapters", {})
    if not isinstance(adapters, dict):
        adapters = {}
        interaction["adapters"] = adapters
    logs = adapters.setdefault("logs", {})
    if not isinstance(logs, dict):
        logs = {}
        adapters["logs"] = logs
    code = adapters.setdefault("code", {})
    if not isinstance(code, dict):
        code = {}
        adapters["code"] = code

    tool_policy = config.raw.setdefault("tool_policy", {})
    if not isinstance(tool_policy, dict):
        tool_policy = {}
        config.raw["tool_policy"] = tool_policy
    auto_log = tool_policy.setdefault("auto_log_analysis", {})
    if not isinstance(auto_log, dict):
        auto_log = {}
        tool_policy["auto_log_analysis"] = auto_log
    auto_code = tool_policy.setdefault("auto_code_lookup", {})
    if not isinstance(auto_code, dict):
        auto_code = {}
        tool_policy["auto_code_lookup"] = auto_code

    memory = config.raw.setdefault("memory", {})
    if not isinstance(memory, dict):
        memory = {}
        config.raw["memory"] = memory

    if harness_mode == "minimal":
        logs["enabled"] = False
        code["enabled"] = False
        auto_log["enabled"] = False
        auto_code["enabled"] = False
        memory["load_persistent_long_term"] = False
        memory["cross_session_enabled"] = False
    else:
        logs["enabled"] = True
        code["enabled"] = True
        auto_log["enabled"] = True
        auto_code["enabled"] = True
    hooks = config.raw.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        config.raw["hooks"] = hooks
    hooks.update(normalize_hook_policy(hooks, harness_mode=harness_mode))

    subagents = config.raw.setdefault("subagents", {})
    if not isinstance(subagents, dict):
        subagents = {}
        config.raw["subagents"] = subagents
    if harness_mode == "minimal":
        subagents["enabled"] = False
    else:
        subagents["enabled"] = True
        for worker_name in (
            "explorer",
            "reproducer",
            "log_analyst",
            "code_localizer",
        ):
            worker_policy = subagents.setdefault(worker_name, {})
            if isinstance(worker_policy, dict):
                worker_policy["enabled"] = True
    subagents.update(
        normalize_subagent_policy(subagents, harness_mode=harness_mode)
    )


def _resolve_interaction_profile(
    *,
    requested: Any,
    supported_modes: list[str],
    default_mode: str,
) -> tuple[str, str, list[str]]:
    profile = normalize_interaction_mode(requested)
    supported = [normalize_interaction_mode(item) for item in supported_modes]
    primary_mode = normalize_interaction_mode(default_mode)
    if primary_mode == "default":
        primary_mode = supported[0] if supported else "api"
    if profile == "default":
        if primary_mode not in supported:
            raise ValueError(
                "Task default interaction mode is not in supported modes: "
                + primary_mode
            )
        return "default", primary_mode, supported
    if profile not in supported:
        raise ValueError("Unsupported interaction profile for task metadata: " + profile)
    return profile, profile, [profile]


def _resolve_task_endpoints(
    *,
    backend_type: str,
    backend_settings: dict,
    task_id: str,
    task_config: dict,
) -> tuple[str, str]:
    port = task_config.get("port")
    service_base_url = str(
        task_config.get("base_url") or backend_settings.get("base_url") or ""
    ).strip()
    configured_frontend_url = str(
        task_config.get("frontend_url") or backend_settings.get("frontend_url") or ""
    ).strip()

    if backend_type == "api":
        if not service_base_url and port is None:
            raise ValueError(
                f"api backend for '{task_id}' requires either 'base_url' or 'port'"
            )
    elif (
        backend_type in {"playwright_mcp", "computer_use"}
        and port is None
        and not configured_frontend_url
    ):
        raise ValueError(
            f"Task config for '{task_id}' must provide at least one of 'port' or 'frontend_url'"
        )

    if not service_base_url and port is not None:
        service_base_url = f"http://localhost:{port}/api/agent"
    frontend_url = configured_frontend_url
    if not frontend_url and port is not None:
        frontend_url = f"http://localhost:{port}"
    return service_base_url, frontend_url


def _task_metadata_config_layer(metadata_path: str) -> dict[str, Any]:
    """Convert task package metadata into the task-package config layer."""

    from gbqa.spec import load_gbqa_metadata

    metadata = load_gbqa_metadata(metadata_path)
    default_mode = normalize_interaction_mode(metadata.default_interaction_mode)
    backend_type = backend_type_for_interaction_mode(default_mode)
    enabled_modes = [
        normalize_interaction_mode(mode)
        for mode in metadata.supported_interaction_modes
    ]
    enabled_backends = [
        backend_type_for_interaction_mode(mode)
        for mode in enabled_modes
    ]
    return {
        "run": {
            "task_id": metadata.task_id,
            "task_metadata_path": metadata_path,
            "interaction_mode": default_mode,
            "enabled_interaction_modes": enabled_modes,
        },
        "interaction": {
            "primary_mode": default_mode,
            "primary": backend_type,
            "enabled_modes": enabled_modes,
            "enabled_backends": enabled_backends,
            "adapters": {
                "api": {
                    "base_url": metadata.service_api_base_url,
                    "session_id_field": metadata.service_session_id_field,
                    "terminal_field": metadata.service_terminal_field,
                },
                "playwright_mcp": {
                    "frontend_url": metadata.service_frontend_url,
                },
                "computer_use": {
                    **metadata.interaction_adapter("computer_use"),
                    "server_url": "http://127.0.0.1:8030",
                    "frontend_url": metadata.service_frontend_url,
                    "startup_timeout": 30,
                    "sandbox_name": "gbqa-local-computer",
                    "display": {"width": 1280, "height": 720},
                },
                "code": {
                    "enabled": False,
                    "base_url": metadata.service_api_base_url,
                    "timeout": 60,
                },
                "logs": {
                    "enabled": True,
                    "base_url": metadata.service_api_base_url,
                    "timeout": 60,
                    "session_id_field": metadata.service_session_id_field,
                    "sources": metadata.internal_log_sources,
                },
            },
        },
        "tasks": {
            metadata.task_slug: {
                "id": metadata.task_id,
                "slug": metadata.task_slug,
                "port": metadata.service_port,
                "base_url": metadata.service_api_base_url,
                "frontend_url": metadata.service_frontend_url,
                "session_id_field": metadata.service_session_id_field,
                "terminal_field": metadata.service_terminal_field,
                "name": metadata.task_title,
                "ground_truth": False,
                "profile": metadata.agent_profile,
                "supported_interaction_modes": list(metadata.supported_interaction_modes),
                "default_interaction_mode": metadata.default_interaction_mode,
            },
        },
    }


def build_log_tool_sources(log_config: dict[str, Any]) -> list[Any]:
    """Build final log-tool sources from configured internal logs and trajectory."""
    if not log_config.get("enabled", False):
        return []
    configured_sources = log_config.get("sources", [])
    if not isinstance(configured_sources, list):
        configured_sources = []
    return [AgentTrajectoryLogSource(), *build_log_sources(configured_sources)]


def _apply_task_metadata(config, metadata_path: str) -> None:  # noqa: ANN001
    """Inject task/environment metadata into the QA-agent harness config."""

    from gbqa.spec import load_gbqa_metadata

    metadata = load_gbqa_metadata(metadata_path)
    run_section = config.get_section("run")
    interaction_profile, primary_mode, enabled_modes = _resolve_interaction_profile(
        requested=(
            run_section.get("interaction_profile")
            or run_section.get("profile")
            or run_section.get("interaction_mode")
            or metadata.default_interaction_mode
        ),
        supported_modes=metadata.supported_interaction_modes,
        default_mode=(
            run_section.get("interaction_mode")
            or metadata.default_interaction_mode
        ),
    )
    backend_type = backend_type_for_interaction_mode(primary_mode)
    run_section["interaction_profile"] = interaction_profile
    run_section["interaction_mode"] = primary_mode
    run_section["enabled_interaction_modes"] = list(enabled_modes)
    interaction = config.raw.setdefault("interaction", {})
    interaction["profile"] = interaction_profile
    interaction["primary_mode"] = primary_mode
    interaction["primary"] = backend_type
    interaction["enabled_modes"] = list(enabled_modes)
    interaction["enabled_backends"] = [
        backend_type_for_interaction_mode(mode)
        for mode in enabled_modes
    ]
    adapters = interaction.setdefault("adapters", {})

    api_settings = adapters.setdefault("api", {})
    if isinstance(api_settings, dict):
        api_settings.setdefault("base_url", metadata.service_api_base_url)
        api_settings.setdefault("session_id_field", metadata.service_session_id_field)
        api_settings.setdefault("terminal_field", metadata.service_terminal_field)

    playwright_settings = adapters.setdefault("playwright_mcp", {})
    if isinstance(playwright_settings, dict):
        playwright_settings.setdefault("frontend_url", metadata.service_frontend_url)

    computer_use_settings = adapters.setdefault("computer_use", {})
    if isinstance(computer_use_settings, dict):
        metadata_computer_use = metadata.interaction_adapter("computer_use")
        for key, value in metadata_computer_use.items():
            computer_use_settings.setdefault(key, value)
        computer_use_settings.setdefault("server_url", "http://127.0.0.1:8030")
        computer_use_settings.setdefault("frontend_url", metadata.service_frontend_url)
        computer_use_settings.setdefault("startup_timeout", 30)
        computer_use_settings.setdefault("sandbox_name", "gbqa-local-computer")
        computer_use_settings.setdefault("display", {"width": 1280, "height": 720})

    code_settings = adapters.setdefault("code", {})
    if isinstance(code_settings, dict):
        code_settings.setdefault("enabled", False)
        code_settings.setdefault("base_url", metadata.service_api_base_url)
        code_settings.setdefault("timeout", 60)

    log_settings = adapters.setdefault("logs", {})
    if isinstance(log_settings, dict):
        log_settings.setdefault("enabled", True)
        log_settings.setdefault("base_url", metadata.service_api_base_url)
        log_settings.setdefault("timeout", 60)
        log_settings.setdefault("session_id_field", metadata.service_session_id_field)
        log_settings.setdefault("sources", metadata.internal_log_sources)

    tasks = config.raw.setdefault("tasks", {})
    if not isinstance(tasks, dict):
        tasks = {}
        config.raw["tasks"] = tasks
    task_entry = tasks.setdefault(metadata.task_slug, {})
    if not isinstance(task_entry, dict):
        task_entry = {}
        tasks[metadata.task_slug] = task_entry
    task_defaults = {
        "id": metadata.task_id,
        "slug": metadata.task_slug,
        "port": metadata.service_port,
        "base_url": metadata.service_api_base_url,
        "frontend_url": metadata.service_frontend_url,
        "session_id_field": metadata.service_session_id_field,
        "terminal_field": metadata.service_terminal_field,
        "name": metadata.task_title,
        "ground_truth": False,
        "profile": metadata.agent_profile,
        "supported_interaction_modes": list(metadata.supported_interaction_modes),
        "default_interaction_mode": metadata.default_interaction_mode,
    }
    for key, value in task_defaults.items():
        task_entry.setdefault(key, value)


def _register_interaction_mode_tools(
    *,
    registry: ToolRegistry,
    enabled_modes: list[str],
    primary_mode: str,
    operator: Operator,
    backend,
    task_id: str,
) -> None:
    if len(enabled_modes) <= 1:
        return

    def _make_handler(mode: str):
        def _handle_mode_action(payload, runtime_context):  # noqa: ANN001
            action_text = str(payload.get("action", "")).strip()
            planner_action = runtime_context.get("planner_action")
            source_action = (
                planner_action
                if isinstance(planner_action, Action)
                else Action(
                    command=action_text,
                    tool=_INTERACTION_TOOL_BY_MODE.get(mode, "environment_action"),
                )
            )
            parent_session = runtime_context.get("session")
            target_backend = backend
            target_session = parent_session
            if isinstance(backend, MultiModeExecutionBackend):
                target_backend = backend.backend_for_mode(mode)
                target_session = backend.ensure_mode_session(parent_session, mode)
            capability = target_backend.describe_capabilities(target_session)
            result = operator.execute(
                action=Action(
                    command=action_text,
                    tool=source_action.tool,
                    rationale=source_action.rationale,
                    expected_outcome=source_action.expected_outcome,
                    bug_exist=source_action.bug_exist,
                    confidence=source_action.confidence,
                    explanation=source_action.explanation,
                ),
                current_observation=runtime_context["current_observation"],
                capability=capability,
                session=target_session,
                backend=target_backend,
            )
            result.observation.execution.setdefault("diagnostics", {})
            result.observation.execution["diagnostics"]["interaction_mode"] = mode
            result.observation.execution["diagnostics"]["task_id"] = task_id
            return ToolInvocationResult(observation=result.observation)

        return _handle_mode_action

    for mode in enabled_modes:
        normalized = normalize_interaction_mode(mode)
        tool_name = _INTERACTION_TOOL_BY_MODE.get(normalized)
        if not tool_name:
            continue
        primary_note = " Primary/default mode." if normalized == primary_mode else ""
        registry.register(
            Tool(
                name=tool_name,
                description=_INTERACTION_TOOL_DESCRIPTIONS[normalized] + primary_note,
                action_format="semantic action string",
                handler=_make_handler(normalized),
                action_parser=lambda action_text: {"action": str(action_text).strip()},
                input_schema={
                    "type": "object",
                    "properties": {"action": {"type": "string"}},
                    "required": ["action"],
                },
                side_effect="environment",
            )
        )


def main() -> None:
    dotenv.load_dotenv(dotenv_path=REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Run QA Agent")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.toml"),
    )
    parser.add_argument("--task", default="dark-castle")
    parser.add_argument("--task-metadata", default=None)
    parser.add_argument(
        "--interaction-profile",
        "--profile",
        dest="interaction_profile",
        default=None,
    )
    parser.add_argument(
        "--harness-mode",
        choices=sorted(_HARNESS_MODES),
        default=None,
    )
    parser.add_argument("--max-steps", type=int, default=None)
    args = parser.parse_args()

    metadata_path = _resolve_task_metadata_path(
        config_path=args.config,
        requested_metadata_path=args.task_metadata,
    )
    task_metadata_layer = (
        _task_metadata_config_layer(metadata_path)
        if metadata_path
        else {}
    )
    config_resolution = build_config_resolution(
        config_path=args.config,
        repo_default_path=_repo_harness_default_config_path(),
        task_metadata_config=task_metadata_layer,
        task_metadata_source=metadata_path,
        cli_overrides=_cli_config_overrides(args),
    )
    config = Config(
        raw=config_resolution.resolved,
        root_dir=config_resolution.root_dir,
    )
    config_normalizers: list[str] = []
    if metadata_path:
        _apply_task_metadata(config, metadata_path)
        config_normalizers.append("task_metadata_profile_resolution")
    harness_mode = _resolve_harness_mode(config)
    _apply_harness_mode(config, harness_mode)
    config_normalizers.append(f"harness_mode_policy:{harness_mode}")
    llm_config = config.get_section("llm")
    api_key = llm_config.get("api_key") or os.getenv("API_KEY")
    llm_base_url = llm_config.get("base_url") or os.getenv("BASE_URL") or DEFAULT_BASE_URL
    model = llm_config.get("model") or os.getenv("MODEL_NAME")
    if not api_key or not llm_base_url or not model:
        missing = [
            name
            for name, value in (
                ("API_KEY", api_key),
                ("MODEL_NAME", model),
            )
            if not value
        ]
        raise RuntimeError(
            "Missing model request field(s): "
            + ", ".join(missing)
            + ". Set them in the environment or provide llm.api_key "
            "and llm.model in config.toml."
        )
    llm_config = {
        **llm_config,
        "api_key": api_key,
        "base_url": llm_base_url,
        "model": model,
    }
    llm_client = LlmClient(llm_config)
    resolved_platform = resolve_model_platform(llm_client.runtime_config).name

    task_config = config.get_task(args.task)
    if not task_config:
        raise ValueError(f"Unknown task: {args.task}")
    run_section = config.get_section("run")
    task_id = str(
        task_config.get("id")
        or run_section.get("task_id")
        or args.task
    )
    task_slug = str(task_config.get("slug") or args.task.rsplit("/", maxsplit=1)[-1])
    environment_id = str(
        task_config.get("environment_id")
        or run_section.get("environment_id")
        or task_slug
    )
    backend_spec = resolve_backend_spec(config)
    service_base_url, frontend_url = _resolve_task_endpoints(
        backend_type=backend_spec.backend_type,
        backend_settings=backend_spec.settings,
        task_id=task_id,
        task_config=task_config,
    )

    prompt_dir = config.resolve_path(
        config.get_section("agent").get("prompt_dir", "prompts")
    )
    prompt_loader = PromptLoader(prompt_dir)
    prompts = prompt_loader.load_bundle()
    planner = ActionPlanner(llm_client, prompts)
    operator_config = config.get_section("operator")
    operator = Operator(
        llm_client,
        prompts.operator,
        max_retries=operator_config.get("max_retries", 2),
        retryable_error_kinds=operator_config.get(
            "retryable_error_kinds",
            ["tool_not_found", "element_not_found", "timeout", "not_visible"],
        ),
    )

    bug_config = config.get_section("bug_detection")
    detector = BugDetector(
        llm_client=llm_client,
        enable_llm_analysis=bug_config.get("enable_llm_analysis", True),
        auto_confirm_threshold=bug_config.get("auto_confirm_threshold", 0.8),
        rules=bug_config.get("rules", []),
    )

    report_config = config.get_section("report")
    reporter = Reporter(
        config.resolve_path(report_config.get("output_dir", "reports")),
        task_slug,
    )

    evaluator = None
    if task_config.get("ground_truth", False):
        ground_truth_path = resolve_ground_truth_path(config, task_id)
        evaluator = Evaluator(
            ground_truth_path,
            match_threshold=config.get_section("evaluation").get("match_threshold", 0.65),
            llm_client=llm_client
            if config.get_section("evaluation").get("use_llm", True)
            else None,
        )

    max_steps = (
        args.max_steps
        if args.max_steps is not None
        else config.get_section("agent").get("max_steps", 50)
    )
    reflection_threshold = config.get_section("agent").get("reflection_threshold", 3)
    max_consecutive_failures = config.get_section("agent").get(
        "max_consecutive_failures", 5
    )
    confidence_threshold = config.get_section("agent").get("confidence_threshold", 0.8)
    reflection_interval = config.get_section("agent").get("reflection_interval", 10)
    log_analysis_interval = config.get_section("agent").get("log_analysis_interval", 20)
    summary_interval = config.get_section("agent").get("summary_interval", 50)
    tool_policy = config.get_section("tool_policy")
    hook_policy = normalize_hook_policy(
        config.get_section("hooks"),
        harness_mode=harness_mode,
    )
    subagent_policy = normalize_subagent_policy(
        config.get_section("subagents"),
        harness_mode=harness_mode,
    )
    auto_log_analysis_policy = tool_policy.get("auto_log_analysis", {})
    if not isinstance(auto_log_analysis_policy, dict):
        auto_log_analysis_policy = {}
    auto_code_lookup_policy = tool_policy.get("auto_code_lookup", {})
    if not isinstance(auto_code_lookup_policy, dict):
        auto_code_lookup_policy = {}
    end_condition_policy = tool_policy.get("end_conditions", {})
    if not isinstance(end_condition_policy, dict):
        end_condition_policy = {}
    memory_config = config.get_section("memory")
    memory_context_token_limit = int(
        memory_config.get(
            "memory_context_token_limit",
            llm_client.runtime_config.memory_context_token_limit,
        )
    )
    session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    session_metadata = {
        "llm": {
            "model": model,
            "platform": resolved_platform,
            "temperature": llm_config.get("temperature"),
            "max_tokens": llm_config.get("max_tokens"),
            "timeout": llm_config.get("timeout"),
            "input_token_limit": llm_client.runtime_config.input_token_limit,
        },
        "agent": {
            "max_steps": max_steps,
            "max_consecutive_failures": max_consecutive_failures,
            "reflection_threshold": reflection_threshold,
            "reflection_interval": reflection_interval,
            "summary_interval": summary_interval,
            "confidence_threshold": confidence_threshold,
            "auto_summarize": config.get_section("agent").get("auto_summarize", True),
            "summary_threshold": config.get_section("agent").get("summary_threshold", 15),
        },
        "memory": {
            "max_short_term": memory_config.get("max_short_term", 100),
            "memory_context_token_limit": memory_context_token_limit,
        },
    }
    long_term_template = memory_config.get(
        "long_term_file", "memory/{task_slug}/long_term.json"
    )
    long_term_path = long_term_template.format(
        task_id=task_id,
        task_slug=task_slug,
        environment_id=environment_id,
    )
    memory = MemoryManager(
        max_short_term=memory_config.get("max_short_term", 100),
        long_term_path=config.resolve_path(long_term_path),
        llm_client=llm_client,
        auto_summarize=config.get_section("agent").get("auto_summarize", True),
        summary_threshold=config.get_section("agent").get("summary_threshold", 15),
        summary_prompt=prompts.summary,
        task_id=task_id,
        session_id=session_id,
        memory_dir=config.resolve_path("memory"),
        session_metadata=session_metadata,
        cross_session_enabled=memory_config.get("cross_session_enabled", False),
        cross_session_top_k=memory_config.get("cross_session_top_k", 3),
        cross_session_similarity=memory_config.get("cross_session_similarity", 0.2),
        load_persistent_long_term=memory_config.get("load_persistent_long_term", False),
        memory_context_token_limit=memory_context_token_limit,
    )

    backend = build_execution_backend(config, task_id, task_config)
    tool_registry = ToolRegistry()

    def _handle_environment_action(payload, runtime_context):  # noqa: ANN001
        action_text = str(payload.get("action", "")).strip()
        planner_action = runtime_context.get("planner_action")
        source_action = (
            planner_action
            if isinstance(planner_action, Action)
            else Action(command=action_text, tool="environment_action")
        )
        result = operator.execute(
            action=Action(
                command=action_text,
                tool="environment_action",
                rationale=source_action.rationale,
                expected_outcome=source_action.expected_outcome,
                bug_exist=source_action.bug_exist,
                confidence=source_action.confidence,
                explanation=source_action.explanation,
            ),
            current_observation=runtime_context["current_observation"],
            capability=runtime_context["capability"],
            session=runtime_context["session"],
            backend=backend,
        )
        return ToolInvocationResult(
            observation=result.observation,
            refreshed_capability=result.refreshed_capability,
        )

    register_environment_action_tool(tool_registry, _handle_environment_action)
    _register_interaction_mode_tools(
        registry=tool_registry,
        enabled_modes=backend_spec.enabled_modes,
        primary_mode=backend_spec.primary_mode,
        operator=operator,
        backend=backend,
        task_id=task_id,
    )

    interaction_config = config.get_section("interaction")
    interaction_adapters = interaction_config.get("adapters", {})
    if not isinstance(interaction_adapters, dict):
        interaction_adapters = {}

    code_tool_config = interaction_adapters.get("code", {})
    if not isinstance(code_tool_config, dict):
        code_tool_config = {}
    
    code_tools_registered = False
    if code_tool_config.get("enabled", False):
        code_root_dir = str(code_tool_config.get("root_dir") or "/sandbox/software")
        if (
            harness_mode == "full"
            or hasattr(backend, "shell")
            or backend_spec.backend_type in {"computer_use", "daytona"}
        ):
            register_code_tools(
                tool_registry,
                codebase_adapter=UniversalCodebaseAdapter(
                    shell_client=backend if hasattr(backend, "shell") else None,
                    root_dir=code_root_dir,
                ),
            )
            code_tools_registered = True
        else:
            code_tool_base_url = str(
                code_tool_config.get("base_url") or service_base_url
            ).strip()
            if not code_tool_base_url:
                raise ValueError(
                    "interaction.adapters.code.base_url is required when enabled=true"
                )
            register_code_tools(
                tool_registry,
                create_http_code_tool_adapter(
                    EnvironmentClientConfig(
                        base_url=code_tool_base_url,
                        timeout=int(code_tool_config.get("timeout", 60)),
                    )
                ),
            )
            code_tools_registered = True

    runtime_log_config = interaction_adapters.get("logs", {})
    if not isinstance(runtime_log_config, dict):
        runtime_log_config = {}
    log_sources = build_log_tool_sources(runtime_log_config)
    log_tools_registered = False
    if log_sources:
        register_log_tools(
            tool_registry,
            log_sources,
            LogAnalyzer(),
        )
        log_tools_registered = True
    if harness_mode == "full":
        if code_tools_registered:
            tool_registry.activate_skill("code")
        if log_tools_registered:
            tool_registry.activate_skill("logs")

    reflection_analyzer = ReflectionAnalyzer(llm_client, prompts.reflection)
    subagent_manager = (
        SubagentManager(llm_client=llm_client, policy=subagent_policy)
        if subagent_policy.get("enabled", False)
        else None
    )
    orchestrator = Orchestrator(
        task_id=task_id,
        execution_backend=backend,
        operator=operator,
        tool_registry=tool_registry,
        planner=planner,
        memory=memory,
        detector=detector,
        reporter=reporter,
        evaluator=evaluator,
        max_steps=max_steps,
        reflection_analyzer=reflection_analyzer,
        reflection_threshold=reflection_threshold,
        max_consecutive_failures=max_consecutive_failures,
        confidence_threshold=confidence_threshold,
        reflection_interval=reflection_interval,
        log_analysis_interval=log_analysis_interval,
        summary_interval=summary_interval,
        auto_log_analysis_policy=auto_log_analysis_policy,
        auto_code_lookup_policy=auto_code_lookup_policy,
        end_condition_policy=end_condition_policy,
        hook_manager=HookManager(hook_policy),
        subagent_manager=subagent_manager,
    )

    task_profile = task_config.get(
        "profile",
        "You are testing an interactive software environment. Focus on exploration, "
        "state verification, and reproducible QA evidence.",
    )
    report = orchestrator.run(task_profile)
    report.metadata["llm"] = {
        "model": model,
        "platform": resolved_platform,
        "temperature": llm_config.get("temperature"),
        "max_tokens": llm_config.get("max_tokens"),
        "timeout": llm_config.get("timeout"),
        "input_token_limit": llm_client.runtime_config.input_token_limit,
    }
    report.metadata["task"] = {
        "id": task_id,
        "slug": task_slug,
        "environment_id": environment_id,
        "name": task_config.get("name") or task_slug,
        "port": task_config.get("port"),
        "base_url": service_base_url,
        "frontend_url": frontend_url,
        "backend_type": backend.backend_type,
        "primary_backend_type": backend_spec.backend_type,
        "interaction_profile": str(run_section.get("interaction_profile", "")),
        "enabled_interaction_modes": list(backend_spec.enabled_modes),
        "harness_mode": harness_mode,
        "have_ground_truth": bool(task_config.get("ground_truth", False)),
        "profile": task_profile,
    }
    report.metadata["agent"] = {
        "harness_mode": harness_mode,
        "hook_policy": hook_policy,
        "subagent_policy": subagent_policy,
        "max_steps": max_steps,
        "max_consecutive_failures": max_consecutive_failures,
        "reflection_threshold": reflection_threshold,
        "reflection_interval": reflection_interval,
        "summary_interval": summary_interval,
        "confidence_threshold": confidence_threshold,
        "auto_summarize": config.get_section("agent").get("auto_summarize", True),
        "summary_threshold": config.get_section("agent").get("summary_threshold", 15),
        "camel_memory_history": str(memory.chat_history_path),
        "operator_max_retries": operator_config.get("max_retries", 2),
    }
    report.metadata["memory"] = {
        "max_short_term": memory_config.get("max_short_term", 100),
        "memory_context_token_limit": memory_context_token_limit,
    }
    report.metadata["run_spec"] = build_run_spec(
        task_id=task_id,
        task_slug=task_slug,
        environment_id=environment_id,
        harness_mode=harness_mode,
        interaction_mode=str(run_section.get("interaction_mode", "")),
        interaction_profile=str(run_section.get("interaction_profile", "")),
        enabled_interaction_modes=list(backend_spec.enabled_modes),
        backend_type=backend.backend_type,
        model=model,
        model_platform=resolved_platform,
        llm_config=llm_config,
        agent_config={
            "max_steps": max_steps,
            "max_consecutive_failures": max_consecutive_failures,
            "reflection_threshold": reflection_threshold,
            "reflection_interval": reflection_interval,
            "log_analysis_interval": log_analysis_interval,
            "summary_interval": summary_interval,
            "confidence_threshold": confidence_threshold,
            "auto_summarize": config.get_section("agent").get("auto_summarize", True),
            "summary_threshold": config.get_section("agent").get("summary_threshold", 15),
        },
        operator_config=operator_config,
        memory_config=memory_config,
        tool_policy=tool_policy,
        hook_policy=hook_policy,
        subagent_policy=subagent_policy,
        tool_registry_policy=tool_registry.describe_policy(),
        config_resolution=config_resolution_for_run_spec(
            config_resolution,
            final_config=config.raw,
            normalizers=config_normalizers,
        ),
    )
    paths = reporter.write_report(report)
    print(f"Report saved: {paths['json']}")
    print(f"Markdown saved: {paths['markdown']}")


if __name__ == "__main__":
    main()
