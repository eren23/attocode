"""Model capability detection.

Determines what features a given LLM model supports based on known
model metadata: vision, tool use, streaming, structured output,
extended thinking, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Capability(StrEnum):
    """Individual model capabilities."""

    TOOL_USE = "tool_use"
    VISION = "vision"
    STREAMING = "streaming"
    STRUCTURED_OUTPUT = "structured_output"
    EXTENDED_THINKING = "extended_thinking"
    PROMPT_CACHING = "prompt_caching"
    COMPUTER_USE = "computer_use"
    PDF_INPUT = "pdf_input"
    CITATIONS = "citations"
    BATCHES = "batches"
    MULTI_TOOL_USE = "multi_tool_use"


@dataclass(slots=True)
class ModelCapabilities:
    """Capabilities for a specific model."""

    model_id: str
    capabilities: set[Capability] = field(default_factory=set)
    max_output_tokens: int = 4096
    max_input_tokens: int = 200_000
    supports_system_prompt: bool = True

    def has(self, cap: Capability) -> bool:
        return cap in self.capabilities

    @property
    def can_use_tools(self) -> bool:
        return Capability.TOOL_USE in self.capabilities

    @property
    def can_see_images(self) -> bool:
        return Capability.VISION in self.capabilities

    @property
    def can_stream(self) -> bool:
        return Capability.STREAMING in self.capabilities

    @property
    def can_think(self) -> bool:
        return Capability.EXTENDED_THINKING in self.capabilities


# Known model capability database
_CAPABILITY_DB: dict[str, ModelCapabilities] = {}


def _register(model_id: str, caps: set[Capability], **kwargs: Any) -> None:
    _CAPABILITY_DB[model_id] = ModelCapabilities(
        model_id=model_id,
        capabilities=caps,
        **kwargs,
    )


# Anthropic Claude models
_CLAUDE_FULL = {
    Capability.TOOL_USE,
    Capability.VISION,
    Capability.STREAMING,
    Capability.STRUCTURED_OUTPUT,
    Capability.EXTENDED_THINKING,
    Capability.PROMPT_CACHING,
    Capability.COMPUTER_USE,
    Capability.PDF_INPUT,
    Capability.CITATIONS,
    Capability.BATCHES,
    Capability.MULTI_TOOL_USE,
}

_register("claude-opus-4-20250514", _CLAUDE_FULL, max_output_tokens=32_000, max_input_tokens=200_000)
_register("claude-sonnet-4-20250514", _CLAUDE_FULL, max_output_tokens=16_000, max_input_tokens=200_000)
_register("claude-haiku-4-20250514", _CLAUDE_FULL - {Capability.EXTENDED_THINKING, Capability.COMPUTER_USE}, max_output_tokens=8192, max_input_tokens=200_000)
_register("claude-3-5-sonnet-20241022", _CLAUDE_FULL - {Capability.EXTENDED_THINKING}, max_output_tokens=8192, max_input_tokens=200_000)

# OpenAI models
_OPENAI_BASE = {
    Capability.TOOL_USE,
    Capability.VISION,
    Capability.STREAMING,
    Capability.STRUCTURED_OUTPUT,
    Capability.MULTI_TOOL_USE,
}

_register("gpt-4o", _OPENAI_BASE, max_output_tokens=16_384, max_input_tokens=128_000)
_register("gpt-4o-mini", _OPENAI_BASE, max_output_tokens=16_384, max_input_tokens=128_000)
_register("gpt-4-turbo", _OPENAI_BASE, max_output_tokens=4096, max_input_tokens=128_000)
_register("o1", _OPENAI_BASE | {Capability.EXTENDED_THINKING}, max_output_tokens=100_000, max_input_tokens=200_000)
_register("o3-mini", _OPENAI_BASE | {Capability.EXTENDED_THINKING}, max_output_tokens=100_000, max_input_tokens=200_000)

# Google models
_register("gemini-2.0-flash", _OPENAI_BASE, max_output_tokens=8192, max_input_tokens=1_000_000)
_register("gemini-2.0-pro", _OPENAI_BASE, max_output_tokens=8192, max_input_tokens=1_000_000)

# DeepSeek
_register("deepseek-chat", {Capability.TOOL_USE, Capability.STREAMING, Capability.STRUCTURED_OUTPUT}, max_output_tokens=8192, max_input_tokens=128_000)
_register("deepseek-reasoner", {Capability.STREAMING, Capability.EXTENDED_THINKING}, max_output_tokens=8192, max_input_tokens=128_000)


def get_capabilities(model_id: str) -> ModelCapabilities:
    """Get capabilities for a model.

    Performs exact match first, then prefix matching for versioned
    model IDs (e.g. ``claude-sonnet-4-20250514`` matches ``claude-sonnet-4``).

    Returns a default set for unknown models.
    """
    # Exact match
    if model_id in _CAPABILITY_DB:
        return _CAPABILITY_DB[model_id]

    # Prefix match (versioned model names)
    for known_id, caps in _CAPABILITY_DB.items():
        if model_id.startswith(known_id) or known_id.startswith(model_id):
            return caps

    # Default: assume basic tool use and streaming
    return ModelCapabilities(
        model_id=model_id,
        capabilities={Capability.TOOL_USE, Capability.STREAMING},
        max_output_tokens=4096,
        max_input_tokens=128_000,
    )


def list_known_models() -> list[str]:
    """List all known model IDs."""
    return sorted(_CAPABILITY_DB.keys())
