"""Tests for streaming handler, PTY shell, and LSP client modules."""

from __future__ import annotations

import asyncio
import json
import os
import platform
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.integrations.streaming.handler import (
    StreamCallback,
    StreamConfig,
    StreamEventListener,
    StreamHandler,
    _StreamState,
    adapt_anthropic_stream,
    adapt_openrouter_stream,
    format_chunk_for_terminal,
)
from attocode.integrations.streaming.pty_shell import (
    CommandResult,
    PTYEventListener,
    PTYShellConfig,
    PTYShellManager,
    ShellState,
    format_shell_state,
)
from attocode.integrations.lsp.client import (
    BUILTIN_SERVERS,
    COMPLETION_KIND_MAP,
    LanguageServerConfig,
    LSPCompletion,
    LSPConfig,
    LSPDiagnostic,
    LSPLocation,
    LSPManager,
    LSPPosition,
    LSPRange,
    _LSPClient,
    _parse_range,
)
from attocode.types.messages import (
    ChatResponse,
    StreamChunk,
    StreamChunkType,
    TokenUsage,
    ToolCall,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


async def async_iter(items: list[Any]) -> AsyncIterator[Any]:
    """Create an async iterator from a list of items."""
    for item in items:
        yield item


def _text_chunk(content: str) -> StreamChunk:
    return StreamChunk(type=StreamChunkType.TEXT, content=content)


def _tool_call_chunk(
    tc_id: str = "tc_1", name: str = "read_file", args: dict | None = None
) -> StreamChunk:
    return StreamChunk(
        type=StreamChunkType.TOOL_CALL,
        tool_call=ToolCall(id=tc_id, name=name, arguments=args or {}),
    )


def _usage_chunk(
    input_tokens: int = 10, output_tokens: int = 20
) -> StreamChunk:
    return StreamChunk(
        type=StreamChunkType.USAGE,
        usage=TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )


def _done_chunk() -> StreamChunk:
    return StreamChunk(type=StreamChunkType.DONE)


def _error_chunk(error: str = "something failed") -> StreamChunk:
    return StreamChunk(type=StreamChunkType.ERROR, error=error)


# ======================================================================
# StreamConfig
# ======================================================================


class TestStreamConfig:
    """Tests for StreamConfig defaults and construction."""

    def test_default_values(self) -> None:
        cfg = StreamConfig()
        assert cfg.enabled is True
        assert cfg.buffer_size == 50
        assert cfg.show_typing_indicator is True

    def test_custom_values(self) -> None:
        cfg = StreamConfig(enabled=False, buffer_size=100, show_typing_indicator=False)
        assert cfg.enabled is False
        assert cfg.buffer_size == 100
        assert cfg.show_typing_indicator is False

    def test_is_dataclass(self) -> None:
        from dataclasses import fields

        names = [f.name for f in fields(StreamConfig)]
        assert "enabled" in names
        assert "buffer_size" in names
        assert "show_typing_indicator" in names


# ======================================================================
# _StreamState (internal)
# ======================================================================


class TestStreamState:
    """Tests for internal stream state accumulator."""

    def test_default_values(self) -> None:
        state = _StreamState()
        assert state.content == ""
        assert state.tool_calls == []
        assert state.current_tool_call is None
        assert state.usage is None

    def test_content_accumulation(self) -> None:
        state = _StreamState()
        state.content += "Hello"
        state.content += " world"
        assert state.content == "Hello world"

    def test_tool_calls_list(self) -> None:
        state = _StreamState()
        tc = ToolCall(id="t1", name="write_file", arguments={"path": "a.py"})
        state.tool_calls.append(tc)
        assert len(state.tool_calls) == 1


# ======================================================================
# StreamHandler
# ======================================================================


class TestStreamHandlerInit:
    """Tests for StreamHandler initialization."""

    def test_default_config(self) -> None:
        handler = StreamHandler()
        assert handler.is_enabled() is True

    def test_custom_config(self) -> None:
        cfg = StreamConfig(enabled=False)
        handler = StreamHandler(config=cfg)
        assert handler.is_enabled() is False

    def test_is_enabled_returns_config_enabled(self) -> None:
        handler = StreamHandler(StreamConfig(enabled=True))
        assert handler.is_enabled() is True
        handler2 = StreamHandler(StreamConfig(enabled=False))
        assert handler2.is_enabled() is False


class TestStreamHandlerProcessStream:
    """Tests for StreamHandler.process_stream."""

    @pytest.mark.asyncio
    async def test_text_chunks_accumulate_content(self) -> None:
        handler = StreamHandler()
        chunks = [_text_chunk("Hello"), _text_chunk(" world"), _done_chunk()]
        result = await handler.process_stream(async_iter(chunks))

        assert isinstance(result, ChatResponse)
        assert result.content == "Hello world"

    @pytest.mark.asyncio
    async def test_tool_call_chunks_collected(self) -> None:
        handler = StreamHandler()
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "f.py"})
        chunks = [
            StreamChunk(type=StreamChunkType.TOOL_CALL, tool_call=tc),
            _done_chunk(),
        ]
        result = await handler.process_stream(async_iter(chunks))

        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self) -> None:
        handler = StreamHandler()
        chunks = [
            _tool_call_chunk("t1", "read_file", {"path": "a.py"}),
            _tool_call_chunk("t2", "write_file", {"path": "b.py"}),
            _done_chunk(),
        ]
        result = await handler.process_stream(async_iter(chunks))
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[1].name == "write_file"

    @pytest.mark.asyncio
    async def test_usage_chunk_recorded(self) -> None:
        handler = StreamHandler()
        chunks = [_usage_chunk(100, 200), _done_chunk()]
        result = await handler.process_stream(async_iter(chunks))

        assert result.usage is not None
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 200
        assert result.usage.total_tokens == 300

    @pytest.mark.asyncio
    async def test_done_chunk_flushes_buffer(self) -> None:
        handler = StreamHandler(StreamConfig(buffer_size=1000))
        events: list[tuple[str, dict]] = []
        handler.on(lambda e, d: events.append((e, d)))

        chunks = [_text_chunk("small text"), _done_chunk()]
        await handler.process_stream(async_iter(chunks))

        text_events = [e for e in events if e[0] == "stream.text"]
        # Buffer flush should happen (either from DONE chunk or final flush)
        assert any("small text" in ev[1].get("content", "") for ev in text_events)

    @pytest.mark.asyncio
    async def test_error_chunk_emits_event(self) -> None:
        handler = StreamHandler()
        events: list[tuple[str, dict]] = []
        handler.on(lambda e, d: events.append((e, d)))

        chunks = [_error_chunk("bad things"), _done_chunk()]
        await handler.process_stream(async_iter(chunks))

        error_events = [e for e in events if e[0] == "stream.error"]
        assert len(error_events) == 1
        assert error_events[0][1]["error"] == "bad things"

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_none(self) -> None:
        handler = StreamHandler()
        chunks = [_text_chunk("just text"), _done_chunk()]
        result = await handler.process_stream(async_iter(chunks))
        assert result.tool_calls is None

    @pytest.mark.asyncio
    async def test_empty_stream(self) -> None:
        handler = StreamHandler()
        result = await handler.process_stream(async_iter([]))
        assert result.content == ""
        assert result.tool_calls is None
        assert result.usage is None

    @pytest.mark.asyncio
    async def test_stream_exception_propagates(self) -> None:
        handler = StreamHandler()

        async def error_stream() -> AsyncIterator[StreamChunk]:
            yield _text_chunk("partial")
            raise RuntimeError("network fail")

        with pytest.raises(RuntimeError, match="network fail"):
            await handler.process_stream(error_stream())

    @pytest.mark.asyncio
    async def test_stream_exception_emits_error_event(self) -> None:
        handler = StreamHandler()
        events: list[tuple[str, dict]] = []
        handler.on(lambda e, d: events.append((e, d)))

        async def error_stream() -> AsyncIterator[StreamChunk]:
            raise ValueError("parse error")
            yield  # noqa: unreachable - makes this an async generator

        with pytest.raises(ValueError):
            await handler.process_stream(error_stream())

        error_events = [e for e in events if e[0] == "stream.error"]
        assert len(error_events) >= 1


