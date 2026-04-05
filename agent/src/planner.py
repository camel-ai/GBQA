"""CAMEL-based action planning logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .llm_client import LlmClient
from .prompts import PromptBundle, render_prompt
from .structured_outputs import PlannerDecision
from .types import Action


@dataclass
class PlanResult:
    """Planner output with prompt and model response."""

    action: Action
    prompt: str
    output: str
    error: str = ""


class ActionPlanner:
    """Uses a CAMEL role agent to propose the next action."""

    def __init__(self, llm_client: LlmClient, prompts: PromptBundle) -> None:
        self._prompts = prompts
        self._agent = llm_client.create_task_agent(
            system_prompt=prompts.system,
            agent_id="planner",
        )

    def plan(self, context: Dict[str, Any]) -> PlanResult:
        variables = {
            "game_profile": context.get("game_profile", ""),
            "memory_summary": context.get("memory_summary", ""),
            "recent_trace": context.get("recent_trace", ""),
            "current_observation": context.get("current_observation", ""),
            "turn": str(context.get("turn", "")),
            "code_tools_prompt_section": context.get("code_tools_prompt_section", ""),
        }
        planner_prompt = render_prompt(self._prompts.planner, variables)
        response = self._agent.run(
            planner_prompt,
            response_format=PlannerDecision,
        )
        action = self._to_action(response.parsed)
        return PlanResult(
            action=action,
            prompt=planner_prompt,
            output=response.content,
            error=response.error,
        )

    @staticmethod
    def _to_action(decision: PlannerDecision | None) -> Action:
        if decision is None or not decision.command.strip():
            return Action(
                command="look",
                rationale="Fallback command due to invalid model output.",
                expected_outcome="Refresh the room description.",
            )
        return Action(
            command=decision.command.strip(),
            tool=decision.tool.strip() or "game_command",
            rationale=decision.rationale.strip(),
            expected_outcome=decision.expected_outcome.strip(),
            bug_exist=decision.bug_exist,
            confidence=float(decision.bug_confidence),
            explanation=decision.bug_explanation.strip(),
        )
