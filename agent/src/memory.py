"""CAMEL-backed session memory for the QA Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
import json

from camel.memories import MemoryRecord
from camel.messages import BaseMessage
from camel.types import OpenAIBackendRole

from .llm_client import LlmClient
from .memory_search import MemoryHit, rank_memories
from .prompts import render_prompt
from .types import SummaryRecord, BugFinding, StepRecord


@dataclass
class MemoryState:
    """Container for memory data."""

    pending_trace_lines: List[str] = field(default_factory=list)
    long_term: List[str] = field(default_factory=list)
    bug_notes: List[str] = field(default_factory=list)


class MemoryManager:
    """Handles session memory using CAMEL chat-history storage."""

    def __init__(
        self,
        max_short_term: int,
        long_term_path: str,
        llm_client: LlmClient,
        auto_summarize: bool,
        summary_threshold: int,
        summary_prompt: str,
        game_id: str,
        session_id: str,
        memory_dir: str,
        session_metadata: Dict[str, Any],
        cross_session_enabled: bool,
        cross_session_top_k: int,
        cross_session_similarity: float,
        load_persistent_long_term: bool,
    ) -> None:
        self._max_short_term = max_short_term
        self._long_term_path = Path(long_term_path)
        self._auto_summarize = auto_summarize
        self._summary_threshold = summary_threshold
        self._summary_prompt = summary_prompt
        self._game_id = game_id
        self._session_id = session_id
        self._memory_dir = Path(memory_dir)
        self._session_metadata = session_metadata
        self._cross_session_enabled = cross_session_enabled
        self._cross_session_top_k = cross_session_top_k
        self._cross_session_similarity = cross_session_similarity
        self._load_persistent_long_term = load_persistent_long_term
        self._state = MemoryState()
        self._summary_agent = llm_client.create_task_agent(
            system_prompt="You summarize gameplay traces.",
            agent_id=f"{game_id}:{session_id}:summary",
        )

        self._session_dir = self._get_memory_dir()
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._chat_history_path = self._session_dir / f"{session_id}_history.json"
        self._summary_log_path = self._session_dir / f"{session_id}.jsonl"
        self._chat_memory = llm_client.create_history_memory(
            str(self._chat_history_path),
            agent_id=f"{game_id}:{session_id}:memory",
            window_size=max_short_term,
        )
        self._load_long_term()

    @property
    def chat_history_path(self) -> Path:
        """Return the persisted CAMEL chat-history path."""
        return self._chat_history_path

    def _load_long_term(self) -> None:
        if not self._load_persistent_long_term:
            return
        if not self._long_term_path.exists():
            return
        with open(self._long_term_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        if isinstance(data, list):
            self._state.long_term = [str(item) for item in data]

    def save_long_term(self) -> None:
        if not self._load_persistent_long_term:
            return
        self._long_term_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._long_term_path, "w", encoding="utf-8") as file_handle:
            json.dump(self._state.long_term, file_handle, ensure_ascii=False, indent=2)

    def record_step(self, record: StepRecord) -> None:
        """Persist a step trace into CAMEL chat-history memory."""
        trace_line = (
            f"Step {record.step}: {record.action.command} -> "
            f"{record.observation.message}"
        )
        self._state.pending_trace_lines.append(trace_line)
        if len(self._state.pending_trace_lines) > self._max_short_term:
            self._state.pending_trace_lines.pop(0)
        self._write_memory_message(
            content=trace_line,
            step=record.step,
            record_type="trace",
            role_name="QA Session",
            role_at_backend=OpenAIBackendRole.USER,
        )
        if record.notes:
            self._write_memory_message(
                content=f"Reflection step {record.step}: {record.notes}",
                step=record.step,
                record_type="reflection",
                role_name="Reflection",
                role_at_backend=OpenAIBackendRole.ASSISTANT,
            )

    def record_bug(self, bug: BugFinding, step: int) -> None:
        """Persist a bug note into session memory."""
        note = f"Step {step}: {bug.title} - {bug.description}"
        self._state.bug_notes.append(note)
        self._write_memory_message(
            content=f"Bug note: {note}",
            step=step,
            record_type="bug",
            role_name="Bug Analyzer",
            role_at_backend=OpenAIBackendRole.ASSISTANT,
        )

    def get_recent_trace(self) -> str:
        """Return the CAMEL memory window as plain text."""
        if (
            not self._chat_history_path.exists()
            or self._chat_history_path.stat().st_size == 0
        ):
            return ""
        messages, _ = self._chat_memory.get_context()
        trace_lines = []
        for message in messages:
            if message.get("role") == "system":
                continue
            content = str(message.get("content", "")).strip()
            if content:
                trace_lines.append(content)
        return "\n".join(trace_lines[-self._max_short_term :])

    def get_long_term_summary(self) -> str:
        """Return persisted long-term summary text."""
        return "\n".join(self._state.long_term)

    def maybe_summarize(self, step: int) -> SummaryRecord | None:
        """Summarize buffered trace lines when thresholds are reached."""
        if not self._auto_summarize:
            return None
        if len(self._state.pending_trace_lines) < self._summary_threshold:
            return None
        return self._commit_summary(step)

    def force_summarize(self, step: int) -> SummaryRecord | None:
        """Force a summary over the current pending trace buffer."""
        if not self._state.pending_trace_lines:
            return None
        return self._commit_summary(step)

    def get_cross_session_memories(self, query: str) -> List[MemoryHit]:
        """Return cross-session summary hits when enabled."""
        if not self._cross_session_enabled:
            return []
        docs = []
        for path in self._session_dir.glob("*.jsonl"):
            if path.name == self._summary_log_path.name:
                continue
            docs.extend(self._load_summary_docs(path))
        return rank_memories(
            query,
            docs,
            top_k=self._cross_session_top_k,
            threshold=self._cross_session_similarity,
        )

    def _commit_summary(self, step: int) -> SummaryRecord | None:
        summary_record = self._summarize_short_term(step)
        if not summary_record or not summary_record.output:
            return None
        self._state.long_term.append(summary_record.output)
        self._state.pending_trace_lines = []
        self._state.bug_notes = []
        self.save_long_term()
        return summary_record

    def _summarize_short_term(self, step: int) -> SummaryRecord | None:
        transcript = "\n".join(self._state.pending_trace_lines)
        bug_section = ""
        if self._state.bug_notes:
            bug_lines = "\n".join(f"- {note}" for note in self._state.bug_notes)
            bug_section = f"\n\nBugs:\n{bug_lines}"
        trace_with_bugs = f"{transcript}{bug_section}".strip()
        if not trace_with_bugs:
            return None
        prompt = render_prompt(
            self._summary_prompt,
            {
                "trace": trace_with_bugs,
                "memory_summary": self.get_long_term_summary(),
            },
        )
        response = self._summary_agent.run(prompt)
        summary_record = SummaryRecord(
            step=step,
            prompt=prompt,
            output=response.content.strip(),
        )
        self._persist_summary(summary_record)
        self._write_memory_message(
            content=f"Summary step {step}: {summary_record.output}",
            step=step,
            record_type="summary",
            role_name="Summary Agent",
            role_at_backend=OpenAIBackendRole.ASSISTANT,
        )
        return summary_record

    def _write_memory_message(
        self,
        *,
        content: str,
        step: int,
        record_type: str,
        role_name: str,
        role_at_backend: OpenAIBackendRole,
    ) -> None:
        message_factory = (
            BaseMessage.make_assistant_message
            if role_at_backend == OpenAIBackendRole.ASSISTANT
            else BaseMessage.make_user_message
        )
        self._chat_memory.write_record(
            MemoryRecord(
                message=message_factory(role_name=role_name, content=content),
                role_at_backend=role_at_backend,
                extra_info={"step": str(step), "record_type": record_type},
                agent_id=f"{self._game_id}:{self._session_id}:memory",
            )
        )

    def _persist_summary(self, summary: SummaryRecord) -> None:
        payload = {
            "type": "summary",
            "game_id": self._game_id,
            "session_id": self._session_id,
            "step": summary.step,
            "prompt": summary.prompt,
            "output": summary.output,
            "metadata": self._session_metadata,
        }
        with open(self._summary_log_path, "a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _load_summary_docs(self, path: Path) -> List[tuple[str, str, int]]:
        docs = []
        try:
            with open(path, "r", encoding="utf-8") as file_handle:
                for line in file_handle:
                    line = line.strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    if payload.get("type") != "summary":
                        continue
                    docs.append(
                        (
                            str(payload.get("output", "")),
                            str(payload.get("session_id", "")),
                            int(payload.get("step", 0)),
                        )
                    )
        except (OSError, json.JSONDecodeError, ValueError):
            return []
        return docs

    def _get_memory_dir(self) -> Path:
        return self._memory_dir / self._game_id
