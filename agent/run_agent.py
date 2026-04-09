"""Run the Agent against a target game."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

import dotenv

from src.bug_detector import BugDetector
from src.camel_runtime import resolve_model_platform
from src.config import load_config
from src.evaluator import Evaluator
from src.game_clients import GameClientConfig, create_http_game_client
from src.ground_truth import resolve_ground_truth_path
from src.llm_client import LlmClient
from src.memory import MemoryManager
from src.orchestrator import Orchestrator
from src.planner import ActionPlanner
from src.prompts import PromptLoader
from src.reflection import ReflectionAnalyzer
from src.reporter import Reporter
from src.tool_registry import ToolRegistry, register_standard_game_tools, register_code_reading_tools, register_log_tools


def main() -> None:
    dotenv.load_dotenv()
    parser = argparse.ArgumentParser(description="Run QA Agent")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"),
    )
    parser.add_argument("--game", default="dark-castle")
    parser.add_argument("--max-steps", type=int, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    llm_config = config.get_section("llm")
    api_key = llm_config.get("api_key") or os.getenv("OPENAI_API_KEY")
    llm_base_url = llm_config.get("base_url") or os.getenv("OPENAI_BASE_URL")
    model = llm_config.get("model") or os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        raise RuntimeError(
            "Missing OPENAI_API_KEY or OPENAI_MODEL. Set them in the environment or "
            "provide llm.api_key or llm.model in config.yaml."
        )
    llm_config = {
        **llm_config,
        "api_key": api_key,
        "base_url": llm_base_url,
        "model": model,
    }
    llm_client = LlmClient(llm_config)
    resolved_platform = resolve_model_platform(llm_client.runtime_config).name

    game_config = config.get_game(args.game)
    if not game_config:
        raise ValueError(f"Unknown game: {args.game}")

    prompt_dir = config.resolve_path(
        config.get_section("agent").get("prompt_dir", "prompts")
    )
    prompt_loader = PromptLoader(prompt_dir)
    prompts = prompt_loader.load_bundle()
    planner = ActionPlanner(llm_client, prompts)

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
        args.game,
    )

    evaluator = None
    if game_config.get("ground_truth", False):
        ground_truth_path = resolve_ground_truth_path(config, args.game)
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
    summary_interval = config.get_section("agent").get("summary_interval", 50)
    memory_config = config.get_section("memory")
    session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    session_metadata = {
        "llm": {
            "model": model,
            "platform": resolved_platform,
            "temperature": llm_config.get("temperature"),
            "max_tokens": llm_config.get("max_tokens"),
            "timeout": llm_config.get("timeout"),
            "context_token_limit": llm_client.runtime_config.context_token_limit,
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
    }
    long_term_template = memory_config.get(
        "long_term_file", "memory/{game_id}/long_term.json"
    )
    long_term_path = long_term_template.format(game_id=args.game)
    memory = MemoryManager(
        max_short_term=memory_config.get("max_short_term", 30),
        long_term_path=config.resolve_path(long_term_path),
        llm_client=llm_client,
        auto_summarize=config.get_section("agent").get("auto_summarize", True),
        summary_threshold=config.get_section("agent").get("summary_threshold", 15),
        summary_prompt=prompts.summary,
        game_id=args.game,
        session_id=session_id,
        memory_dir=config.resolve_path("memory"),
        session_metadata=session_metadata,
        cross_session_enabled=memory_config.get("cross_session_enabled", False),
        cross_session_top_k=memory_config.get("cross_session_top_k", 3),
        cross_session_similarity=memory_config.get("cross_session_similarity", 0.2),
        load_persistent_long_term=memory_config.get("load_persistent_long_term", False),
    )

    game_base_url = game_config.get("base_url") or f"http://localhost:{game_config['port']}/api/agent"
    game_client = create_http_game_client(
        GameClientConfig(
            base_url=game_base_url,
            timeout=config.get_section("llm").get("timeout", 60),
        )
    )
    registry = ToolRegistry()
    register_standard_game_tools(registry, game_client)
    if config.get_section("agent").get("enable_code_reading", False):
        register_code_reading_tools(registry, game_client)
    if config.get_section("agent").get("enable_log_analysis", False):
        register_log_tools(registry, game_client)

    log_analysis_interval = config.get_section("agent").get("log_analysis_interval", 20)
    reflection_analyzer = ReflectionAnalyzer(llm_client, prompts.reflection)
    orchestrator = Orchestrator(
        game_id=args.game,
        tool_registry=registry,
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
        summary_interval=summary_interval,
        log_analysis_interval=log_analysis_interval,
    )

    game_profile = game_config.get(
        "profile",
        "You are testing a text-based adventure game. Focus on exploration, items, and puzzle logic.",
    )
    try:
        report = orchestrator.run(game_profile)
        report.metadata["llm"] = {
            "model": model,
            "platform": resolved_platform,
            "temperature": llm_config.get("temperature"),
            "max_tokens": llm_config.get("max_tokens"),
            "timeout": llm_config.get("timeout"),
            "message_window_size": llm_config.get("message_window_size", 6),
            "reset_between_turns": llm_config.get("reset_between_turns", True),
            "context_token_limit": llm_client.runtime_config.context_token_limit,
        }
        report.metadata["game"] = {
            "name": args.game,
            "port": game_config.get("port"),
            "base_url": game_base_url,
            "have_ground_truth": bool(game_config.get("ground_truth", False)),
            "profile": game_profile,
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
        }
        paths = reporter.write_report(report)
        print(f"Report saved: {paths['json']}")
        print(f"Markdown saved: {paths['markdown']}")
    finally:
        game_client.close()


if __name__ == "__main__":
    main()
