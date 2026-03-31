"""Tests for MiniMax provider."""

from __future__ import annotations

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
    assert p._model == "MiniMax-M2.7"


def test_minimax_custom_model():
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test-key", model="MiniMax-M2.1")
    assert p._model == "MiniMax-M2.1"


def test_minimax_base_url():
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test-key")
    assert "api.minimax.io" in p._api_url


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


# -----------------------------------------------------------------------
# Think-tag stripping
# -----------------------------------------------------------------------

def test_strip_think_tags_basic():
    """Basic think-tag removal."""
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test")
    assert p._strip_think_tags("<think>reasoning</think>Hello!") == "Hello!"


def test_strip_think_tags_multiline():
    """Multiline think block is fully removed."""
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test")
    text = "<think>\nI need to think about this.\nLet me reason step by step.\n</think>\n\nThe answer is 42."
    assert p._strip_think_tags(text) == "The answer is 42."


def test_strip_think_tags_multiple():
    """Multiple think blocks are all removed."""
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test")
    assert p._strip_think_tags("<think>a</think>b<think>c</think>d") == "bd"


def test_strip_think_tags_no_tags():
    """Text without think tags passes through unchanged."""
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test")
    assert p._strip_think_tags("just normal text") == "just normal text"


def test_strip_think_tags_empty_result():
    """Text that is only a think block results in empty string."""
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test")
    assert p._strip_think_tags("<think>all reasoning</think>") == ""


# -----------------------------------------------------------------------
# Body building — temperature clamping and stream options
# -----------------------------------------------------------------------

def test_build_body_clamps_temperature():
    """Temperature is clamped to >= 0.01 (MiniMax rejects 0.0)."""
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test")
    body = p._build_body([], None, stream=False)
    assert body["temperature"] >= 0.01


def test_build_body_clamps_zero_temperature():
    """Explicit temperature=0.0 is clamped up to 0.01."""
    from attocode.providers.minimax import MinimaxProvider
    from attocode.types.messages import ChatOptions
    p = MinimaxProvider(api_key="test")
    opts = ChatOptions(temperature=0.0)
    body = p._build_body([], opts, stream=False)
    assert body["temperature"] == 0.01


def test_build_body_preserves_valid_temperature():
    """A valid temperature (e.g. 0.7) is not clamped."""
    from attocode.providers.minimax import MinimaxProvider
    from attocode.types.messages import ChatOptions
    p = MinimaxProvider(api_key="test")
    opts = ChatOptions(temperature=0.7)
    body = p._build_body([], opts, stream=False)
    assert body["temperature"] == 0.7


def test_build_body_no_stream_options():
    """stream_options is intentionally omitted even for streaming."""
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test")
    body = p._build_body([], None, stream=True)
    assert body.get("stream") is True
    assert "stream_options" not in body


def test_minimax_url_has_chat_completions():
    """API URL ends with /chat/completions."""
    from attocode.providers.minimax import MinimaxProvider
    p = MinimaxProvider(api_key="test")
    assert p._api_url.endswith("/chat/completions")
