"""Shared data models for the QA Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Action:
    """Represents a single action to send to the game."""

    command: str
    rationale: str = ""
    expected_outcome: str = ""
    bug_exist: bool = False
    confidence: float = 0.0
    explanation: str = ""


@dataclass
class Observation:
    """Represents the game response."""

    success: bool
    message: str
    state: Dict[str, Any]
    raw: Dict[str, Any] = field(default_factory=dict)
    game_over: bool = False
    turn: Optional[int] = None


@dataclass
class BugFinding:
    """Represents a suspected or confirmed bug."""

    title: str
    description: str
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


@dataclass
class StepRecord:
    """Represents a single loop step."""

    step: int
    action: Action
    observation: Observation
    notes: str = ""
    planner_prompt: str = ""
    planner_output: str = ""
    reflection_prompt: str = ""
    reflection_output: str = ""


@dataclass
class SummaryRecord:
    """Represents a summary prompt/output."""

    step: int
    prompt: str
    output: str



@dataclass
class RunReport:
    """Aggregated run data."""

    game_id: str
    steps: List[StepRecord] = field(default_factory=list)
    bugs: List[BugFinding] = field(default_factory=list)
    summaries: List[SummaryRecord] = field(default_factory=list)
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
