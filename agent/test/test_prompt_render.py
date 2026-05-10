"""Quick prompt render test for QA Agent."""

from __future__ import annotations

import sys
from typing import Dict

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.prompts import PromptLoader, render_prompt


def _build_sample_context() -> Dict[str, str]:
    return {
        "task_profile": (
            "Text adventure in a mysterious castle. "
            "You can start, explore, and close a session through the exposed controls."
        ),
        "capability_summary": "You can send one environment command per step or ask for describe_capabilities.",
        "memory_summary": "- Found a locked door.\n- Collected a key fragment.",
        "recent_trace": (
            "Step 1: look -> You are in a hall.\n"
            "Step 2: take torch -> You picked up a torch."
        ),
        "current_observation": "A dark corridor lies ahead.",
        "current_artifacts": "",
        "execution_diagnostics": "{}",
        "turn": "2",
        "available_tools_prompt_section": """## Available Tools:
- environment_action: Execute one semantic environment action through the operator and active execution backend. Format: `semantic action string`.
- code_list_files: List available source code files for the current environment. Format: `any non-empty text (ignored)`.
- code_read_file: Read a source file, optionally with a line range. Format: `path or path:start-end`.
- code_search: Search source code using a regex pattern. Format: `pattern`.
- code_write_file: Modify a source file using JSON payload or path:old_text->new_text patch shorthand. Format: `JSON string or path:old_text->new_text`.
- code_restore_file: Restore a file previously modified by code_write_file. Format: `path`.
- code_read_debug_logs: Read or clear runtime debug logs for the current active environment session. Format: `read or clear`.
- log_analyze: Analyze the current environment session log for anomalies and optionally show filtered commands. Format: `analyze, failures, or JSON object with start_turn/end_turn/failures_only/limit/include_debug_output`.""",
    }


def _load_context() -> Dict[str, str]:
    return _build_sample_context()


def main() -> None:
    prompt_dir = str(ROOT_DIR / "prompts")
    loader = PromptLoader(prompt_dir)
    prompts = loader.load_bundle()

    context = _load_context()

    system_prompt = render_prompt(prompts.system, context)
    planner_prompt = render_prompt(prompts.planner, context)
    reflection_vars = {
        "memory_summary": context["memory_summary"],
        "recent_trace": context["recent_trace"],
        "current_observation": context["current_observation"],
        "execution_diagnostics": context["execution_diagnostics"],
    }
    reflection_prompt = render_prompt(prompts.reflection, reflection_vars)
    summary_prompt = render_prompt(
        prompts.summary,
        {
            "trace": "Step 1: look -> You are in a hall.",
            "memory_summary": context["memory_summary"],
        },
    )

    print("Rendered system prompt:\n")
    print(system_prompt)
    print("\nRendered planner prompt:\n")
    print(planner_prompt)
    print("\nRendered reflection prompt:\n")
    print(reflection_prompt)
    print("\nRendered summary prompt:\n")
    print(summary_prompt)
    assert "{task_profile}" not in planner_prompt
    assert "## Task Profile:" in planner_prompt


if __name__ == "__main__":
    main()
