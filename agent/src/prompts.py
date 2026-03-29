"""Prompt loading and rendering utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
import os


@dataclass
class PromptBundle:
    """Container for prompts used in the loop."""

    system: str
    planner: str
    reflection: str
    summary: str


class PromptLoader:
    """Loads prompt templates from disk."""

    def __init__(self, prompt_dir: str) -> None:
        self._prompt_dir = prompt_dir

    def _load(self, filename: str) -> str:
        path = os.path.join(self._prompt_dir, filename)
        with open(path, "r", encoding="utf-8") as file_handle:
            return file_handle.read().strip()

    def load_bundle(self) -> PromptBundle:
        return PromptBundle(
            system=self._load("system.md"),
            planner=self._load("planner.md"),
            reflection=self._load("reflection.md"),
            summary=self._load("summary.md"),
        )


def render_prompt(template: str, variables: Dict[str, str]) -> str:
    """Render prompt template with variables."""
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered
