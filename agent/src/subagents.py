"""Isolated worker subagents for QA harness side tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Type

from pydantic import BaseModel

from .structured_outputs import (
    CodeLocalizerWorkerDecision,
    ExplorerWorkerDecision,
    LogAnalystWorkerDecision,
    ReproducerWorkerDecision,
)
from .tool_registry import ToolRegistry
from .types import BugFinding, SessionHandle


_WORKER_NAMES = {
    "explorer": "ExplorerAgent",
    "reproducer": "ReproducerAgent",
    "log_analyst": "LogAnalystAgent",
    "code_localizer": "CodeLocalizerAgent",
}


@dataclass
class SubagentResult:
    """One isolated worker result."""

    worker: str
    summary: str
    suggestions: list[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    prompt: str = ""
    output: str = ""
    error: str = ""

    def to_dict(self, *, include_prompt: bool = False) -> Dict[str, Any]:
        payload = asdict(self)
        if not include_prompt:
            payload.pop("prompt", None)
            payload.pop("output", None)
        return payload


class SubagentWorker:
    """Fresh one-shot worker agent; no main planner context or memory is shared."""

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        response_format: Type[BaseModel],
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.response_format = response_format
        self.calls = 0

    def run(self, llm_client: Any, prompt: str) -> SubagentResult:
        self.calls += 1
        agent = llm_client.create_task_agent(
            self.system_prompt,
            agent_id=f"subagent.{self.name}.{self.calls}",
        )
        response = agent.run(prompt, response_format=self.response_format)
        parsed = response.parsed
        if parsed is None:
            return SubagentResult(
                worker=_WORKER_NAMES[self.name],
                summary="",
                prompt=prompt,
                output=response.content,
                error=response.error or "invalid_structured_output",
            )
        payload = parsed.model_dump()
        return _result_from_payload(
            worker=_WORKER_NAMES[self.name],
            payload=payload,
            prompt=prompt,
            output=response.content,
            error=response.error,
        )


class SubagentManager:
    """Coordinates isolated QA worker agents without polluting planner context."""

    def __init__(self, *, llm_client: Any, policy: Dict[str, Any]) -> None:
        self._llm_client = llm_client
        self.policy = normalize_subagent_policy(policy)
        self._workers = {
            "explorer": SubagentWorker(
                name="explorer",
                system_prompt=_EXPLORER_SYSTEM_PROMPT,
                response_format=ExplorerWorkerDecision,
            ),
            "reproducer": SubagentWorker(
                name="reproducer",
                system_prompt=_REPRODUCER_SYSTEM_PROMPT,
                response_format=ReproducerWorkerDecision,
            ),
            "log_analyst": SubagentWorker(
                name="log_analyst",
                system_prompt=_LOG_ANALYST_SYSTEM_PROMPT,
                response_format=LogAnalystWorkerDecision,
            ),
            "code_localizer": SubagentWorker(
                name="code_localizer",
                system_prompt=_CODE_LOCALIZER_SYSTEM_PROMPT,
                response_format=CodeLocalizerWorkerDecision,
            ),
        }

    def enabled(self, worker: str) -> bool:
        if not self.policy.get("enabled", False):
            return False
        worker_policy = self.policy.get(worker, {})
        return isinstance(worker_policy, dict) and worker_policy.get("enabled", False)

    def should_run_explorer(self, *, step: int) -> bool:
        if not self.enabled("explorer"):
            return False
        interval = int(self.policy["explorer"].get("interval_steps") or 0)
        return interval > 0 and step > 0 and step % interval == 0

    def explore(self, *, coverage_summary: str, observation_summary: str) -> SubagentResult:
        prompt = _limit_prompt(
            "\n\n".join(
                [
                    "Worker task: identify coverage gaps and next exploration targets.",
                    "Coverage summary:\n" + coverage_summary,
                    "Latest observation:\n" + observation_summary,
                ]
            ),
            self.policy,
        )
        return self._workers["explorer"].run(self._llm_client, prompt)

    def reproduce(
        self,
        *,
        hypothesis_summary: str,
        bug: BugFinding,
        observation_summary: str,
    ) -> SubagentResult:
        prompt = _limit_prompt(
            "\n\n".join(
                [
                    "Worker task: turn the suspected bug into a reproduction plan.",
                    "Hypothesis summary:\n" + hypothesis_summary,
                    "Bug candidate:\n"
                    + f"title={bug.title}\n"
                    + f"description={bug.description}\n"
                    + f"confidence={bug.confidence}",
                    "Latest observation:\n" + observation_summary,
                ]
            ),
            self.policy,
        )
        return self._workers["reproducer"].run(self._llm_client, prompt)

    def analyze_logs(
        self,
        *,
        registry: ToolRegistry,
        session: SessionHandle | None,
        runtime_context: Dict[str, Any],
    ) -> SubagentResult:
        log_summary = ""
        try:
            result = registry.invoke_internal(
                "log_analyze",
                {"include_debug_output": True},
                {"session": session, **runtime_context},
            )
            log_summary = result.observation.summary or result.observation.message
        except Exception as exc:
            return SubagentResult(
                worker=_WORKER_NAMES["log_analyst"],
                summary="",
                error=str(exc),
                evidence={"tool": "log_analyze"},
            )
        prompt = _limit_prompt(
            "\n\n".join(
                [
                    "Worker task: inspect runtime and trajectory logs for bug evidence.",
                    "Log tool summary:\n" + log_summary,
                ]
            ),
            self.policy,
        )
        result = self._workers["log_analyst"].run(self._llm_client, prompt)
        result.evidence.setdefault("log_summary", log_summary)
        return result

    def localize_code(
        self,
        *,
        registry: ToolRegistry,
        session: SessionHandle | None,
        bug: BugFinding,
    ) -> SubagentResult:
        query = "|".join(str(bug.description).split()[:5])
        search_summary = ""
        try:
            result = registry.invoke_internal(
                "code_search",
                {"pattern": query},
                {"session": session},
            )
            search_summary = result.observation.message
        except Exception as exc:
            return SubagentResult(
                worker=_WORKER_NAMES["code_localizer"],
                summary="",
                error=str(exc),
                evidence={"tool": "code_search", "query": query},
            )
        prompt = _limit_prompt(
            "\n\n".join(
                [
                    "Worker task: localize likely code files for this bug.",
                    "Bug candidate:\n"
                    + f"title={bug.title}\n"
                    + f"description={bug.description}\n"
                    + f"confidence={bug.confidence}",
                    "Code search query:\n" + query,
                    "Code search result:\n" + search_summary,
                ]
            ),
            self.policy,
        )
        result = self._workers["code_localizer"].run(self._llm_client, prompt)
        result.evidence.setdefault("code_search_query", query)
        result.evidence.setdefault("code_search_summary", search_summary[:1000])
        return result


def normalize_subagent_policy(
    policy: Dict[str, Any] | None,
    *,
    harness_mode: str = "minimal",
) -> Dict[str, Any]:
    """Normalize worker-subagent policy for config/run_spec export."""

    full = str(harness_mode or "minimal").strip().lower().replace("-", "_") == "full"
    normalized: Dict[str, Any] = {
        "enabled": full,
        "context_isolation": "per_invocation",
        "share_full_trace": False,
        "max_prompt_chars": 6000,
        "record_prompts": False,
        "explorer": {"enabled": full, "interval_steps": 5},
        "reproducer": {"enabled": full, "on_new_hypothesis": True},
        "log_analyst": {"enabled": full, "read_logs": True},
        "code_localizer": {"enabled": full, "read_code": True},
    }
    if policy:
        _deep_update(normalized, policy)
    if not normalized.get("enabled", False):
        for worker in _WORKER_NAMES:
            worker_policy = normalized.setdefault(worker, {})
            if isinstance(worker_policy, dict):
                worker_policy["enabled"] = False
    return normalized


def _result_from_payload(
    *,
    worker: str,
    payload: Dict[str, Any],
    prompt: str,
    output: str,
    error: str,
) -> SubagentResult:
    suggestions: list[str] = []
    for key in (
        "suggested_actions",
        "reproduction_steps",
        "findings",
        "suspected_files",
    ):
        values = payload.get(key, [])
        if isinstance(values, list):
            suggestions.extend(str(item) for item in values if str(item).strip())
    next_action = str(
        payload.get("next_action")
        or payload.get("recommended_next_check")
        or payload.get("recommended_probe")
        or ""
    ).strip()
    if next_action:
        suggestions.append(next_action)
    return SubagentResult(
        worker=worker,
        summary=str(payload.get("summary") or "").strip(),
        suggestions=suggestions[:8],
        evidence=payload,
        prompt=prompt,
        output=output,
        error=error,
    )


def _limit_prompt(prompt: str, policy: Dict[str, Any]) -> str:
    limit = int(policy.get("max_prompt_chars") or 6000)
    if limit <= 0 or len(prompt) <= limit:
        return prompt
    return prompt[-limit:]


def _deep_update(target: Dict[str, Any], update: Dict[str, Any]) -> None:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


_EXPLORER_SYSTEM_PROMPT = """You are ExplorerAgent, an isolated QA worker.
Find uncovered states and high-value next exploration targets.
Do not claim a bug. Return concise structured suggestions only."""

_REPRODUCER_SYSTEM_PROMPT = """You are ReproducerAgent, an isolated QA worker.
Convert one bug hypothesis into a minimal reproduction plan.
Separate confirmed evidence from proposed next checks."""

_LOG_ANALYST_SYSTEM_PROMPT = """You are LogAnalystAgent, an isolated QA worker.
Read log summaries for runtime errors, suspicious transitions, and evidence.
Do not assume source-code access."""

_CODE_LOCALIZER_SYSTEM_PROMPT = """You are CodeLocalizerAgent, an isolated QA worker.
Use code search summaries to localize likely files or symbols.
Do not edit code or ask to run patches."""