class TestStreamHandlerBuffering:
    """Tests for text buffering behavior."""

    @pytest.mark.asyncio
    async def test_buffer_fills_at_buffer_size_then_emits(self) -> None:
        handler = StreamHandler(StreamConfig(buffer_size=10))
        text_events: list[str] = []
        handler.on(
            lambda e, d: text_events.append(d.get("content", ""))
            if e == "stream.text"
            else None
        )

        chunks = [
            _text_chunk("12345"),  # 5 chars, buffer not full
            _text_chunk("67890"),  # 10 chars total, buffer full -> emit
            _text_chunk("abc"),    # 3 chars
            _done_chunk(),         # flush remaining
        ]
        await handler.process_stream(async_iter(chunks))

        assert len(text_events) >= 2
        assert "1234567890" in text_events

    @pytest.mark.asyncio
    async def test_buffer_flush_on_done_with_remaining(self) -> None:
        handler = StreamHandler(StreamConfig(buffer_size=100))
        text_events: list[str] = []
        handler.on(
            lambda e, d: text_events.append(d.get("content", ""))
            if e == "stream.text"
            else None
        )

        chunks = [_text_chunk("short"), _done_chunk()]
        await handler.process_stream(async_iter(chunks))

        assert any("short" in t for t in text_events)

    @pytest.mark.asyncio
    async def test_no_extra_flush_when_buffer_empty(self) -> None:
        handler = StreamHandler(StreamConfig(buffer_size=5))
        text_events: list[str] = []
        handler.on(
            lambda e, d: text_events.append(d.get("content", ""))
            if e == "stream.text"
            else None
        )

        # Exactly fills and empties the buffer
        chunks = [_text_chunk("12345"), _done_chunk()]
        await handler.process_stream(async_iter(chunks))

        # Should emit once from buffer fill (5==5), then nothing from done since empty
        non_empty_texts = [t for t in text_events if t]
        assert len(non_empty_texts) >= 1


class TestStreamHandlerEvents:
    """Tests for event subscription."""

    def test_on_subscribes_returns_unsubscribe(self) -> None:
        handler = StreamHandler()
        events: list[str] = []
        unsub = handler.on(lambda e, d: events.append(e))
        assert callable(unsub)

    def test_unsubscribe_removes_listener(self) -> None:
        handler = StreamHandler()
        events: list[str] = []
        unsub = handler.on(lambda e, d: events.append(e))

        handler._emit("test.event", {})
        assert len(events) == 1

        unsub()
        handler._emit("test.event", {})
        assert len(events) == 1  # No new event

    def test_double_unsubscribe_safe(self) -> None:
        handler = StreamHandler()
        unsub = handler.on(lambda e, d: None)
        unsub()
        unsub()  # Should not raise

    def test_multiple_listeners(self) -> None:
        handler = StreamHandler()
        events_a: list[str] = []
        events_b: list[str] = []
        handler.on(lambda e, d: events_a.append(e))
        handler.on(lambda e, d: events_b.append(e))

        handler._emit("test.x", {})
        assert len(events_a) == 1
        assert len(events_b) == 1

    def test_listener_error_silently_caught(self) -> None:
        handler = StreamHandler()

        def bad_listener(event: str, data: dict) -> None:
            raise RuntimeError("listener crash")

        handler.on(bad_listener)
        events: list[str] = []
        handler.on(lambda e, d: events.append(e))

        handler._emit("test.event", {})
        # Second listener should still be called despite first crashing
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_on_chunk_callback_called(self) -> None:
        handler = StreamHandler()
        received: list[StreamChunk] = []

        def on_chunk(chunk: StreamChunk) -> None:
            received.append(chunk)

        chunks = [_text_chunk("hi"), _done_chunk()]
        await handler.process_stream(async_iter(chunks), on_chunk=on_chunk)
        assert len(received) == 2
        assert received[0].type == StreamChunkType.TEXT
        assert received[1].type == StreamChunkType.DONE

    @pytest.mark.asyncio
    async def test_start_and_complete_events_emitted(self) -> None:
        handler = StreamHandler()
        events: list[str] = []
        handler.on(lambda e, d: events.append(e))

        chunks = [_text_chunk("x"), _done_chunk()]
        await handler.process_stream(async_iter(chunks))

        assert "stream.start" in events
        assert "stream.complete" in events

    @pytest.mark.asyncio
    async def test_tool_call_event_emitted(self) -> None:
        handler = StreamHandler()
        events: list[tuple[str, dict]] = []
        handler.on(lambda e, d: events.append((e, d)))

        tc = ToolCall(id="tc_99", name="glob", arguments={"pattern": "*.py"})
        chunks = [
            StreamChunk(type=StreamChunkType.TOOL_CALL, tool_call=tc),
            _done_chunk(),
        ]
        await handler.process_stream(async_iter(chunks))

        tc_events = [e for e in events if e[0] == "stream.tool_call"]
        assert len(tc_events) == 1
        assert tc_events[0][1]["tool_call"].name == "glob"


# ======================================================================
# SSE Adapter: adapt_openrouter_stream
# ======================================================================


