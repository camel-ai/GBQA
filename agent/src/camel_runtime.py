"""Shared CAMEL runtime helpers for production QA agents."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Iterable, Optional, Type, TypeVar
import json
import re
from urllib.parse import urlparse

from camel.agents import ChatAgent
from camel.memories import ChatHistoryMemory, ScoreBasedContextCreator
from camel.models import ModelFactory
from camel.storages import JsonStorage
from camel.toolkits import FunctionTool
from camel.types import ModelPlatformType
from camel.utils.token_counting import BaseTokenCounter
from pydantic import BaseModel, ValidationError


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CONTEXT_TOKEN_LIMIT = 12000

StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


@dataclass(frozen=True)
class CamelRuntimeConfig:
    """Configuration for CAMEL-backed role agents."""

    model: str
    api_key: str
    model_platform: str = "auto"
    base_url: str = DEFAULT_OPENAI_BASE_URL
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: int = 60
    message_window_size: int = 6
    reset_between_turns: bool = True
    context_token_limit: int = DEFAULT_CONTEXT_TOKEN_LIMIT


@dataclass
class ChatAgentResult(Generic[StructuredResponseT]):
    """Normalized result returned by a CAMEL role agent."""

    content: str
    parsed: Optional[StructuredResponseT] = None
    info: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


class HeuristicTokenCounter(BaseTokenCounter):
    """Offline token counter used for CAMEL memory in restricted environments."""

    _TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def count_tokens_from_messages(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for message in messages:
            content = str(message.get("content", ""))
            total += max(len(self.encode(content)), 1)
        return total

    def encode(self, text: str) -> list[int]:
        if not text:
            return []
        pieces = self._TOKEN_PATTERN.findall(text)
        return list(range(len(pieces)))

    def decode(self, token_ids: list[int]) -> str:
        return " ".join("<tok>" for _ in token_ids)


class CamelTaskAgent:
    """Thin production wrapper around CAMEL ``ChatAgent``."""

    def __init__(
        self,
        config: CamelRuntimeConfig,
        system_message: str,
        *,
        agent_id: Optional[str] = None,
        tools: Optional[Iterable[FunctionTool | Callable[..., Any]]] = None,
        memory: Optional[ChatHistoryMemory] = None,
    ) -> None:
        self._config = config
        self._model_platform = resolve_model_platform(config)
        self._native_structured_output = supports_native_structured_output(
            config,
            self._model_platform,
        )
        self._agent = ChatAgent(
            system_message=system_message,
            model=ModelFactory.create(
                model_platform=self._model_platform,
                model_type=config.model,
                model_config_dict={
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens,
                },
                token_counter=HeuristicTokenCounter(),
                api_key=config.api_key,
                url=config.base_url,
                timeout=config.timeout,
            ),
            memory=memory,
            message_window_size=config.message_window_size,
            tools=list(tools or []),
            agent_id=agent_id,
        )

    def run(
        self,
        prompt: str,
        response_format: Optional[Type[StructuredResponseT]] = None,
    ) -> ChatAgentResult[StructuredResponseT]:
        """Execute one prompt against the CAMEL agent."""
        native_structured_output = getattr(self, "_native_structured_output", True)
        if response_format is not None and not native_structured_output:
            fallback = self._run_text_fallback(
                prompt,
                response_format=response_format,
                original_error="native_structured_output_disabled_for_platform",
            )
            if fallback is not None:
                return fallback
            return ChatAgentResult(
                content="",
                error="native_structured_output_disabled_for_platform",
            )
        if self._config.reset_between_turns:
            self._agent.reset()
        try:
            response = self._agent.step(prompt, response_format=response_format)
        except Exception as exc:  # noqa: BLE001
            if response_format is not None:
                fallback = self._run_text_fallback(
                    prompt,
                    response_format=response_format,
                    original_error=str(exc),
                )
                if fallback is not None:
                    return fallback
            return ChatAgentResult(content="", error=str(exc))
        return self._build_result(response, response_format=response_format)

    def _build_result(
        self,
        response: Any,
        *,
        response_format: Optional[Type[StructuredResponseT]] = None,
        extra_info: Optional[Dict[str, Any]] = None,
        fallback_error: str = "",
    ) -> ChatAgentResult[StructuredResponseT]:
        first_message = response.msgs[0] if response.msgs else None
        info = dict(response.info or {})
        if extra_info:
            info.update(extra_info)
        if first_message is None:
            return ChatAgentResult(
                content="",
                info=info,
                error=fallback_error or "empty_response",
            )

        content = first_message.content or ""
        parsed: Optional[StructuredResponseT] = None
        error = ""
        if response_format is not None:
            parsed = self._coerce_response(
                payload=first_message.parsed,
                content=content,
                response_format=response_format,
            )
            if parsed is None:
                error = fallback_error or "invalid_structured_output"

        return ChatAgentResult(
            content=content,
            parsed=parsed,
            info=info,
            error=error,
        )

    def _run_text_fallback(
        self,
        prompt: str,
        *,
        response_format: Type[StructuredResponseT],
        original_error: str,
    ) -> ChatAgentResult[StructuredResponseT]:
        if self._config.reset_between_turns:
            self._agent.reset()
        try:
            response = self._agent.step(prompt)
        except Exception as exc:  # noqa: BLE001
            message = str(exc).strip()
            if original_error and message:
                message = f"{original_error}: {message}"
            elif original_error:
                message = original_error
            return ChatAgentResult(content="", error=message or "invalid_structured_output")
        return self._build_result(
            response,
            response_format=response_format,
            extra_info={
                "structured_output_fallback": True,
                "structured_output_error": original_error,
            },
            fallback_error=original_error,
        )

    @classmethod
    def _coerce_response(
        cls,
        *,
        payload: Any,
        content: str,
        response_format: Type[StructuredResponseT],
    ) -> Optional[StructuredResponseT]:
        parsed = None
        if payload is not None:
            parsed = cls._coerce_parsed(payload, response_format)
        if parsed is not None:
            return parsed
        return cls._coerce_from_content(content, response_format)

    @staticmethod
    def _coerce_parsed(
        payload: Any,
        response_format: Type[StructuredResponseT],
    ) -> Optional[StructuredResponseT]:
        if isinstance(payload, response_format):
            return payload
        try:
            return response_format.model_validate(payload)
        except ValidationError:
            return None

    @classmethod
    def _coerce_from_content(
        cls,
        content: str,
        response_format: Type[StructuredResponseT],
    ) -> Optional[StructuredResponseT]:
        candidate = cls._extract_json_candidate(content)
        if candidate is None:
            return None
        try:
            return response_format.model_validate_json(candidate)
        except ValidationError:
            pass
        except ValueError:
            pass
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return cls._coerce_parsed(payload, response_format)

    @staticmethod
    def _extract_json_candidate(content: str) -> Optional[str]:
        stripped = content.strip()
        if not stripped:
            return None
        stripped = re.sub(
            r"<think>.*?</think>",
            "",
            stripped,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()
        if not stripped:
            return None
        fenced_match = re.search(
            r"```(?:json)?\s*(\{.*\})\s*```",
            stripped,
            flags=re.DOTALL,
        )
        if fenced_match:
            return fenced_match.group(1).strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return stripped[start : end + 1].strip()


def resolve_model_platform(config: CamelRuntimeConfig) -> ModelPlatformType:
    """Resolve the CAMEL model platform from explicit config or provider URL."""
    explicit = (config.model_platform or "auto").strip()
    if explicit and explicit.lower() != "auto":
        normalized = explicit.upper()
        if normalized.startswith("MODELPLATFORMTYPE."):
            normalized = normalized.split(".", maxsplit=1)[1]
        return ModelPlatformType[normalized]

    host = urlparse(config.base_url).netloc.lower()
    if "modelscope" in host:
        return ModelPlatformType.MODELSCOPE
    if "openrouter" in host:
        return ModelPlatformType.OPENROUTER
    return ModelPlatformType.OPENAI_COMPATIBLE_MODEL


def supports_native_structured_output(
    config: CamelRuntimeConfig,
    model_platform: ModelPlatformType,
) -> bool:
    """Return whether provider-native structured parsing is reliable enough to use."""
    host = urlparse(config.base_url).netloc.lower()
    if "modelscope" in host or "openrouter" in host:
        return False
    return model_platform not in {
        ModelPlatformType.MODELSCOPE,
        ModelPlatformType.OPENROUTER,
        ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
    }


class CamelAgentFactory:
    """Factory for CAMEL role agents and memory objects."""

    def __init__(self, config: CamelRuntimeConfig) -> None:
        self._config = config

    @property
    def config(self) -> CamelRuntimeConfig:
        return self._config

    def create_task_agent(
        self,
        system_message: str,
        *,
        agent_id: Optional[str] = None,
        tools: Optional[Iterable[FunctionTool | Callable[..., Any]]] = None,
        memory: Optional[ChatHistoryMemory] = None,
        reset_between_turns: Optional[bool] = None,
    ) -> CamelTaskAgent:
        """Create a CAMEL role agent with shared runtime settings."""
        runtime_config = self._config
        if reset_between_turns is not None:
            runtime_config = replace(
                self._config,
                reset_between_turns=reset_between_turns,
            )
        return CamelTaskAgent(
            runtime_config,
            system_message,
            agent_id=agent_id,
            tools=tools,
            memory=memory,
        )

    def create_history_memory(
        self,
        storage_path: str | Path,
        *,
        agent_id: Optional[str] = None,
        window_size: Optional[int] = None,
        token_limit: Optional[int] = None,
    ) -> ChatHistoryMemory:
        """Create CAMEL chat-history memory backed by JSON storage."""
        path = Path(storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return ChatHistoryMemory(
            ScoreBasedContextCreator(
                token_counter=HeuristicTokenCounter(),
                token_limit=token_limit or self._config.context_token_limit,
            ),
            storage=JsonStorage(path),
            window_size=window_size,
            agent_id=agent_id,
        )
