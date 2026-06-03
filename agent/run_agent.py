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
from src.config import load_config
from src.evaluator import Evaluator
from src.execution_backends import build_execution_backend, resolve_backend_spec
from src.environment_clients import (
    EnvironmentClientConfig,
    create_http_code_tool_adapter,
)
from src.ground_truth import resolve_ground_truth_path
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
from src.tool_registry import (
    ToolInvocationResult,
    ToolRegistry,
    register_code_tools,
    register_environment_action_tool,
    register_log_tools,
)
from src.codebase_types import UniversalCodebaseAdapter
from src.types import Action


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
    elif backend_type in {"playwright_mcp", "computer_use"} and port is None and not configured_frontend_url:
        raise ValueError(
            f"Task config for '{task_id}' must provide at least one of 'port' or 'frontend_url'"
        )

    if not service_base_url and port is not None:
        service_base_url = f"http://localhost:{port}/api/agent"
    frontend_url = configured_frontend_url
    if not frontend_url and port is not None:
        frontend_url = f"http://localhost:{port}"
    return service_base_url, frontend_url


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
    interaction_mode = str(
        run_section.get("interaction_mode") or metadata.default_interaction_mode
    ).strip()
    if interaction_mode not in metadata.supported_interaction_modes:
        raise ValueError(
            "Unsupported interaction_mode for task metadata: " + interaction_mode
        )

    backend_by_mode = {
        "api": "api",
        "browser": "playwright_mcp",
        "computer_use": "computer_use",
    }
    backend_type = backend_by_mode.get(interaction_mode)
    if backend_type is None:
        raise ValueError(
            "Unsupported interaction_mode for task metadata: " + interaction_mode
        )
    interaction = config.raw.setdefault("interaction", {})
    interaction["primary"] = backend_type
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
    tasks[metadata.task_slug] = {
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
    }


def main() -> None:
    dotenv.load_dotenv(dotenv_path=REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Run QA Agent")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"),
    )
    parser.add_argument("--task", default="dark-castle")
    parser.add_argument("--task-metadata", default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    if args.task_metadata:
        metadata_path = (
            args.task_metadata
            if os.path.isabs(args.task_metadata)
            else config.resolve_path(args.task_metadata)
        )
        _apply_task_metadata(config, metadata_path)
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
            "and llm.model in config.yaml."
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

    interaction_config = config.get_section("interaction")
    interaction_adapters = interaction_config.get("adapters", {})
    if not isinstance(interaction_adapters, dict):
        interaction_adapters = {}

    code_tool_config = interaction_adapters.get("code", {})
    if not isinstance(code_tool_config, dict):
        code_tool_config = {}
    
    # Skills-style codebase tool integration (with Universal Sandbox support)
    if hasattr(backend, "shell") or backend_spec.backend_type in {"computer_use", "daytona"}:
        register_code_tools(tool_registry, codebase_adapter=UniversalCodebaseAdapter(shell_client=backend))
    elif code_tool_config.get("enabled", False):
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

    runtime_log_config = interaction_adapters.get("logs", {})
    if not isinstance(runtime_log_config, dict):
        runtime_log_config = {}
    log_sources = build_log_tool_sources(runtime_log_config)
    if log_sources:
        register_log_tools(
            tool_registry,
            log_sources,
            LogAnalyzer(),
        )

    reflection_analyzer = ReflectionAnalyzer(llm_client, prompts.reflection)
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
    )

    task_profile = task_config.get(
        "profile",
        "You are testing an interactive software environment. Focus on exploration, state verification, and reproducible QA evidence.",
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
        "backend_type": backend_spec.backend_type,
        "have_ground_truth": bool(task_config.get("ground_truth", False)),
        "profile": task_profile,
    }
    report.metadata["agent"] = {
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
    paths = reporter.write_report(report)
    print(f"Report saved: {paths['json']}")
    print(f"Markdown saved: {paths['markdown']}")


if __name__ == "__main__":
    main()
