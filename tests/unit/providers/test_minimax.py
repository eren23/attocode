"""Tests for MiniMax provider."""

import os

import pytest

from attocode.errors import ProviderError


def test_minimax_requires_api_key():
    """Provider raises ProviderError when MINIMAX_API_KEY not set."""
    env = os.environ.copy()
    os.environ.pop("MINIMAX_API_KEY", None)
    try:
        from attocode.providers.minimax import MinimaxProvider
        with pytest.raises(ProviderError, match="MINIMAX_API_KEY"):
            MinimaxProvider()
    finally:
        os.environ.clear()
        os.environ.update(env)


def test_minimax_accepts_explicit_key():
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test-key-123")
    assert p.name == "minimax"


def test_minimax_default_model():
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test-key")
    assert p.model == "MiniMax-M2.7"


def test_minimax_custom_model():
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test-key", model="MiniMax-M2.1")
    assert p.model == "MiniMax-M2.1"


def test_minimax_base_url():
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test-key")
    assert "api.minimax.io" in p.api_url


def test_minimax_no_vision():
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test-key")
    assert p.supports_vision is False


def test_minimax_in_registry():
    """Provider can be created via the registry."""
    from attocode.providers.registry import create_provider
    p = create_provider("minimax", api_key="test-key")
    assert p.name == "minimax"


def test_minimax_in_config_maps():
    """MiniMax appears in all config maps."""
    from attocode.config import (
        PROVIDER_ENV_VARS,
        PROVIDER_MODEL_DEFAULTS,
        PROVIDER_MODEL_OPTIONS,
    )
    assert "minimax" in PROVIDER_MODEL_DEFAULTS
    assert "minimax" in PROVIDER_ENV_VARS
    assert "minimax" in PROVIDER_MODEL_OPTIONS
    assert PROVIDER_ENV_VARS["minimax"] == "MINIMAX_API_KEY"
    assert len(PROVIDER_MODEL_OPTIONS["minimax"]) == 7
