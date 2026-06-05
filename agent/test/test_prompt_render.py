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
        "step": "2",
        "available_tools_prompt_section": """## Available Tools:
- environment_action: Execute one semantic environment action through the operator and active execution backend. Format: `semantic action string`.
- use_skill: Load an available skill's SKILL.md instructions and reveal its tools. Format: `skill name`.

## Available Skills:
Use `use_skill` with the skill name to load that skill's full SKILL.md instructions when relevant.
- code: Inspect, search, and optionally modify target software source code for white-box debugging. (SKILL.md: agent/skills/code/SKILL.md)
- logs: Inspect and analyze agent trajectory plus target runtime log sources. (SKILL.md: agent/skills/logs/SKILL.md)""",
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
