"""LLM Provider protocol and capability types.

Defines the provider interface, capability detection, pricing info,
and streaming configuration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import yaml

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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

    @property
    def supports_vision(self) -> bool:
        """Whether this provider accepts image content blocks inline."""
        return True

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


# ---------------------------------------------------------------------------
# Built-in model registry (static fallback when dynamic cache is unavailable)
# ---------------------------------------------------------------------------

_log = logging.getLogger(__name__)


def _load_builtin_models() -> dict[str, ModelInfo]:
    """Load model definitions from the co-located ``models.yaml`` file.

    Falls back to an empty dict if the file is missing or malformed.
    """
    yaml_path = Path(__file__).parent / "models.yaml"
    try:
        raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text())  # type: ignore[assignment]
    except Exception:
        _log.warning("Failed to load %s – falling back to empty model registry", yaml_path)
        return {}

    if not isinstance(raw, dict):
        return {}

    models_section = raw.get("models")
    if not isinstance(models_section, dict):
        return {}

    result: dict[str, ModelInfo] = {}
    for model_id, attrs in models_section.items():
        if not isinstance(attrs, dict):
            continue
        pricing_data = attrs.get("pricing") or {}
        result[model_id] = ModelInfo(
            model_id=model_id,
            provider=attrs.get("provider", ""),
            max_context_tokens=attrs.get("max_context_tokens", 200_000),
            max_output_tokens=attrs.get("max_output_tokens", 4_096),
            pricing=ModelPricing(
                input_per_million=pricing_data.get("input_per_million", 0.0),
                output_per_million=pricing_data.get("output_per_million", 0.0),
                cache_read_per_million=pricing_data.get("cache_read_per_million", 0.0),
                cache_write_per_million=pricing_data.get("cache_write_per_million", 0.0),
            ),
        )
    return result


BUILTIN_MODELS: dict[str, ModelInfo] = _load_builtin_models()

DEFAULT_CONTEXT_WINDOW = 200_000

# Backward-compat aliases — some callers import these directly
KNOWN_PRICING: dict[str, ModelPricing] = {
    mid: info.pricing for mid, info in BUILTIN_MODELS.items()
}
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    mid: info.max_context_tokens for mid, info in BUILTIN_MODELS.items()
}


# ---------------------------------------------------------------------------
# Lookup helpers (3-tier: dynamic cache → builtin → default)
# ---------------------------------------------------------------------------

def _lookup_builtin(model_id: str) -> ModelInfo | None:
    """Exact match then prefix match against :data:`BUILTIN_MODELS`."""
    if model_id in BUILTIN_MODELS:
        return BUILTIN_MODELS[model_id]
    # Strip provider prefix (e.g. "anthropic/claude-sonnet-4" → "claude-sonnet-4")
    short_id = model_id.rsplit("/", 1)[-1]
    if short_id != model_id and short_id in BUILTIN_MODELS:
        return BUILTIN_MODELS[short_id]
    # Prefix match (dated variant → base entry)
    for known_id, info in BUILTIN_MODELS.items():
        base = known_id.rsplit("-", 1)[0]
        if model_id.startswith(base) or short_id.startswith(base):
            return info
    return None


def get_model_context_window(model_id: str) -> int:
    """Return the context window for *model_id*.

    Resolution: dynamic cache → builtin registry → 200 000 default.
    """
    from attocode.providers.model_cache import get_cached_context_length

    cached = get_cached_context_length(model_id)
    if cached is not None:
        return cached
    info = _lookup_builtin(model_id)
    if info is not None:
        return info.max_context_tokens
    return DEFAULT_CONTEXT_WINDOW


def get_model_pricing(model_id: str) -> ModelPricing:
    """Return pricing for *model_id*.

    Resolution: dynamic cache → builtin registry → zero pricing.
    """
    from attocode.providers.model_cache import get_cached_pricing

    cached = get_cached_pricing(model_id)
    if cached is not None:
        return cached
    info = _lookup_builtin(model_id)
    if info is not None:
        return info.pricing
    return ModelPricing()
