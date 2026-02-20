"""Tests for provider registry."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from attocode.providers.registry import ProviderRegistry, create_provider


class TestProviderRegistry:
    def test_detect_available_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            available = ProviderRegistry.detect_available()
            assert available == []

    def test_detect_anthropic(self) -> None:
        env = {"ANTHROPIC_API_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            available = ProviderRegistry.detect_available()
            assert "anthropic" in available

    def test_detect_openrouter(self) -> None:
        env = {"OPENROUTER_API_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            available = ProviderRegistry.detect_available()
            assert "openrouter" in available

    def test_detect_openai(self) -> None:
        env = {"OPENAI_API_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            available = ProviderRegistry.detect_available()
            assert "openai" in available

    def test_detect_multiple(self) -> None:
        env = {"ANTHROPIC_API_KEY": "sk-1", "OPENAI_API_KEY": "sk-2"}
        with patch.dict(os.environ, env, clear=True):
            available = ProviderRegistry.detect_available()
            assert len(available) == 2
            assert "anthropic" in available
            assert "openai" in available

    def test_register_and_get(self) -> None:
        from attocode.providers.mock import MockProvider

        reg = ProviderRegistry()
        mock = MockProvider()
        reg.register("mock", mock)
        assert reg.get("mock") is mock
        assert reg.get("unknown") is None

    def test_list_providers(self) -> None:
        from attocode.providers.mock import MockProvider

        reg = ProviderRegistry()
        reg.register("a", MockProvider())
        reg.register("b", MockProvider())
        assert sorted(reg.list_providers()) == ["a", "b"]


class TestCreateProvider:
    def test_create_mock(self) -> None:
        provider = create_provider("mock")
        assert provider.name == "mock"

    def test_auto_detect_no_keys(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="No LLM provider found"):
                create_provider()

    def test_unknown_provider(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("nonexistent")

    def test_create_anthropic(self) -> None:
        from attocode.providers.anthropic import AnthropicProvider

        provider = create_provider("anthropic", api_key="sk-test")
        assert isinstance(provider, AnthropicProvider)

    def test_create_openrouter(self) -> None:
        from attocode.providers.openrouter import OpenRouterProvider

        provider = create_provider("openrouter", api_key="sk-test")
        assert isinstance(provider, OpenRouterProvider)

    def test_create_openai(self) -> None:
        from attocode.providers.openai import OpenAIProvider

        provider = create_provider("openai", api_key="sk-test")
        assert isinstance(provider, OpenAIProvider)

    def test_create_with_model(self) -> None:
        from attocode.providers.anthropic import AnthropicProvider

        provider = create_provider("anthropic", api_key="sk-test", model="claude-opus-4-20250514")
        assert isinstance(provider, AnthropicProvider)

    def test_auto_detect_anthropic(self) -> None:
        env = {"ANTHROPIC_API_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=True):
            provider = create_provider()
            assert provider.name == "anthropic"
