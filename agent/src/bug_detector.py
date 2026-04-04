"""Bug detection rules and CAMEL-based review."""

from __future__ import annotations

from typing import List, Optional

from .llm_client import LlmClient
from .structured_outputs import BugReviewBatch
from .types import Action, BugFinding, Observation


class BugDetector:
    """Rule-based bug detector with CAMEL-based finding refinement."""

    _BENIGN_FAILURE_PATTERNS = (
        "cannot be lit",
        "too high to reach",
        "need something to climb",
        "need to set up something to climb",
        "you are not sure how to use",
        "you can't go that way",
        "cannot go that way",
        "that's not possible",
        "nothing happens",
        "it is locked",
        "it's locked",
        "you don't see",
        "you do not see",
        "you can't do that",
        "you cannot do that",
        "you need",
        "not carrying",
        "don't have",
        "do not have",
        "already",
        "there is no",
        "there's no",
    )
    _SUSPICIOUS_FAILURE_PATTERNS = (
        "traceback",
        "exception",
        "internal server error",
        "server error",
        "unexpected error",
        "nullreference",
        "undefined",
        "stack trace",
        "failed to",
        "runtime error",
        "500",
    )

    def __init__(
        self,
        llm_client: LlmClient,
        enable_llm_analysis: bool,
        auto_confirm_threshold: float,
        rules: List[str],
    ) -> None:
        self._enable_llm_analysis = enable_llm_analysis
        self._auto_confirm_threshold = auto_confirm_threshold
        self._rules = set(rules)
        self._last_turn: Optional[int] = None
        self._review_agent = (
            llm_client.create_task_agent(
                system_prompt="You are a QA analyst summarizing potential bugs.",
                agent_id="bug-review",
            )
            if enable_llm_analysis
            else None
        )

    def inspect(self, action: Action, observation: Observation) -> List[BugFinding]:
        """Inspect an observation with deterministic rules and CAMEL review."""
        execution_origin = str(
            (observation.execution or {}).get("suspected_origin", "")
        )
        if execution_origin == "execution":
            return []

        findings: List[BugFinding] = []

        if "response_format" in self._rules:
            missing = self._check_response_format(observation)
            if missing:
                findings.append(
                    BugFinding(
                        title="Response format missing fields",
                        description=f"Missing fields in response: {', '.join(missing)}",
                        confidence=0.7,
                        evidence={"missing_fields": missing},
                        tags=["response_format"],
                    )
                )

        if "error_message" in self._rules:
            failure_finding = self._check_failed_command(action, observation)
            if failure_finding:
                findings.append(failure_finding)

        if "state_consistency" in self._rules:
            turn_issue = self._check_turn_consistency(observation)
            if turn_issue:
                findings.append(turn_issue)

        if "duplicate_item" in self._rules:
            duplicate_issue = self._check_duplicate_items(observation)
            if duplicate_issue:
                findings.append(duplicate_issue)

        if self._review_agent and findings:
            findings = self._refine_with_llm(action, observation, findings)

        return findings

    @classmethod
    def is_benign_failure(cls, observation: Observation) -> bool:
        """Return whether a failed command looks like an expected game refusal."""
        if observation.success:
            return False
        execution_origin = str(
            (observation.execution or {}).get("suspected_origin", "")
        )
        if execution_origin == "execution":
            return False
        return cls._is_benign_failure_message(observation.message)

    @staticmethod
    def _check_response_format(observation: Observation) -> List[str]:
        missing = []
        if observation.message == "":
            missing.append("message")
        if not isinstance(observation.state, dict):
            missing.append("state")
        return missing

    def _check_turn_consistency(self, observation: Observation) -> Optional[BugFinding]:
        if observation.turn is None:
            return None
        if self._last_turn is not None and observation.turn < self._last_turn:
            return BugFinding(
                title="Turn counter moved backwards",
                description=(
                    f"Turn decreased from {self._last_turn} to {observation.turn}."
                ),
                confidence=0.8,
                evidence={
                    "previous_turn": self._last_turn,
                    "current_turn": observation.turn,
                },
                tags=["state_consistency"],
            )
        self._last_turn = observation.turn
        return None

    @staticmethod
    def _check_duplicate_items(observation: Observation) -> Optional[BugFinding]:
        inventory = observation.state.get("inventory", []) if observation.state else []
        if not isinstance(inventory, list):
            return None
        names = [str(item.get("name", "")) for item in inventory if isinstance(item, dict)]
        duplicates = {name for name in names if name and names.count(name) > 1}
        if duplicates:
            return BugFinding(
                title="Duplicate items in inventory",
                description=f"Duplicate item names detected: {', '.join(duplicates)}",
                confidence=0.6,
                evidence={"duplicates": list(duplicates)},
                tags=["duplicate_item"],
            )
        return None

    @classmethod
    def _check_failed_command(
        cls,
        action: Action,
        observation: Observation,
    ) -> Optional[BugFinding]:
        if observation.success:
            return None
        message = (observation.summary or observation.message or "").strip()
        if not message:
            return BugFinding(
                title="Command failed without explanation",
                description="The game returned an unsuccessful response with no message.",
                confidence=0.85,
                evidence={"command": action.command},
                tags=["error_message", "missing_error_detail"],
            )

        lowered = message.lower()
        if cls._is_benign_failure_message(message):
            return None
        if any(pattern in lowered for pattern in cls._SUSPICIOUS_FAILURE_PATTERNS):
            return BugFinding(
                title="Command triggered system-like failure",
                description=message,
                confidence=0.85,
                evidence={"command": action.command},
                tags=["error_message", "system_failure"],
            )
        return None

    @classmethod
    def _is_benign_failure_message(cls, message: str) -> bool:
        lowered = (message or "").strip().lower()
        if not lowered:
            return False
        return any(pattern in lowered for pattern in cls._BENIGN_FAILURE_PATTERNS)

    def _refine_with_llm(
        self,
        action: Action,
        observation: Observation,
        findings: List[BugFinding],
    ) -> List[BugFinding]:
        summary = "\n".join(
            (
                f"- finding_index={index}; title={item.title}; "
                f"description={item.description}; "
                f"confidence={item.confidence:.2f}"
            )
            for index, item in enumerate(findings)
        )
        response = self._review_agent.run(
            (
                "Review the candidate findings below and refine them. "
                "Keep finding_index aligned with the source list.\n\n"
                f"Action: {action.command}\n"
                f"Observation message: {observation.summary or observation.message}\n"
                f"Findings:\n{summary}"
            ),
            response_format=BugReviewBatch,
        )
        batch = response.parsed
        if batch is None or not batch.findings:
            return findings
        updated: List[BugFinding] = []
        for item in batch.findings:
            if item.finding_index >= len(findings):
                continue
            original = findings[item.finding_index]
            updated.append(
                BugFinding(
                    title=item.title,
                    description=item.description,
                    confidence=float(item.confidence),
                    evidence=original.evidence,
                    tags=[*original.tags, "llm_refined"],
                )
            )
        return updated or findings
