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


# -----------------------------------------------------------------------
# sanitize_tool_messages
# -----------------------------------------------------------------------

def test_sanitize_removes_orphaned_tool_result():
    """Tool result without preceding tool call is dropped."""
    from attocode.providers.openai_compat import sanitize_tool_messages

    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "tool", "content": "result", "tool_call_id": "orphan-1"},
        {"role": "assistant", "content": "ok"},
    ]
    result = sanitize_tool_messages(msgs)
    assert len(result) == 2
    assert all(m["role"] != "tool" for m in result)


def test_sanitize_keeps_valid_tool_result():
    """Tool result with matching preceding tool call is kept."""
    from attocode.providers.openai_compat import sanitize_tool_messages

    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "tc-1", "type": "function", "function": {"name": "read", "arguments": "{}"}},
        ]},
        {"role": "tool", "content": "file contents", "tool_call_id": "tc-1"},
        {"role": "assistant", "content": "done"},
    ]
    result = sanitize_tool_messages(msgs)
    assert len(result) == 4


def test_sanitize_drops_only_orphaned_keeps_valid():
    """Mix of valid and orphaned tool results — only orphans removed."""
    from attocode.providers.openai_compat import sanitize_tool_messages

    msgs = [
        {"role": "tool", "content": "orphan", "tool_call_id": "gone-1"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "tc-2", "type": "function", "function": {"name": "bash", "arguments": "{}"}},
        ]},
        {"role": "tool", "content": "valid", "tool_call_id": "tc-2"},
    ]
    result = sanitize_tool_messages(msgs)
    assert len(result) == 2
    assert result[0]["role"] == "assistant"
    assert result[1]["role"] == "tool"
    assert result[1]["tool_call_id"] == "tc-2"


def test_sanitize_no_tool_messages_is_noop():
    """Messages with no tool results pass through unchanged."""
    from attocode.providers.openai_compat import sanitize_tool_messages

    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
    ]
    result = sanitize_tool_messages(msgs)
    assert result == msgs


def test_sanitize_multiple_tool_calls():
    """Multiple tool calls and results in one assistant turn are kept."""
    from attocode.providers.openai_compat import sanitize_tool_messages

    msgs = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "tc-a", "type": "function", "function": {"name": "read", "arguments": "{}"}},
            {"id": "tc-b", "type": "function", "function": {"name": "grep", "arguments": "{}"}},
        ]},
        {"role": "tool", "content": "r1", "tool_call_id": "tc-a"},
        {"role": "tool", "content": "r2", "tool_call_id": "tc-b"},
    ]
    result = sanitize_tool_messages(msgs)
    assert len(result) == 3


# -----------------------------------------------------------------------
# _build_body sanitizes tool messages
# -----------------------------------------------------------------------

def test_build_body_sanitizes_orphaned_tool_results():
    """_build_body strips orphaned tool results before sending."""
    from attocode.providers.minimax import MinimaxProvider
    from attocode.types.messages import Message, Role, ToolCall

    p = MinimaxProvider(api_key="test")
    msgs = [
        Message(role=Role.USER, content="compacted context"),
        Message(role=Role.ASSISTANT, content="summary"),
        # Orphaned tool result (tool_call was compacted away)
        Message(role=Role.TOOL, content="stale result", tool_call_id="old-tc-1"),
        Message(role=Role.USER, content="continue"),
    ]
    body = p._build_body(msgs, None, stream=False)
    tool_msgs = [m for m in body["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 0


def test_sanitize_reorders_interleaved_messages():
    """Interleaved user messages between tool_call and results are moved after results."""
    from attocode.providers.openai_compat import sanitize_tool_messages

    msgs = [
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "tc-1", "type": "function", "function": {"name": "bash", "arguments": "{}"}},
        ]},
        {"role": "user", "content": "[System: phase nudge]"},  # interleaved!
        {"role": "tool", "content": "output", "tool_call_id": "tc-1"},
        {"role": "assistant", "content": "done"},
    ]
    result = sanitize_tool_messages(msgs)
    # Tool result must immediately follow assistant, nudge moved after
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "assistant"
    assert result[2]["role"] == "tool"  # immediately after assistant
    assert result[2]["tool_call_id"] == "tc-1"
    assert result[3]["role"] == "user"  # nudge moved here
    assert result[3]["content"] == "[System: phase nudge]"
    assert result[4]["role"] == "assistant"


def test_sanitize_reorders_multiple_interleaved():
    """Multiple interleaved messages are all moved after tool results."""
    from attocode.providers.openai_compat import sanitize_tool_messages

    msgs = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "tc-a", "type": "function", "function": {"name": "read", "arguments": "{}"}},
            {"id": "tc-b", "type": "function", "function": {"name": "grep", "arguments": "{}"}},
        ]},
        {"role": "user", "content": "[System: doom loop]"},
        {"role": "user", "content": "[System: failure context]"},
        {"role": "tool", "content": "r1", "tool_call_id": "tc-a"},
        {"role": "tool", "content": "r2", "tool_call_id": "tc-b"},
    ]
    result = sanitize_tool_messages(msgs)
    assert result[0]["role"] == "assistant"
    assert result[1]["role"] == "tool"
    assert result[1]["tool_call_id"] == "tc-a"
    assert result[2]["role"] == "tool"
    assert result[2]["tool_call_id"] == "tc-b"
    assert result[3]["content"] == "[System: doom loop]"
    assert result[4]["content"] == "[System: failure context]"


def test_build_body_keeps_valid_tool_results():
    """_build_body preserves tool results that have matching tool calls."""
    from attocode.providers.minimax import MinimaxProvider
    from attocode.types.messages import Message, Role, ToolCall

    p = MinimaxProvider(api_key="test")
    msgs = [
        Message(role=Role.USER, content="do it"),
        Message(role=Role.ASSISTANT, content="", tool_calls=[
            ToolCall(id="tc-1", name="bash", arguments={"cmd": "ls"}),
        ]),
        Message(role=Role.TOOL, content="file.txt", tool_call_id="tc-1"),
    ]
    body = p._build_body(msgs, None, stream=False)
    tool_msgs = [m for m in body["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
