"""Provider registry and auto-detection."""

from __future__ import annotations

import os
from typing import Any

from attocode.providers.base import LLMProvider


class ProviderRegistry:
    """Registry of available LLM providers."""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, name: str, provider: LLMProvider) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> LLMProvider | None:
        return self._providers.get(name)

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())

    @staticmethod
    def detect_available() -> list[str]:
        available: list[str] = []
        if os.environ.get("ANTHROPIC_API_KEY"):
            available.append("anthropic")
        if os.environ.get("OPENROUTER_API_KEY"):
            available.append("openrouter")
        if os.environ.get("OPENAI_API_KEY"):
            available.append("openai")
        if os.environ.get("ZAI_API_KEY"):
            available.append("zai")
        return available


def create_provider(
    name: str | None = None,
    *,
    api_key: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> LLMProvider:
    """Create a provider by name, or auto-detect from environment."""
    if name is None:
        available = ProviderRegistry.detect_available()
        if not available:
            raise ValueError("No LLM provider found. Set ANTHROPIC_API_KEY, OPENROUTER_API_KEY, or OPENAI_API_KEY.")
        name = available[0]

    if name == "mock":
        from attocode.providers.mock import MockProvider
        return MockProvider()

    provider_kwargs: dict[str, Any] = {}
    if api_key:
        provider_kwargs["api_key"] = api_key
    if model:
        provider_kwargs["model"] = model
    provider_kwargs.update(kwargs)

    if name == "anthropic":
        from attocode.providers.anthropic import AnthropicProvider
        return AnthropicProvider(**provider_kwargs)
    if name == "openrouter":
        from attocode.providers.openrouter import OpenRouterProvider
        return OpenRouterProvider(**provider_kwargs)
    if name == "openai":
        from attocode.providers.openai import OpenAIProvider
        return OpenAIProvider(**provider_kwargs)
    if name == "zai":
        from attocode.providers.zai import ZAIProvider
        return ZAIProvider(**provider_kwargs)

    raise ValueError(f"Unknown provider: {name}")
