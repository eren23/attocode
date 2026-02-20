"""LLM Provider protocol and capability types.

Defines the provider interface, capability detection, pricing info,
and streaming configuration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    Message,
    MessageWithStructuredContent,
    StreamChunk,
)


class ProviderCapability(StrEnum):
    """Capabilities a provider may support."""

    CHAT = "chat"
    STREAMING = "streaming"
    TOOL_USE = "tool_use"
    VISION = "vision"
    EXTENDED_THINKING = "extended_thinking"
    CACHING = "caching"
    JSON_MODE = "json_mode"
    SYSTEM_PROMPT = "system_prompt"
    MULTI_TURN = "multi_turn"
    EMBEDDINGS = "embeddings"


@dataclass(slots=True)
class ModelPricing:
    """Pricing per million tokens for a model."""

    input_per_million: float = 0.0
    output_per_million: float = 0.0
    cache_read_per_million: float = 0.0
    cache_write_per_million: float = 0.0

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
    ) -> float:
        """Estimate cost in dollars for given token counts."""
        cost = (
            (input_tokens * self.input_per_million / 1_000_000)
            + (output_tokens * self.output_per_million / 1_000_000)
            + (cache_read_tokens * self.cache_read_per_million / 1_000_000)
        )
        return cost


@dataclass(slots=True)
class ModelInfo:
    """Information about an LLM model."""

    model_id: str
    provider: str
    display_name: str = ""
    max_context_tokens: int = 200_000
    max_output_tokens: int = 4_096
    capabilities: set[ProviderCapability] = field(default_factory=set)
    pricing: ModelPricing = field(default_factory=ModelPricing)

    @property
    def supports_tools(self) -> bool:
        return ProviderCapability.TOOL_USE in self.capabilities

    @property
    def supports_vision(self) -> bool:
        return ProviderCapability.VISION in self.capabilities

    @property
    def supports_streaming(self) -> bool:
        return ProviderCapability.STREAMING in self.capabilities

    @property
    def supports_caching(self) -> bool:
        return ProviderCapability.CACHING in self.capabilities


@dataclass(slots=True)
class StreamConfig:
    """Configuration for streaming responses."""

    enabled: bool = True
    chunk_timeout_seconds: float = 30.0
    max_idle_seconds: float = 60.0


@dataclass(slots=True)
class ProviderHealth:
    """Health status of a provider."""

    healthy: bool = True
    latency_ms: float = 0.0
    error_rate: float = 0.0
    last_error: str | None = None
    consecutive_failures: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    @property
    def name(self) -> str: ...

    async def chat(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> ChatResponse: ...

    async def close(self) -> None:
        """Release resources (e.g. HTTP client connections)."""
        ...


@runtime_checkable
class StreamingProvider(LLMProvider, Protocol):
    """Provider that supports streaming responses."""

    async def chat_stream(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamChunk]: ...


@runtime_checkable
class CapableProvider(LLMProvider, Protocol):
    """Provider that exposes capability and model information."""

    def get_model_info(self, model_id: str) -> ModelInfo | None: ...

    def list_models(self) -> list[str]: ...

    def supports(self, capability: ProviderCapability) -> bool: ...


# Common model pricing data
KNOWN_PRICING: dict[str, ModelPricing] = {
    "claude-opus-4-20250514": ModelPricing(
        input_per_million=15.0, output_per_million=75.0,
        cache_read_per_million=1.5, cache_write_per_million=18.75,
    ),
    "claude-sonnet-4-20250514": ModelPricing(
        input_per_million=3.0, output_per_million=15.0,
        cache_read_per_million=0.3, cache_write_per_million=3.75,
    ),
    "claude-haiku-4-20250414": ModelPricing(
        input_per_million=0.80, output_per_million=4.0,
        cache_read_per_million=0.08, cache_write_per_million=1.0,
    ),
    "gpt-4o": ModelPricing(
        input_per_million=2.50, output_per_million=10.0,
    ),
    "gpt-4o-mini": ModelPricing(
        input_per_million=0.15, output_per_million=0.60,
    ),
}


def get_model_pricing(model_id: str) -> ModelPricing:
    """Look up pricing for a known model, or return zero pricing."""
    # Check exact match first
    if model_id in KNOWN_PRICING:
        return KNOWN_PRICING[model_id]
    # Check prefix match (e.g. "claude-sonnet-4" matches dated versions)
    for known_id, pricing in KNOWN_PRICING.items():
        if model_id.startswith(known_id.rsplit("-", 1)[0]):
            return pricing
    return ModelPricing()
