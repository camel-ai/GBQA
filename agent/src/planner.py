"""CAMEL-based action planning logic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from camel.messages import BaseMessage
from PIL import Image

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
            "current_artifacts": context.get("current_artifacts", ""),
            "turn": str(context.get("turn", "")),
            "available_tools_prompt_section": context.get(
                "available_tools_prompt_section",
                context.get("code_tools_prompt_section", ""),
            ),
        }
        planner_prompt = render_prompt(self._prompts.planner, variables)
        prompt_input = self._build_prompt_input(
            planner_prompt=planner_prompt,
            image_paths=context.get("observation_images", []),
        )
        response = self._agent.run(
            prompt_input,
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
    def _build_prompt_input(
        *,
        planner_prompt: str,
        image_paths: Any,
    ) -> str | BaseMessage:
        images = []
        for item in image_paths or []:
            path = Path(str(item)).expanduser()
            if not path.exists():
                continue
            try:
                with Image.open(path) as image:
                    images.append(image.copy())
            except OSError:
                continue
        if not images:
            return planner_prompt
        return BaseMessage.make_user_message(
            role_name="Planner",
            content=planner_prompt,
            image_list=images,
        )

    @staticmethod
    def _to_action(decision: PlannerDecision | None) -> Action:
        if decision is None or not decision.action.strip():
            return Action(
                command="look",
                tool="game_action",
                rationale="Fallback command due to invalid model output.",
                expected_outcome="Refresh the room description.",
            )
        return Action(
            command=decision.action.strip(),
            tool=decision.tool.strip() or "game_action",
            rationale=decision.rationale.strip(),
            expected_outcome=decision.expected_outcome.strip(),
            bug_exist=decision.bug_exist,
            confidence=float(decision.bug_confidence),
            explanation=decision.bug_explanation.strip(),
        )