class TestAdaptOpenRouterStream:
    """Tests for OpenRouter/OpenAI SSE adapter."""

    @pytest.mark.asyncio
    async def test_text_delta_yields_text_chunk(self) -> None:
        line = 'data: {"choices":[{"delta":{"content":"Hello"}}]}'
        chunks = [c async for c in adapt_openrouter_stream(async_iter([line]))]
        # Should get a TEXT chunk + final DONE
        text_chunks = [c for c in chunks if c.type == StreamChunkType.TEXT]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "Hello"

    @pytest.mark.asyncio
    async def test_done_marker_yields_done_chunk(self) -> None:
        lines = [
            'data: {"choices":[{"delta":{"content":"x"}}]}',
            "data: [DONE]",
        ]
        chunks = [c async for c in adapt_openrouter_stream(async_iter(lines))]
        assert chunks[-1].type == StreamChunkType.DONE

    @pytest.mark.asyncio
    async def test_tool_calls_delta(self) -> None:
        data = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "a.py"}',
                        },
                    }]
                }
            }]
        }
        line = f"data: {json.dumps(data)}"
        chunks = [c async for c in adapt_openrouter_stream(async_iter([line]))]
        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 1
        assert tc_chunks[0].tool_call is not None
        assert tc_chunks[0].tool_call.name == "read_file"
        assert tc_chunks[0].tool_call.arguments == {"path": "a.py"}

    @pytest.mark.asyncio
    async def test_tool_call_with_invalid_json_args(self) -> None:
        data = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "id": "call_2",
                        "function": {
                            "name": "write_file",
                            "arguments": "not valid json",
                        },
                    }]
                }
            }]
        }
        line = f"data: {json.dumps(data)}"
        chunks = [c async for c in adapt_openrouter_stream(async_iter([line]))]
        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 1
        assert tc_chunks[0].tool_call is not None
        assert tc_chunks[0].tool_call.arguments == {}

    @pytest.mark.asyncio
    async def test_usage_from_final_chunk(self) -> None:
        data = {
            "choices": [{"delta": {}}],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 100,
                "total_tokens": 150,
            },
        }
        line = f"data: {json.dumps(data)}"
        chunks = [c async for c in adapt_openrouter_stream(async_iter([line]))]
        usage_chunks = [c for c in chunks if c.type == StreamChunkType.USAGE]
        assert len(usage_chunks) == 1
        assert usage_chunks[0].usage is not None
        assert usage_chunks[0].usage.input_tokens == 50
        assert usage_chunks[0].usage.output_tokens == 100
        assert usage_chunks[0].usage.total_tokens == 150

    @pytest.mark.asyncio
    async def test_ignores_non_data_lines(self) -> None:
        lines = [
            "event: message",
            ": comment",
            "",
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            "data: [DONE]",
        ]
        chunks = [c async for c in adapt_openrouter_stream(async_iter(lines))]
        text_chunks = [c for c in chunks if c.type == StreamChunkType.TEXT]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "ok"

    @pytest.mark.asyncio
    async def test_handles_json_parse_error_gracefully(self) -> None:
        lines = [
            "data: {invalid json",
            "data: [DONE]",
        ]
        chunks = [c async for c in adapt_openrouter_stream(async_iter(lines))]
        # Should still yield DONE without crashing
        assert any(c.type == StreamChunkType.DONE for c in chunks)

    @pytest.mark.asyncio
    async def test_empty_choices_handled(self) -> None:
        line = 'data: {"choices":[]}'
        chunks = [c async for c in adapt_openrouter_stream(async_iter([line]))]
        # Should not crash; may produce DONE from end of stream
        assert any(c.type == StreamChunkType.DONE for c in chunks)

    @pytest.mark.asyncio
    async def test_no_content_in_delta_no_text_chunk(self) -> None:
        line = 'data: {"choices":[{"delta":{"role":"assistant"}}]}'
        chunks = [c async for c in adapt_openrouter_stream(async_iter([line]))]
        text_chunks = [c for c in chunks if c.type == StreamChunkType.TEXT]
        assert len(text_chunks) == 0

    @pytest.mark.asyncio
    async def test_end_of_stream_without_done_marker_yields_done(self) -> None:
        line = 'data: {"choices":[{"delta":{"content":"hi"}}]}'
        chunks = [c async for c in adapt_openrouter_stream(async_iter([line]))]
        assert chunks[-1].type == StreamChunkType.DONE

    @pytest.mark.asyncio
    async def test_tool_call_without_name_not_yielded(self) -> None:
        """Tool call delta with no function name should not yield TOOL_CALL."""
        data = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "id": "call_x",
                        "function": {"arguments": '{"x": 1}'},
                    }]
                }
            }]
        }
        line = f"data: {json.dumps(data)}"
        chunks = [c async for c in adapt_openrouter_stream(async_iter([line]))]
        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 0

    @pytest.mark.asyncio
    async def test_tool_call_without_arguments_not_yielded(self) -> None:
        """Tool call delta with name but no arguments should not yield TOOL_CALL."""
        data = {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "id": "call_y",
                        "function": {"name": "some_tool"},
                    }]
                }
            }]
        }
        line = f"data: {json.dumps(data)}"
        chunks = [c async for c in adapt_openrouter_stream(async_iter([line]))]
        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 0


# ======================================================================
# SSE Adapter: adapt_anthropic_stream
# ======================================================================


class TestAdaptAnthropicStream:
    """Tests for Anthropic SSE adapter."""

    @pytest.mark.asyncio
    async def test_content_block_start_with_tool_use_tracks_tool(self) -> None:
        # Start a tool, accumulate args, stop -> yields TOOL_CALL
        start_data = {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "tool_1", "name": "bash"},
        }
        delta_data = {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"cmd": "ls"}'},
        }
        stop_data = {"type": "content_block_stop"}
        msg_stop = {"type": "message_stop"}

        lines = [
            f"data: {json.dumps(start_data)}",
            f"data: {json.dumps(delta_data)}",
            f"data: {json.dumps(stop_data)}",
            f"data: {json.dumps(msg_stop)}",
        ]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]

        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 1
        assert tc_chunks[0].tool_call is not None
        assert tc_chunks[0].tool_call.name == "bash"
        assert tc_chunks[0].tool_call.id == "tool_1"
        assert tc_chunks[0].tool_call.arguments == {"cmd": "ls"}

    @pytest.mark.asyncio
    async def test_text_delta_yields_text_chunk(self) -> None:
        delta_data = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello world"},
        }
        msg_stop = {"type": "message_stop"}
        lines = [
            f"data: {json.dumps(delta_data)}",
            f"data: {json.dumps(msg_stop)}",
        ]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]
        text_chunks = [c for c in chunks if c.type == StreamChunkType.TEXT]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "Hello world"

    @pytest.mark.asyncio
    async def test_input_json_delta_accumulates(self) -> None:
        start = {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "t1", "name": "grep"},
        }
        delta1 = {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"pat'},
        }
        delta2 = {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": 'tern": "foo"}'},
        }
        stop = {"type": "content_block_stop"}
        msg_stop = {"type": "message_stop"}

        lines = [f"data: {json.dumps(d)}" for d in [start, delta1, delta2, stop, msg_stop]]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]

        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 1
        assert tc_chunks[0].tool_call is not None
        assert tc_chunks[0].tool_call.arguments == {"pattern": "foo"}

    @pytest.mark.asyncio
    async def test_content_block_stop_with_tool_yields_tool_call(self) -> None:
        start = {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "t2", "name": "edit"},
        }
        stop = {"type": "content_block_stop"}
        msg_stop = {"type": "message_stop"}

        lines = [f"data: {json.dumps(d)}" for d in [start, stop, msg_stop]]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]

        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 1
        assert tc_chunks[0].tool_call is not None
        assert tc_chunks[0].tool_call.name == "edit"
        assert tc_chunks[0].tool_call.arguments == {}

    @pytest.mark.asyncio
    async def test_message_delta_with_usage_yields_usage(self) -> None:
        msg_delta = {
            "type": "message_delta",
            "usage": {"input_tokens": 500, "output_tokens": 200},
        }
        msg_stop = {"type": "message_stop"}
        lines = [
            f"data: {json.dumps(msg_delta)}",
            f"data: {json.dumps(msg_stop)}",
        ]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]
        usage_chunks = [c for c in chunks if c.type == StreamChunkType.USAGE]
        assert len(usage_chunks) == 1
        assert usage_chunks[0].usage is not None
        assert usage_chunks[0].usage.input_tokens == 500
        assert usage_chunks[0].usage.output_tokens == 200
        assert usage_chunks[0].usage.total_tokens == 700

    @pytest.mark.asyncio
    async def test_message_stop_yields_done(self) -> None:
        msg_stop = {"type": "message_stop"}
        lines = [f"data: {json.dumps(msg_stop)}"]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]
        assert chunks[-1].type == StreamChunkType.DONE

    @pytest.mark.asyncio
    async def test_ignores_non_data_lines(self) -> None:
        lines = [
            "event: content_block_delta",
            ": keep-alive",
            "",
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}',
            'data: {"type":"message_stop"}',
        ]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]
        text_chunks = [c for c in chunks if c.type == StreamChunkType.TEXT]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "hi"

    @pytest.mark.asyncio
    async def test_json_parse_error_gracefully_skipped(self) -> None:
        lines = [
            "data: {broken json",
            'data: {"type":"message_stop"}',
        ]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]
        assert any(c.type == StreamChunkType.DONE for c in chunks)

    @pytest.mark.asyncio
    async def test_content_block_stop_without_tool_no_tool_call(self) -> None:
        """content_block_stop without prior tool_use start should not yield TOOL_CALL."""
        stop = {"type": "content_block_stop"}
        msg_stop = {"type": "message_stop"}
        lines = [f"data: {json.dumps(d)}" for d in [stop, msg_stop]]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]
        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 0

    @pytest.mark.asyncio
    async def test_end_of_stream_without_message_stop_yields_done(self) -> None:
        text_delta = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "partial"},
        }
        lines = [f"data: {json.dumps(text_delta)}"]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]
        assert chunks[-1].type == StreamChunkType.DONE

    @pytest.mark.asyncio
    async def test_invalid_tool_args_json_defaults_to_empty(self) -> None:
        start = {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "id": "t3", "name": "exec"},
        }
        delta = {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": "{bad"},
        }
        stop = {"type": "content_block_stop"}
        msg_stop = {"type": "message_stop"}

        lines = [f"data: {json.dumps(d)}" for d in [start, delta, stop, msg_stop]]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]
        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 1
        assert tc_chunks[0].tool_call is not None
        assert tc_chunks[0].tool_call.arguments == {}

    @pytest.mark.asyncio
    async def test_multiple_tool_blocks(self) -> None:
        """Multiple content_block_start/stop cycles produce multiple TOOL_CALL chunks."""
        events = [
            {"type": "content_block_start", "content_block": {"type": "tool_use", "id": "a", "name": "tool_a"}},
            {"type": "content_block_stop"},
            {"type": "content_block_start", "content_block": {"type": "tool_use", "id": "b", "name": "tool_b"}},
            {"type": "content_block_stop"},
            {"type": "message_stop"},
        ]
        lines = [f"data: {json.dumps(e)}" for e in events]
        chunks = [c async for c in adapt_anthropic_stream(async_iter(lines))]
        tc_chunks = [c for c in chunks if c.type == StreamChunkType.TOOL_CALL]
        assert len(tc_chunks) == 2
        assert tc_chunks[0].tool_call.name == "tool_a"
        assert tc_chunks[1].tool_call.name == "tool_b"


