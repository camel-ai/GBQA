"""Pydantic models for optional software-project taxonomy annotations."""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field, field_validator


class TaxonomyPrediction(BaseModel):
    """One LLM-predicted taxonomy annotation."""

    finding_index: int = Field(ge=0)
    primary_category: str = Field(default="other")
    secondary_labels: List[str] = Field(default_factory=list)
    context_summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("primary_category", mode="before")
    @classmethod
    def normalize_primary_category(cls, value: Any) -> str:
        """Normalize category values into a compact lowercase label."""
        text = str(value or "other").strip().lower()
        if text not in {"frontend", "backend", "database", "safety", "other"}:
            return "other"
        return text


class TaxonomyPredictionBatch(BaseModel):
    """Batch wrapper for taxonomy annotations."""

    findings: List[TaxonomyPrediction] = Field(default_factory=list)
