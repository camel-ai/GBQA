"""CAMEL-based reflection analysis for QA Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict
import json

from .llm_client import LlmClient
from .prompts import render_prompt
from .structured_outputs import ReflectionDecision


@dataclass
class ReflectionResult:
    """Structured reflection output."""

    bug_exist: bool
    bug_confidence: float
    bug_evidence: str
    next_check: str
    prompt: str
    output: str
    raw: Dict[str, Any]
    error: str = ""


class ReflectionAnalyzer:
    """Generates a reflection based on the latest action and observation."""

    def __init__(self, llm_client: LlmClient, prompt: str) -> None:
        self._prompt = prompt
        self._agent = llm_client.create_task_agent(
            system_prompt="You are a QA agent reflecting on game behavior.",
            agent_id="reflection",
        )

    def reflect(self, context: Dict[str, Any]) -> ReflectionResult:
        variables = {
            "memory_summary": context.get("memory_summary", ""),
            "recent_trace": context.get("recent_trace", ""),
            "current_observation": context.get("current_observation", ""),
        }
        prompt = render_prompt(self._prompt, variables)
        response = self._agent.run(
            prompt,
            response_format=ReflectionDecision,
        )
        decision = response.parsed
        if decision is None:
            return ReflectionResult(
                bug_exist=False,
                bug_confidence=0.0,
                bug_evidence="",
                next_check="",
                prompt=prompt,
                output=response.content,
                raw={"error": response.error or "invalid_structured_output"},
                error=response.error or "invalid_structured_output",
            )
        return ReflectionResult(
            bug_exist=decision.bug_exist,
            bug_confidence=float(decision.bug_confidence),
            bug_evidence=decision.bug_evidence.strip(),
            next_check=decision.next_check.strip(),
            prompt=prompt,
            output=response.content,
            raw=decision.model_dump(),
            error=response.error,
        )

    @staticmethod
    def format_note(result: ReflectionResult) -> str:
        summary = {
            "bug_exist": result.bug_exist,
            "bug_confidence": result.bug_confidence,
            "bug_evidence": result.bug_evidence,
            "next_check": result.next_check,
        }
        return json.dumps(summary, ensure_ascii=False)