# ======================================================================
# format_chunk_for_terminal
# ======================================================================


class TestFormatChunkForTerminal:
    """Tests for format_chunk_for_terminal."""

    def test_text_chunk_returns_content(self) -> None:
        chunk = _text_chunk("Hello world")
        assert format_chunk_for_terminal(chunk) == "Hello world"

    def test_text_chunk_none_content_returns_empty(self) -> None:
        chunk = StreamChunk(type=StreamChunkType.TEXT, content=None)
        assert format_chunk_for_terminal(chunk) == ""

    def test_tool_call_chunk_returns_tool_name(self) -> None:
        tc = ToolCall(id="t", name="bash", arguments={})
        chunk = StreamChunk(type=StreamChunkType.TOOL_CALL, tool_call=tc)
        result = format_chunk_for_terminal(chunk)
        assert "bash" in result
        assert "Tool:" in result

    def test_tool_call_chunk_no_tool_call_returns_unknown(self) -> None:
        chunk = StreamChunk(type=StreamChunkType.TOOL_CALL, tool_call=None)
        result = format_chunk_for_terminal(chunk)
        assert "unknown" in result

    def test_error_chunk_returns_error_text(self) -> None:
        chunk = _error_chunk("timeout occurred")
        result = format_chunk_for_terminal(chunk)
        assert "timeout occurred" in result
        assert "Error:" in result

    def test_done_chunk_returns_newline(self) -> None:
        chunk = _done_chunk()
        assert format_chunk_for_terminal(chunk) == "\n"

    def test_usage_chunk_returns_empty(self) -> None:
        chunk = _usage_chunk(10, 20)
        assert format_chunk_for_terminal(chunk) == ""

    def test_thinking_chunk_returns_empty(self) -> None:
        chunk = StreamChunk(type=StreamChunkType.THINKING, content="hmm")
        assert format_chunk_for_terminal(chunk) == ""


# ======================================================================
# PTYShellConfig
# ======================================================================


class TestPTYShellConfig:
    """Tests for PTYShellConfig defaults."""

    def test_default_values(self) -> None:
        cfg = PTYShellConfig()
        assert cfg.shell == ""
        assert cfg.cwd == ""
        assert cfg.env == {}
        assert cfg.timeout == 30.0
        assert cfg.max_output_size == 1_048_576
        assert cfg.prompt_pattern == "__CMD_DONE__"

    def test_custom_values(self) -> None:
        cfg = PTYShellConfig(
            shell="/bin/zsh",
            cwd="/tmp",
            env={"FOO": "bar"},
            timeout=60.0,
            max_output_size=2_000_000,
            prompt_pattern="DONE_MARKER",
        )
        assert cfg.shell == "/bin/zsh"
        assert cfg.cwd == "/tmp"
        assert cfg.env == {"FOO": "bar"}
        assert cfg.timeout == 60.0
        assert cfg.max_output_size == 2_000_000
        assert cfg.prompt_pattern == "DONE_MARKER"


# ======================================================================
# CommandResult
# ======================================================================


class TestCommandResult:
    """Tests for CommandResult dataclass."""

    def test_fields(self) -> None:
        r = CommandResult(output="ok", exit_code=0, duration=1.5, timed_out=False)
        assert r.output == "ok"
        assert r.exit_code == 0
        assert r.duration == 1.5
        assert r.timed_out is False

    def test_timed_out_result(self) -> None:
        r = CommandResult(output="partial", exit_code=None, duration=30.0, timed_out=True)
        assert r.exit_code is None
        assert r.timed_out is True

    def test_none_exit_code(self) -> None:
        r = CommandResult(output="", exit_code=None, duration=0.1, timed_out=False)
        assert r.exit_code is None


# ======================================================================
# ShellState
# ======================================================================


class TestShellState:
    """Tests for ShellState dataclass."""

    def test_fields(self) -> None:
        state = ShellState(
            cwd="/home/user",
            env={"PATH": "/usr/bin"},
            history=["ls", "pwd"],
            is_running=True,
            pid=12345,
        )
        assert state.cwd == "/home/user"
        assert state.env == {"PATH": "/usr/bin"}
        assert state.history == ["ls", "pwd"]
        assert state.is_running is True
        assert state.pid == 12345

    def test_default_pid_none(self) -> None:
        state = ShellState(cwd="/tmp", env={}, history=[], is_running=False)
        assert state.pid is None

    def test_stopped_state(self) -> None:
        state = ShellState(cwd="/tmp", env={}, history=[], is_running=False, pid=None)
        assert state.is_running is False
        assert state.pid is None


# ======================================================================
# PTYShellManager
# ======================================================================


