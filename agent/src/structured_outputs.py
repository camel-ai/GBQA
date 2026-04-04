"""Pydantic models for CAMEL structured outputs."""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field, field_validator


class PlannerDecision(BaseModel):
    """Planner output schema."""

    tool: str = Field(default="game_command")
    command: str = Field(min_length=1)
    rationale: str = ""
    expected_outcome: str = ""
    bug_exist: bool = False
    bug_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    bug_explanation: str = ""

    @field_validator("bug_confidence", mode="before")
    @classmethod
    def normalize_bug_confidence(cls, value: Any) -> float:
        if value in {"", None}:
            return 0.0
        return float(value)


class ReflectionDecision(BaseModel):
    """Reflection output schema."""

    bug_exist: bool = False
    bug_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    bug_evidence: str = ""
    next_check: str = ""

    @field_validator("bug_confidence", mode="before")
    @classmethod
    def normalize_bug_confidence(cls, value: Any) -> float:
        if value in {"", None}:
            return 0.0
        return float(value)


class OperatorCallDecision(BaseModel):
    """One normalized call produced by the operator."""

    kind: str = Field(min_length=1)
    ref: str = ""
    target: str = ""
    text: str = ""
    url: str = ""
    duration_ms: int = Field(default=0, ge=0)


class OperatorDecision(BaseModel):
    """Operator output schema."""

    rationale: str = ""
    calls: List[OperatorCallDecision] = Field(default_factory=list)


class BugReviewItem(BaseModel):
    """One LLM-reviewed bug finding."""

    finding_index: int = Field(ge=0)
    title: str
    description: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class BugReviewBatch(BaseModel):
    """Batch wrapper for bug review output."""

    findings: List[BugReviewItem] = Field(default_factory=list)


class GroundTruthMatch(BaseModel):
    """Evaluator match result schema."""

    match_id: str = ""
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
