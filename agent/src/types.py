"""Shared data models for the QA Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Action:
    """Represents a single action to send to the game."""

    command: str
    tool: str = "game_command"
    rationale: str = ""
    expected_outcome: str = ""
    bug_exist: bool = False
    confidence: float = 0.0
    explanation: str = ""


@dataclass
class SessionHandle:
    """Represents one backend session bound to the current run."""

    session_id: str
    backend_type: str
    raw: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    initial_observation: Optional["Observation"] = None


@dataclass
class CapabilityDescriptor:
    """Capability metadata exposed by one execution backend."""

    planner_summary: str
    operator_context: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionCall:
    """One normalized low-level call produced by the operator."""

    kind: str
    ref: str = ""
    target: str = ""
    text: str = ""
    url: str = ""
    duration_ms: int = 0
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionRequest:
    """One backend execution request derived from a planner action."""

    planner_action: str
    calls: List[ExecutionCall] = field(default_factory=list)
    request_type: str = "action"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionAttempt:
    """Execution trace for a single operator attempt."""

    attempt: int
    translated_calls: List[ExecutionCall] = field(default_factory=list)
    per_call_results: List[Dict[str, Any]] = field(default_factory=list)
    retry_reason: str = ""
    success: bool = False
    final_status: str = ""
    suspected_origin: str = "ambiguous"
    error: str = ""


@dataclass
class Observation:
    """Represents the game response."""

    success: bool
    message: str
    state: Dict[str, Any]
    raw: Dict[str, Any] = field(default_factory=dict)
    game_over: bool = False
    turn: Optional[int] = None
    summary: str = ""
    env_state: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)


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
    capability_summary: str = ""
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


@dataclass
class BackendExecutionResult:
    """Backend result after executing one normalized request."""

    observation: Observation
    attempts: List[ExecutionAttempt] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    refreshed_capability: Optional[CapabilityDescriptor] = None