class TestPTYShellManagerInit:
    """Tests for PTYShellManager construction and synchronous methods."""

    def test_default_construction(self) -> None:
        mgr = PTYShellManager()
        state = mgr.get_state()
        assert state.is_running is False
        assert state.pid is None
        assert state.history == []

    def test_custom_config(self) -> None:
        cfg = PTYShellConfig(shell="/bin/zsh", cwd="/tmp", timeout=10.0)
        mgr = PTYShellManager(config=cfg)
        state = mgr.get_state()
        assert state.cwd == "/tmp"

    def test_get_state_returns_shell_state(self) -> None:
        mgr = PTYShellManager()
        state = mgr.get_state()
        assert isinstance(state, ShellState)
        assert isinstance(state.cwd, str)
        assert isinstance(state.env, dict)
        assert isinstance(state.history, list)

    def test_get_state_cwd_defaults_to_cwd(self) -> None:
        mgr = PTYShellManager()
        state = mgr.get_state()
        assert state.cwd == os.getcwd()

    def test_get_history_returns_empty_list(self) -> None:
        mgr = PTYShellManager()
        assert mgr.get_history() == []

    def test_get_history_returns_copy(self) -> None:
        mgr = PTYShellManager()
        h1 = mgr.get_history()
        h2 = mgr.get_history()
        assert h1 is not h2

    def test_clear_history(self) -> None:
        mgr = PTYShellManager()
        # Manually add to internal history for testing
        mgr._history.append("ls")
        mgr._history.append("pwd")
        assert len(mgr.get_history()) == 2

        mgr.clear_history()
        assert mgr.get_history() == []

    def test_on_subscribes_listener(self) -> None:
        mgr = PTYShellManager()
        events: list[str] = []
        unsub = mgr.on(lambda e, d: events.append(e))
        assert callable(unsub)

        mgr._emit("test.event", {})
        assert len(events) == 1

    def test_on_returns_unsubscribe_fn(self) -> None:
        mgr = PTYShellManager()
        events: list[str] = []
        unsub = mgr.on(lambda e, d: events.append(e))

        mgr._emit("test.event", {})
        assert len(events) == 1

        unsub()
        mgr._emit("test.event", {})
        assert len(events) == 1  # No new event

    def test_double_unsubscribe_safe(self) -> None:
        mgr = PTYShellManager()
        unsub = mgr.on(lambda e, d: None)
        unsub()
        unsub()  # Should not raise (uses discard)

    def test_listener_error_silently_caught(self) -> None:
        mgr = PTYShellManager()

        def bad(e: str, d: dict) -> None:
            raise ValueError("bad listener")

        events: list[str] = []
        mgr.on(bad)
        mgr.on(lambda e, d: events.append(e))

        mgr._emit("test.ev", {})
        assert len(events) == 1


class TestPTYShellManagerDetectShell:
    """Tests for _detect_shell."""

    def test_uses_shell_env_var(self) -> None:
        with patch.dict(os.environ, {"SHELL": "/usr/local/bin/fish"}):
            result = PTYShellManager._detect_shell()
            assert result == "/usr/local/bin/fish"

    def test_fallback_to_bash_on_unix(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("platform.system", return_value="Linux"):
                result = PTYShellManager._detect_shell()
                assert result == "/bin/bash"

    def test_windows_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("platform.system", return_value="Windows"):
                result = PTYShellManager._detect_shell()
                assert result == "cmd.exe"


class TestPTYShellManagerAsync:
    """Tests for async PTYShellManager methods using mocks."""

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self) -> None:
        mgr = PTYShellManager()
        # Should not raise
        await mgr.stop()

    @pytest.mark.asyncio
    async def test_cleanup_clears_listeners(self) -> None:
        mgr = PTYShellManager()
        mgr.on(lambda e, d: None)
        assert len(mgr._listeners) == 1

        await mgr.cleanup()
        assert len(mgr._listeners) == 0

    @pytest.mark.asyncio
    async def test_start_creates_process(self) -> None:
        mgr = PTYShellManager()

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.pid = 42
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()

        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = mock_process
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await mgr.start()

        state = mgr.get_state()
        assert state.is_running is True
        assert state.pid == 42

    @pytest.mark.asyncio
    async def test_start_already_running_noop(self) -> None:
        mgr = PTYShellManager()

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.pid = 99
        mgr._process = mock_process

        # Should return immediately without creating a new process
        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_spawn:
            await mgr.start()
            mock_spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_emits_shell_started_event(self) -> None:
        mgr = PTYShellManager()
        events: list[tuple[str, dict]] = []
        mgr.on(lambda e, d: events.append((e, d)))

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.pid = 55

        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = mock_process
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await mgr.start()

        started_events = [e for e in events if e[0] == "shell.started"]
        assert len(started_events) == 1
        assert started_events[0][1]["pid"] == 55

    @pytest.mark.asyncio
    async def test_start_no_pid_raises(self) -> None:
        mgr = PTYShellManager()

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.pid = None

        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = mock_process
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RuntimeError, match="Failed to start shell"):
                    await mgr.start()


# ======================================================================
# format_shell_state
# ======================================================================


class TestFormatShellState:
    """Tests for format_shell_state."""

    def test_stopped_no_history(self) -> None:
        state = ShellState(cwd="/home/user", env={}, history=[], is_running=False)
        result = format_shell_state(state)
        assert "Stopped" in result
        assert "/home/user" in result
        assert "0 commands" in result

    def test_running_with_pid(self) -> None:
        state = ShellState(
            cwd="/tmp",
            env={},
            history=["ls"],
            is_running=True,
            pid=1234,
        )
        result = format_shell_state(state)
        assert "Running" in result
        assert "1234" in result
        assert "/tmp" in result

    def test_history_shown(self) -> None:
        state = ShellState(
            cwd="/",
            env={},
            history=["ls", "pwd", "echo hi"],
            is_running=False,
        )
        result = format_shell_state(state)
        assert "3 commands" in result
        assert "$ ls" in result
        assert "$ pwd" in result
        assert "$ echo hi" in result

    def test_recent_commands_limited_to_5(self) -> None:
        cmds = [f"cmd{i}" for i in range(10)]
        state = ShellState(cwd="/", env={}, history=cmds, is_running=False)
        result = format_shell_state(state)
        assert "10 commands" in result
        # Only last 5 should appear
        assert "$ cmd5" in result
        assert "$ cmd9" in result
        assert "$ cmd0" not in result
        assert "$ cmd4" not in result

    def test_no_pid_no_parenthetical(self) -> None:
        state = ShellState(cwd="/tmp", env={}, history=[], is_running=False, pid=None)
        result = format_shell_state(state)
        assert "PID:" not in result

    def test_format_contains_shell_label(self) -> None:
        state = ShellState(cwd="/tmp", env={}, history=[], is_running=True, pid=1)
        result = format_shell_state(state)
        assert result.startswith("Shell:")

    def test_format_contains_cwd_label(self) -> None:
        state = ShellState(cwd="/foo/bar", env={}, history=[], is_running=False)
        result = format_shell_state(state)
        assert "CWD: /foo/bar" in result


# ======================================================================
# LSPPosition / LSPRange / LSPLocation / LSPDiagnostic / LSPCompletion
# ======================================================================


class TestLSPPosition:
    """Tests for LSPPosition."""

    def test_construction(self) -> None:
        pos = LSPPosition(line=10, character=5)
        assert pos.line == 10
        assert pos.character == 5

    def test_zero_indexed(self) -> None:
        pos = LSPPosition(line=0, character=0)
        assert pos.line == 0
        assert pos.character == 0


class TestLSPRange:
    """Tests for LSPRange."""

    def test_construction(self) -> None:
        r = LSPRange(
            start=LSPPosition(line=1, character=0),
            end=LSPPosition(line=1, character=10),
        )
        assert r.start.line == 1
        assert r.end.character == 10

    def test_same_line_range(self) -> None:
        r = LSPRange(
            start=LSPPosition(line=5, character=3),
            end=LSPPosition(line=5, character=8),
        )
        assert r.start.line == r.end.line

    def test_multi_line_range(self) -> None:
        r = LSPRange(
            start=LSPPosition(line=1, character=0),
            end=LSPPosition(line=10, character=0),
        )
        assert r.start.line < r.end.line


