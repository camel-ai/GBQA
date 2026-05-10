"""High-level CAMEL runtime access for GBQA agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar
import json
import os

from pydantic import BaseModel

from .camel_runtime import (
    DEFAULT_INPUT_TOKEN_LIMIT,
    DEFAULT_MEMORY_CONTEXT_TOKEN_LIMIT,
    CamelAgentFactory,
    CamelRuntimeConfig,
    CamelTaskAgent,
    ChatAgentResult,
    ReasoningConfig,
)


StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)

DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"


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
        model = config.get("model") or os.getenv("MODEL_NAME") or ""
        api_key = config.get("api_key") or os.getenv("API_KEY") or ""
        base_url = config.get("base_url") or os.getenv("BASE_URL") or DEFAULT_BASE_URL
        missing = [
            name
            for name, value in (
                ("API_KEY", api_key),
                ("MODEL_NAME", model),
            )
            if not value
        ]
        if missing:
            raise RuntimeError("Missing model request field(s): " + ", ".join(missing))
        self._runtime_config = CamelRuntimeConfig(
            model=model,
            model_platform=(
                config.get("model_platform")
                or config.get("platform")
                or "auto"
            ),
            temperature=config.get("temperature", 0.3),
            max_tokens=config.get("max_tokens", 4096),
            timeout=config.get("timeout", 60),
            input_token_limit=int(
                config.get("input_token_limit", DEFAULT_INPUT_TOKEN_LIMIT)
            ),
            api_key=api_key,
            base_url=base_url,
            memory_context_token_limit=int(
                config.get(
                    "memory_context_token_limit",
                    DEFAULT_MEMORY_CONTEXT_TOKEN_LIMIT,
                )
            ),
            reasoning=_parse_reasoning_config(config.get("reasoning", {})),
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
    ) -> CamelTaskAgent:
        """Create a named CAMEL role agent."""
        return self._factory.create_task_agent(
            system_message=system_prompt,
            agent_id=agent_id,
            tools=tools,
            memory=memory,
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


def _parse_reasoning_config(payload: Any) -> ReasoningConfig:
    if payload is None:
        return ReasoningConfig()
    if isinstance(payload, str):
        return ReasoningConfig(mode=payload)
    if not isinstance(payload, dict):
        raise ValueError("llm.reasoning must be a mapping, string, or null")
    max_tokens = payload.get("max_tokens")
    return ReasoningConfig(
        mode=str(payload.get("mode", "auto")),
        effort=str(payload.get("effort", "") or ""),
        max_tokens=int(max_tokens) if max_tokens is not None and max_tokens != "" else None,
    )
