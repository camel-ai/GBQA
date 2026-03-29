"""High-level CAMEL runtime access for GBQA agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar
import json
import os

from pydantic import BaseModel

from .camel_runtime import (
    DEFAULT_CONTEXT_TOKEN_LIMIT,
    DEFAULT_OPENAI_BASE_URL,
    CamelAgentFactory,
    CamelRuntimeConfig,
    CamelTaskAgent,
    ChatAgentResult,
)


StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


@dataclass
class LlmResponse(Generic[StructuredResponseT]):
    """Compatibility wrapper for one-shot CAMEL role execution."""

    content: str
    raw: Dict[str, Any] = field(default_factory=dict)
    parsed: Optional[StructuredResponseT] = None
    error: str = ""


class LlmClient:
    """Application-level access point for creating CAMEL agents."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._runtime_config = CamelRuntimeConfig(
            model=config.get("model") or os.getenv("OPENAI_MODEL") or "",
            model_platform=(
                config.get("model_platform")
                or config.get("platform")
                or os.getenv("CAMEL_MODEL_PLATFORM")
                or "auto"
            ),
            temperature=config.get("temperature", 0.3),
            max_tokens=config.get("max_tokens", 4096),
            timeout=config.get("timeout", 60),
            api_key=config.get("api_key") or os.getenv("OPENAI_API_KEY") or "",
            base_url=(
                config.get("base_url")
                or os.getenv("OPENAI_BASE_URL")
                or DEFAULT_OPENAI_BASE_URL
            ),
            message_window_size=config.get("message_window_size", 6),
            reset_between_turns=bool(config.get("reset_between_turns", True)),
            context_token_limit=int(
                config.get("context_token_limit", DEFAULT_CONTEXT_TOKEN_LIMIT)
            ),
        )
        self._factory = CamelAgentFactory(self._runtime_config)

    @property
    def runtime_config(self) -> CamelRuntimeConfig:
        """Expose immutable runtime settings."""
        return self._runtime_config

    def create_task_agent(
        self,
        system_prompt: str,
        *,
        agent_id: Optional[str] = None,
        tools: Optional[list[Any]] = None,
        memory: Optional[Any] = None,
        reset_between_turns: Optional[bool] = None,
    ) -> CamelTaskAgent:
        """Create a named CAMEL role agent."""
        return self._factory.create_task_agent(
            system_message=system_prompt,
            agent_id=agent_id,
            tools=tools,
            memory=memory,
            reset_between_turns=reset_between_turns,
        )

    def create_history_memory(
        self,
        storage_path: str,
        *,
        agent_id: Optional[str] = None,
        window_size: Optional[int] = None,
        token_limit: Optional[int] = None,
    ) -> Any:
        """Create CAMEL chat-history memory backed by JSON storage."""
        return self._factory.create_history_memory(
            storage_path=storage_path,
            agent_id=agent_id,
            window_size=window_size,
            token_limit=token_limit,
        )

    def chat(self, messages: List[Dict[str, str]]) -> LlmResponse:
        """Compatibility helper for one-shot message-list chat calls."""
        system_parts = []
        prompt_parts = []
        for message in messages:
            role = str(message.get("role", "user")).strip().lower()
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            if role == "system":
                system_parts.append(content)
            else:
                prompt_parts.append(f"{role.upper()}:\n{content}")
        system_prompt = "\n\n".join(system_parts) or "You are a helpful QA assistant."
        user_prompt = "\n\n".join(prompt_parts).strip()
        return self.complete(system_prompt=system_prompt, user_prompt=user_prompt)

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Optional[Type[StructuredResponseT]] = None,
        agent_key: Optional[str] = None,
    ) -> LlmResponse[StructuredResponseT]:
        """Run a one-shot prompt through a transient CAMEL role agent."""
        agent = self.create_task_agent(
            system_prompt,
            agent_id=agent_key,
            reset_between_turns=True,
        )
        result: ChatAgentResult[StructuredResponseT] = agent.run(
            user_prompt,
            response_format=response_format,
        )
        return LlmResponse(
            content=result.content,
            raw={"info": result.info, "error": result.error},
            parsed=result.parsed,
            error=result.error,
        )

    def chat_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Compatibility helper that parses JSON-like output."""
        response = self.chat(messages)
        if response.parsed is not None:
            if hasattr(response.parsed, "model_dump"):
                return response.parsed.model_dump()
            if isinstance(response.parsed, dict):
                return response.parsed
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            return {
                "error": "invalid_json",
                "raw": response.content,
            }
