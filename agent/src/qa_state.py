"""QA-oriented working state for exploration, hypotheses, and coverage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
import json
from typing import Any, Dict, Iterable, List, Optional

from .types import Action, BugFinding, Observation


def build_bug_evidence(
    evidence: Dict[str, Any] | None,
    *,
    action: Action,
    observation: Observation,
) -> Dict[str, Any]:
    """Normalize planner/harness evidence into the GBQA bug-report shape."""

    normalized = dict(evidence or {})
    expected = str(
        normalized.get("expected_behavior")
        or normalized.get("expected_outcome")
        or action.expected_outcome
        or ""
    ).strip()
    if expected:
        normalized["expected_behavior"] = expected
    normalized.pop("expected_outcome", None)

    observed = str(normalized.get("observed_fault") or "").strip()
    if not observed and action.bug_exist:
        observed = str(action.explanation or "").strip()
    if not observed:
        observed = str(observation.summary or observation.message or "").strip()
    if observed:
        normalized["observed_fault"] = observed

    reproduction = (
        normalized.get("reproduction")
        or normalized.get("minimal_reproduction")
        or normalized.get("reproduction_steps")
    )
    if reproduction:
        normalized["reproduction"] = _string_list(reproduction)

    pinpoint = normalized.get("pinpoint") or normalized.get("root_cause")
    if pinpoint:
        normalized["pinpoint"] = pinpoint

    return normalized


@dataclass
class Hypothesis:
    """One suspected software defect tracked across exploration steps."""

    hypothesis_id: str
    title: str
    description: str
    confidence: float
    status: str
    first_step: int
    last_step: int
    evidence: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    reproduction_steps: List[Dict[str, Any]] = field(default_factory=list)


class HypothesisManager:
    """Maintain deduplicated QA bug hypotheses during a run."""

    def __init__(self, *, confidence_threshold: float = 0.8) -> None:
        self._confidence_threshold = float(confidence_threshold)
        self._items: List[Hypothesis] = []

    @property
    def items(self) -> List[Hypothesis]:
        return list(self._items)

    def add_from_finding(
        self,
        *,
        finding: BugFinding,
        step: int,
        action: Action,
        observation: Observation,
        source: str,
    ) -> Hypothesis:
        evidence = build_bug_evidence(
            finding.evidence,
            action=action,
            observation=observation,
        )
        evidence.setdefault("source", source)
        evidence.setdefault("action", action.command)
        evidence.setdefault("observation", observation.summary or observation.message)
        status = (
            "reproduced"
            if finding.confidence >= self._confidence_threshold
            else "candidate"
        )
        return self._upsert(
            title=finding.title,
            description=finding.description,
            confidence=finding.confidence,
            status=status,
            step=step,
            evidence=evidence,
            tags=[*finding.tags, source],
            reproduction_step={
                "step": step,
                "action": action.command,
                "observation": observation.summary or observation.message,
                "source": source,
            },
        )

    def add_from_planner_signal(
        self,
        *,
        action: Action,
        step: int,
        observation: Observation,
    ) -> Optional[Hypothesis]:
        if not action.bug_exist or action.confidence <= 0:
            return None
        description = action.explanation.strip()
        if not description:
            return None
        status = (
            "reproduced"
            if action.confidence >= self._confidence_threshold
            else "candidate"
        )
        return self._upsert(
            title="Planner-identified environment issue",
            description=description,
            confidence=action.confidence,
            status=status,
            step=step,
            evidence=build_bug_evidence(
                {
                    "source": "planner",
                    "action": action.command,
                    "observation": observation.summary or observation.message,
                },
                action=action,
                observation=observation,
            ),
            tags=["planner"],
            reproduction_step={
                "step": step,
                "action": action.command,
                "observation": observation.summary or observation.message,
                "source": "planner",
            },
        )

    def summary(self, *, max_items: int = 6) -> str:
        if not self._items:
            return "No active bug hypotheses."
        lines = []
        for item in self._items[-max_items:]:
            lines.append(
                "- "
                f"{item.hypothesis_id} [{item.status}, "
                f"confidence={item.confidence:.2f}]: {item.description}"
            )
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {"hypotheses": [asdict(item) for item in self._items]}

    def _upsert(
        self,
        *,
        title: str,
        description: str,
        confidence: float,
        status: str,
        step: int,
        evidence: Dict[str, Any],
        tags: Iterable[str],
        reproduction_step: Dict[str, Any],
    ) -> Hypothesis:
        existing = self._find_similar(description)
        if existing is not None:
            existing.confidence = max(existing.confidence, float(confidence))
            existing.last_step = step
            existing.evidence.update(evidence)
            existing.tags = sorted(set(existing.tags).union(str(tag) for tag in tags if tag))
            if status == "reproduced" or len(existing.reproduction_steps) >= 1:
                existing.status = "reproduced"
            existing.reproduction_steps.append(reproduction_step)
            return existing

        item = Hypothesis(
            hypothesis_id=f"H{len(self._items) + 1}",
            title=title or "Suspected environment issue",
            description=description,
            confidence=float(confidence),
            status=status,
            first_step=step,
            last_step=step,
            evidence=dict(evidence),
            tags=sorted(set(str(tag) for tag in tags if tag)),
            reproduction_steps=[reproduction_step],
        )
        self._items.append(item)
        return item

    def _find_similar(self, description: str) -> Optional[Hypothesis]:
        needle = _normalize_text(description)
        for item in self._items:
            haystack = _normalize_text(item.description)
            if not needle or not haystack:
                continue
            if needle in haystack or haystack in needle:
                return item
            if _token_overlap(needle, haystack) >= 0.5:
                return item
            if SequenceMatcher(None, needle, haystack).ratio() >= 0.84:
                return item
        return None


@dataclass
class CoverageEntry:
    """Observed state/action coverage for one loop step."""

    step: int
    state_key: str
    action: str
    tool: str
    success: bool
    session_id: str = ""
    summary: str = ""


class CoverageState:
    """Track explored states and repeated actions in a backend-agnostic way."""

    def __init__(self) -> None:
        self._entries: List[CoverageEntry] = []
        self._state_order: List[str] = []
        self._actions_by_state: Dict[str, List[str]] = {}
        self._failures: List[CoverageEntry] = []

    def record(
        self,
        *,
        step: int,
        action: Action,
        observation: Observation,
        session_id: str = "",
    ) -> CoverageEntry:
        state_key = self._state_key(observation)
        if state_key not in self._state_order:
            self._state_order.append(state_key)
        actions = self._actions_by_state.setdefault(state_key, [])
        actions.append(action.command)
        entry = CoverageEntry(
            step=step,
            state_key=state_key,
            action=action.command,
            tool=action.tool,
            success=observation.success,
            session_id=session_id,
            summary=observation.summary or observation.message,
        )
        self._entries.append(entry)
        if not observation.success:
            self._failures.append(entry)
        return entry

    def summary(self, *, max_states: int = 5, max_failures: int = 3) -> str:
        if not self._entries:
            return "No coverage has been recorded yet."
        recent_states = self._state_order[-max_states:]
        lines = [
            f"Observed states: {len(self._state_order)}",
            f"Recorded actions: {len(self._entries)}",
        ]
        if recent_states:
            lines.append("Recent state/action frontier:")
            for state_key in recent_states:
                actions = self._actions_by_state.get(state_key, [])
                recent_actions = ", ".join(actions[-4:]) or "none"
                lines.append(f"- {state_key}: {recent_actions}")
        if self._failures:
            lines.append("Recent failed actions:")
            for item in self._failures[-max_failures:]:
                lines.append(f"- step {item.step}: {item.action} -> {item.summary}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unique_state_count": len(self._state_order),
            "recorded_action_count": len(self._entries),
            "states": [
                {
                    "state_key": key,
                    "actions": list(self._actions_by_state.get(key, [])),
                }
                for key in self._state_order
            ],
            "recent_failures": [asdict(item) for item in self._failures[-10:]],
        }

    @staticmethod
    def _state_key(observation: Observation) -> str:
        state = observation.env_state or observation.state or {}
        if isinstance(state, dict):
            for key in (
                "location",
                "room",
                "screen",
                "page",
                "url",
                "title",
                "state_id",
            ):
                value = state.get(key)
                if value:
                    return f"{key}:{str(value)[:80]}"
            try:
                compact = json.dumps(state, sort_keys=True, ensure_ascii=False)
                if compact and compact != "{}":
                    return "state:" + compact[:140]
            except (TypeError, ValueError):
                pass
        summary = (observation.summary or observation.message or "").strip()
        if not summary:
            return "state:unknown"
        normalized = _normalize_text(summary)
        return "text:" + normalized[:140]


def _normalize_text(value: str) -> str:
    return " ".join(str(value).lower().split())


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {
        item
        for item in left.split()
        if len(item) > 2
    }
    right_tokens = {
        item
        for item in right.split()
        if len(item) > 2
    }
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