class TestLSPLocation:
    """Tests for LSPLocation."""

    def test_construction(self) -> None:
        loc = LSPLocation(
            uri="file:///tmp/test.py",
            range=LSPRange(
                start=LSPPosition(line=0, character=0),
                end=LSPPosition(line=0, character=5),
            ),
        )
        assert loc.uri == "file:///tmp/test.py"
        assert loc.range.start.line == 0


class TestLSPDiagnostic:
    """Tests for LSPDiagnostic."""

    def test_construction(self) -> None:
        diag = LSPDiagnostic(
            range=LSPRange(
                start=LSPPosition(line=3, character=0),
                end=LSPPosition(line=3, character=10),
            ),
            message="Undefined variable 'x'",
        )
        assert diag.message == "Undefined variable 'x'"
        assert diag.severity == "error"  # default
        assert diag.source is None
        assert diag.code is None

    def test_custom_severity(self) -> None:
        diag = LSPDiagnostic(
            range=LSPRange(
                start=LSPPosition(line=0, character=0),
                end=LSPPosition(line=0, character=0),
            ),
            message="unused import",
            severity="warning",
            source="pyright",
            code="reportUnusedImport",
        )
        assert diag.severity == "warning"
        assert diag.source == "pyright"
        assert diag.code == "reportUnusedImport"

    def test_numeric_code(self) -> None:
        diag = LSPDiagnostic(
            range=LSPRange(
                start=LSPPosition(line=0, character=0),
                end=LSPPosition(line=0, character=0),
            ),
            message="error",
            code=1234,
        )
        assert diag.code == 1234


class TestLSPCompletion:
    """Tests for LSPCompletion."""

    def test_construction(self) -> None:
        c = LSPCompletion(label="print")
        assert c.label == "print"
        assert c.kind == "text"  # default
        assert c.detail is None
        assert c.documentation is None
        assert c.insert_text is None

    def test_full_completion(self) -> None:
        c = LSPCompletion(
            label="print",
            kind="function",
            detail="print(*objects)",
            documentation="Print objects to the text stream file.",
            insert_text="print($1)",
        )
        assert c.kind == "function"
        assert c.detail == "print(*objects)"
        assert c.documentation is not None
        assert c.insert_text == "print($1)"


# ======================================================================
# LanguageServerConfig
# ======================================================================


class TestLanguageServerConfig:
    """Tests for LanguageServerConfig."""

    def test_construction(self) -> None:
        cfg = LanguageServerConfig(command="pyright-langserver")
        assert cfg.command == "pyright-langserver"
        assert cfg.args == []
        assert cfg.extensions == []
        assert cfg.language_id == ""

    def test_full_construction(self) -> None:
        cfg = LanguageServerConfig(
            command="typescript-language-server",
            args=["--stdio"],
            extensions=[".ts", ".tsx"],
            language_id="typescript",
        )
        assert cfg.args == ["--stdio"]
        assert ".ts" in cfg.extensions
        assert cfg.language_id == "typescript"


# ======================================================================
# LSPConfig
# ======================================================================


class TestLSPConfig:
    """Tests for LSPConfig."""

    def test_defaults(self) -> None:
        cfg = LSPConfig()
        assert cfg.enabled is True
        assert cfg.servers == {}
        assert cfg.auto_detect is True
        assert cfg.timeout == 30.0
        assert cfg.root_uri == ""

    def test_custom_config(self) -> None:
        server = LanguageServerConfig(command="my-lsp")
        cfg = LSPConfig(
            enabled=False,
            servers={"custom": server},
            auto_detect=False,
            timeout=60.0,
            root_uri="file:///workspace",
        )
        assert cfg.enabled is False
        assert "custom" in cfg.servers
        assert cfg.auto_detect is False
        assert cfg.timeout == 60.0


# ======================================================================
# BUILTIN_SERVERS
# ======================================================================


class TestBuiltinServers:
    """Tests for BUILTIN_SERVERS constant."""

    def test_has_typescript(self) -> None:
        assert "typescript" in BUILTIN_SERVERS
        ts = BUILTIN_SERVERS["typescript"]
        assert ts.command == "typescript-language-server"
        assert ".ts" in ts.extensions
        assert ".tsx" in ts.extensions
        assert ".js" in ts.extensions

    def test_has_python(self) -> None:
        assert "python" in BUILTIN_SERVERS
        py = BUILTIN_SERVERS["python"]
        assert py.command == "pyright-langserver"
        assert ".py" in py.extensions
        assert ".pyi" in py.extensions

    def test_has_rust(self) -> None:
        assert "rust" in BUILTIN_SERVERS
        rs = BUILTIN_SERVERS["rust"]
        assert rs.command == "rust-analyzer"
        assert ".rs" in rs.extensions

    def test_has_go(self) -> None:
        assert "go" in BUILTIN_SERVERS
        go = BUILTIN_SERVERS["go"]
        assert go.command == "gopls"
        assert ".go" in go.extensions

    def test_has_json(self) -> None:
        assert "json" in BUILTIN_SERVERS
        j = BUILTIN_SERVERS["json"]
        assert j.command == "vscode-json-language-server"
        assert ".json" in j.extensions
        assert ".jsonc" in j.extensions

    def test_all_have_language_id(self) -> None:
        for lang_id, cfg in BUILTIN_SERVERS.items():
            assert cfg.language_id == lang_id


# ======================================================================
# COMPLETION_KIND_MAP
# ======================================================================


class TestCompletionKindMap:
    """Tests for COMPLETION_KIND_MAP constant."""

    def test_has_expected_mappings(self) -> None:
        assert COMPLETION_KIND_MAP[1] == "text"
        assert COMPLETION_KIND_MAP[2] == "method"
        assert COMPLETION_KIND_MAP[3] == "function"
        assert COMPLETION_KIND_MAP[4] == "constructor"
        assert COMPLETION_KIND_MAP[5] == "field"
        assert COMPLETION_KIND_MAP[6] == "variable"
        assert COMPLETION_KIND_MAP[7] == "class"
        assert COMPLETION_KIND_MAP[8] == "interface"
        assert COMPLETION_KIND_MAP[9] == "module"
        assert COMPLETION_KIND_MAP[10] == "property"
        assert COMPLETION_KIND_MAP[14] == "keyword"
        assert COMPLETION_KIND_MAP[15] == "snippet"

    def test_unknown_kind_not_present(self) -> None:
        assert 999 not in COMPLETION_KIND_MAP


# ======================================================================
# _parse_range (internal helper)
# ======================================================================


class TestParseRange:
    """Tests for _parse_range internal function."""

    def test_valid_range(self) -> None:
        r = _parse_range({
            "start": {"line": 5, "character": 10},
            "end": {"line": 5, "character": 20},
        })
        assert isinstance(r, LSPRange)
        assert r.start.line == 5
        assert r.start.character == 10
        assert r.end.line == 5
        assert r.end.character == 20

    def test_empty_dict_defaults_to_zero(self) -> None:
        r = _parse_range({})
        assert r.start.line == 0
        assert r.start.character == 0
        assert r.end.line == 0
        assert r.end.character == 0

    def test_partial_start_defaults(self) -> None:
        r = _parse_range({"start": {"line": 3}})
        assert r.start.line == 3
        assert r.start.character == 0

    def test_partial_end_defaults(self) -> None:
        r = _parse_range({"end": {"character": 7}})
        assert r.end.line == 0
        assert r.end.character == 7


# ======================================================================
# _LSPClient (internal)
# ======================================================================


class TestLSPClientInit:
    """Tests for _LSPClient construction."""

    def test_construction(self) -> None:
        cfg = LanguageServerConfig(
            command="test-server",
            args=["--stdio"],
            language_id="test",
        )
        client = _LSPClient(cfg, root_uri="file:///workspace")
        assert client.language_id == "test"
        assert client.is_initialized is False

    def test_not_initialized_by_default(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        assert client.is_initialized is False

    @pytest.mark.asyncio
    async def test_get_definition_returns_none_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        result = await client.get_definition("file:///tmp/a.py", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_completions_returns_empty_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        result = await client.get_completions("file:///tmp/a.py", 0, 0)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_hover_returns_none_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        result = await client.get_hover("file:///tmp/a.py", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_references_returns_empty_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        result = await client.get_references("file:///tmp/a.py", 0, 0)
        assert result == []

    def test_notify_document_open_noop_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        # Should not raise
        client.notify_document_open("file:///tmp/a.py", "content")

    def test_notify_document_change_noop_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        client.notify_document_change("file:///tmp/a.py", "content", 2)

    def test_notify_document_close_noop_when_not_initialized(self) -> None:
        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp")
        client.notify_document_close("file:///tmp/a.py")


class TestLSPClientHandleMessage:
    """Tests for _LSPClient._handle_message."""

    def _make_client(self) -> _LSPClient:
        cfg = LanguageServerConfig(command="x", language_id="y")
        return _LSPClient(cfg, root_uri="file:///tmp")

    def test_response_resolves_pending_future(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        future: asyncio.Future = loop.create_future()
        client._pending[1] = future

        client._handle_message({"id": 1, "result": {"key": "value"}})
        assert future.done()
        assert future.result() == {"key": "value"}
        loop.close()

    def test_error_response_sets_exception(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        future: asyncio.Future = loop.create_future()
        client._pending[2] = future

        client._handle_message({
            "id": 2,
            "error": {"message": "Method not found"},
        })
        assert future.done()
        with pytest.raises(RuntimeError, match="Method not found"):
            future.result()
        loop.close()

    def test_unknown_id_ignored(self) -> None:
        client = self._make_client()
        # No pending for id=999
        client._handle_message({"id": 999, "result": None})
        # Should not raise

    def test_notification_with_diagnostics(self) -> None:
        received: list[tuple[str, list]] = []

        def on_diags(uri: str, diags: list[LSPDiagnostic]) -> None:
            received.append((uri, diags))

        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp", on_diagnostics=on_diags)

        client._handle_message({
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": "file:///tmp/test.py",
                "diagnostics": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "message": "undefined name 'x'",
                    "severity": 1,
                    "source": "pyright",
                }],
            },
        })

        assert len(received) == 1
        assert received[0][0] == "file:///tmp/test.py"
        assert len(received[0][1]) == 1
        assert received[0][1][0].message == "undefined name 'x'"
        assert received[0][1][0].severity == "error"
        assert received[0][1][0].source == "pyright"

    def test_notification_diagnostic_severity_mapping(self) -> None:
        received: list[tuple[str, list]] = []

        def on_diags(uri: str, diags: list[LSPDiagnostic]) -> None:
            received.append((uri, diags))

        cfg = LanguageServerConfig(command="x", language_id="y")
        client = _LSPClient(cfg, root_uri="file:///tmp", on_diagnostics=on_diags)

        client._handle_message({
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": "file:///tmp/t.py",
                "diagnostics": [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "message": "e1", "severity": 1},
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "message": "w1", "severity": 2},
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "message": "i1", "severity": 3},
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "message": "h1", "severity": 4},
                ],
            },
        })

        diags = received[0][1]
        assert diags[0].severity == "error"
        assert diags[1].severity == "warning"
        assert diags[2].severity == "information"
        assert diags[3].severity == "hint"

    def test_already_done_future_not_overwritten(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        future: asyncio.Future = loop.create_future()
        future.set_result("already done")
        client._pending[3] = future

        # Should not raise even though future is already resolved
        client._handle_message({"id": 3, "result": "new value"})
        assert future.result() == "already done"
        loop.close()


class TestLSPClientProcessBuffer:
    """Tests for _LSPClient._process_buffer."""

    def _make_client(self) -> _LSPClient:
        cfg = LanguageServerConfig(command="x", language_id="y")
        return _LSPClient(cfg, root_uri="file:///tmp")

    def test_parses_complete_message(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        future: asyncio.Future = loop.create_future()
        client._pending[1] = future

        content = json.dumps({"id": 1, "result": "ok"}).encode()
        header = f"Content-Length: {len(content)}\r\n\r\n".encode()
        client._buffer = header + content

        client._process_buffer()
        assert future.done()
        assert future.result() == "ok"
        loop.close()

    def test_incomplete_message_waits(self) -> None:
        client = self._make_client()
        content = json.dumps({"id": 1, "result": "ok"}).encode()
        header = f"Content-Length: {len(content)}\r\n\r\n".encode()
        # Only provide partial content
        client._buffer = header + content[:5]

        client._process_buffer()
        # Should not have processed anything; buffer still has data
        assert len(client._buffer) > 0

    def test_no_header_clears_garbage(self) -> None:
        client = self._make_client()
        # No Content-Length header, just data with \r\n\r\n separator
        client._buffer = b"Garbage-Header: true\r\n\r\nsome content"
        client._process_buffer()
        # Should skip past the header since no Content-Length match

    def test_multiple_messages_in_buffer(self) -> None:
        client = self._make_client()
        loop = asyncio.new_event_loop()
        f1: asyncio.Future = loop.create_future()
        f2: asyncio.Future = loop.create_future()
        client._pending[1] = f1
        client._pending[2] = f2

        msg1 = json.dumps({"id": 1, "result": "first"}).encode()
        msg2 = json.dumps({"id": 2, "result": "second"}).encode()
        client._buffer = (
            f"Content-Length: {len(msg1)}\r\n\r\n".encode() + msg1
            + f"Content-Length: {len(msg2)}\r\n\r\n".encode() + msg2
        )

        client._process_buffer()
        assert f1.result() == "first"
        assert f2.result() == "second"
        loop.close()


# ======================================================================
# LSPManager
# ======================================================================


class TestLSPManagerInit:
    """Tests for LSPManager construction."""

    def test_default_construction(self) -> None:
        mgr = LSPManager()
        assert mgr.get_active_servers() == []

    def test_custom_config(self) -> None:
        cfg = LSPConfig(enabled=False, timeout=60.0)
        mgr = LSPManager(config=cfg)
        assert mgr._enabled is False
        assert mgr._timeout == 60.0

    def test_get_active_servers_empty_initially(self) -> None:
        mgr = LSPManager()
        assert mgr.get_active_servers() == []

    def test_is_server_running_false_initially(self) -> None:
        mgr = LSPManager()
        assert mgr.is_server_running("typescript") is False
        assert mgr.is_server_running("python") is False
        assert mgr.is_server_running("nonexistent") is False


class TestLSPManagerEvents:
    """Tests for LSPManager event subscription."""

    def test_on_subscribes_returns_unsubscribe(self) -> None:
        mgr = LSPManager()
        events: list[str] = []
        unsub = mgr.on(lambda e, d: events.append(e))
        assert callable(unsub)

        mgr._emit("test.event", {})
        assert len(events) == 1

    def test_unsubscribe_removes_listener(self) -> None:
        mgr = LSPManager()
        events: list[str] = []
        unsub = mgr.on(lambda e, d: events.append(e))

        mgr._emit("test.event", {})
        assert len(events) == 1

        unsub()
        mgr._emit("test.event", {})
        assert len(events) == 1

    def test_listener_error_silently_caught(self) -> None:
        mgr = LSPManager()

        def bad(e: str, d: dict) -> None:
            raise ValueError("oops")

        events: list[str] = []
        mgr.on(bad)
        mgr.on(lambda e, d: events.append(e))

        mgr._emit("test.event", {})
        assert len(events) == 1


class TestLSPManagerHelpers:
    """Tests for LSPManager internal helpers."""

    def test_to_uri_with_file_path(self) -> None:
        result = LSPManager._to_uri("/tmp/test.py")
        assert result == "file:///tmp/test.py"

    def test_to_uri_already_uri(self) -> None:
        result = LSPManager._to_uri("file:///tmp/test.py")
        assert result == "file:///tmp/test.py"

    def test_get_client_for_file_no_matching_extension(self) -> None:
        mgr = LSPManager()
        client = mgr._get_client_for_file("test.unknown")
        assert client is None

    def test_get_client_for_file_not_started(self) -> None:
        mgr = LSPManager()
        # .py matches python, but no client started
        client = mgr._get_client_for_file("test.py")
        assert client is None

    def test_detect_languages_with_pyproject(self, tmp_path: Any) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "python" in result

    def test_detect_languages_with_tsconfig(self, tmp_path: Any) -> None:
        (tmp_path / "tsconfig.json").write_text("{}")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "typescript" in result

    def test_detect_languages_with_cargo(self, tmp_path: Any) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "rust" in result

    def test_detect_languages_with_go_mod(self, tmp_path: Any) -> None:
        (tmp_path / "go.mod").write_text("module test")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "go" in result

    def test_detect_languages_with_package_json(self, tmp_path: Any) -> None:
        (tmp_path / "package.json").write_text("{}")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "typescript" in result

    def test_detect_languages_with_requirements_txt(self, tmp_path: Any) -> None:
        (tmp_path / "requirements.txt").write_text("pytest")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "python" in result

    def test_detect_languages_empty_dir(self, tmp_path: Any) -> None:
        result = LSPManager._detect_languages(str(tmp_path))
        assert result == []

    def test_detect_languages_multiple(self, tmp_path: Any) -> None:
        (tmp_path / "pyproject.toml").write_text("")
        (tmp_path / "tsconfig.json").write_text("")
        result = LSPManager._detect_languages(str(tmp_path))
        assert "python" in result
        assert "typescript" in result

    def test_custom_servers_merged_with_builtin(self) -> None:
        custom = LanguageServerConfig(
            command="my-lsp",
            language_id="custom",
            extensions=[".custom"],
        )
        cfg = LSPConfig(servers={"custom": custom})
        mgr = LSPManager(config=cfg)
        assert "custom" in mgr._servers
        assert "typescript" in mgr._servers  # builtin still present


class TestLSPManagerAsync:
    """Tests for async LSPManager methods."""

    @pytest.mark.asyncio
    async def test_start_server_unknown_language_raises(self) -> None:
        mgr = LSPManager()
        with pytest.raises(ValueError, match="No server configuration"):
            await mgr.start_server("klingon")

    @pytest.mark.asyncio
    async def test_start_server_missing_binary_raises(self) -> None:
        mgr = LSPManager()
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Language server not found"):
                await mgr.start_server("python")

    @pytest.mark.asyncio
    async def test_stop_server_not_started_noop(self) -> None:
        mgr = LSPManager()
        await mgr.stop_server("python")  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_all_empty_noop(self) -> None:
        mgr = LSPManager()
        await mgr.stop_all()  # Should not raise

    @pytest.mark.asyncio
    async def test_cleanup_clears_all(self) -> None:
        mgr = LSPManager()
        mgr.on(lambda e, d: None)
        assert len(mgr._listeners) == 1

        await mgr.cleanup()
        assert len(mgr._listeners) == 0
        assert mgr._diagnostics_cache == {}

    @pytest.mark.asyncio
    async def test_get_definition_no_client_returns_none(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_definition("test.py", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_completions_no_client_returns_empty(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_completions("test.py", 0, 0)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_hover_no_client_returns_none(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_hover("test.py", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_references_no_client_returns_empty(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_references("test.py", 0, 0)
        assert result == []

    def test_get_diagnostics_no_cache_returns_empty(self) -> None:
        mgr = LSPManager()
        result = mgr.get_diagnostics("test.py")
        assert result == []

    def test_get_diagnostics_from_cache(self) -> None:
        mgr = LSPManager()
        diag = LSPDiagnostic(
            range=LSPRange(
                start=LSPPosition(line=0, character=0),
                end=LSPPosition(line=0, character=5),
            ),
            message="error here",
        )
        uri = f"file://{os.path.abspath('test.py')}"
        mgr._diagnostics_cache[uri] = [diag]
        result = mgr.get_diagnostics("test.py")
        assert len(result) == 1
        assert result[0].message == "error here"

    def test_notify_file_opened_no_client_noop(self) -> None:
        mgr = LSPManager()
        # Should not raise
        mgr.notify_file_opened("test.py", "content")

    def test_notify_file_changed_no_client_noop(self) -> None:
        mgr = LSPManager()
        mgr.notify_file_changed("test.py", "new content")

    def test_notify_file_closed_no_client_noop(self) -> None:
        mgr = LSPManager()
        mgr.notify_file_closed("test.py")

    @pytest.mark.asyncio
    async def test_auto_start_disabled_returns_empty(self) -> None:
        cfg = LSPConfig(enabled=False)
        mgr = LSPManager(config=cfg)
        result = await mgr.auto_start("/tmp")
        assert result == []

    @pytest.mark.asyncio
    async def test_auto_start_no_auto_detect_returns_empty(self) -> None:
        cfg = LSPConfig(auto_detect=False)
        mgr = LSPManager(config=cfg)
        result = await mgr.auto_start("/tmp")
        assert result == []

    @pytest.mark.asyncio
    async def test_start_server_already_started_noop(self) -> None:
        mgr = LSPManager()
        # Manually put a client in
        cfg = LanguageServerConfig(command="x", language_id="python")
        mock_client = _LSPClient(cfg, root_uri="file:///tmp")
        mgr._clients["python"] = mock_client

        # Should return without trying to start again
        with patch("shutil.which", return_value="/usr/bin/pyright-langserver"):
            await mgr.start_server("python")

    @pytest.mark.asyncio
    async def test_get_definition_unknown_extension_returns_none(self) -> None:
        mgr = LSPManager()
        result = await mgr.get_definition("test.xyz", 0, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_stop_server_emits_event(self) -> None:
        mgr = LSPManager()
        events: list[tuple[str, dict]] = []
        mgr.on(lambda e, d: events.append((e, d)))

        cfg = LanguageServerConfig(command="x", language_id="python")
        mock_client = MagicMock(spec=_LSPClient)
        mock_client.stop = AsyncMock()
        mgr._clients["python"] = mock_client

        await mgr.stop_server("python")

        stopped_events = [e for e in events if e[0] == "lsp.stopped"]
        assert len(stopped_events) == 1
        assert stopped_events[0][1]["language_id"] == "python"
