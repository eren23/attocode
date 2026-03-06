"""Tests for MockProvider."""

from __future__ import annotations

import pytest

from attocode.providers.mock import MockProvider
from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    Message,
    Role,
    StopReason,
    StreamChunkType,
    TokenUsage,
    ToolCall,
)


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


class TestMockProviderBasic:
    @pytest.mark.asyncio
    async def test_default_response(self, mock_provider: MockProvider) -> None:
        msgs = [Message(role=Role.USER, content="hello")]
        resp = await mock_provider.chat(msgs)
        assert resp.content == "Mock response"
        assert resp.stop_reason == StopReason.END_TURN

    @pytest.mark.asyncio
    async def test_name(self, mock_provider: MockProvider) -> None:
        assert mock_provider.name == "mock"

    @pytest.mark.asyncio
    async def test_call_count(self, mock_provider: MockProvider) -> None:
        assert mock_provider.call_count == 0
        msgs = [Message(role=Role.USER, content="hi")]
        await mock_provider.chat(msgs)
        assert mock_provider.call_count == 1
        await mock_provider.chat(msgs)
        assert mock_provider.call_count == 2

    @pytest.mark.asyncio
    async def test_call_history(self, mock_provider: MockProvider) -> None:
        msgs = [Message(role=Role.USER, content="test")]
        opts = ChatOptions(model="test-model")
        await mock_provider.chat(msgs, opts)
        assert len(mock_provider.call_history) == 1
        assert mock_provider.call_history[0][0] == msgs
        assert mock_provider.call_history[0][1] == opts


class TestMockProviderResponses:
    @pytest.mark.asyncio
    async def test_queued_responses(self) -> None:
        provider = MockProvider()
        provider.add_response(content="first")
        provider.add_response(content="second")
        msgs = [Message(role=Role.USER, content="hi")]
        r1 = await provider.chat(msgs)
        r2 = await provider.chat(msgs)
        r3 = await provider.chat(msgs)
        assert r1.content == "first"
        assert r2.content == "second"
        assert r3.content == "Mock response"  # falls back to default

    @pytest.mark.asyncio
    async def test_add_tool_response(self) -> None:
        provider = MockProvider()
        tc = ToolCall(id="tc1", name="bash", arguments={"command": "ls"})
        provider.add_tool_response([tc], content="running command")
        msgs = [Message(role=Role.USER, content="run ls")]
        resp = await provider.chat(msgs)
        assert resp.has_tool_calls
        assert resp.tool_calls[0].name == "bash"
        assert resp.stop_reason == StopReason.TOOL_USE

    @pytest.mark.asyncio
    async def test_chained_add(self) -> None:
        provider = MockProvider()
        result = provider.add_response(content="a").add_response(content="b")
        assert result is provider
        assert len(provider.responses) == 2

    @pytest.mark.asyncio
    async def test_response_fn(self) -> None:
        async def custom_fn(msgs, opts):
            return ChatResponse(
                content=f"Got {len(msgs)} messages",
                stop_reason=StopReason.END_TURN,
            )

        provider = MockProvider(response_fn=custom_fn)
        msgs = [Message(role=Role.USER, content="hi")]
        resp = await provider.chat(msgs)
        assert resp.content == "Got 1 messages"

    @pytest.mark.asyncio
    async def test_response_fn_takes_priority(self) -> None:
        async def custom_fn(msgs, opts):
            return ChatResponse(content="custom", stop_reason=StopReason.END_TURN)

        provider = MockProvider(response_fn=custom_fn)
        provider.add_response(content="queued")
        msgs = [Message(role=Role.USER, content="hi")]
        resp = await provider.chat(msgs)
        assert resp.content == "custom"  # fn takes priority over queue


class TestMockProviderStream:
    @pytest.mark.asyncio
    async def test_stream_text(self) -> None:
        provider = MockProvider()
        provider.add_response(content="hello world")
        msgs = [Message(role=Role.USER, content="hi")]
        chunks = []
        async for chunk in provider.stream(msgs):
            chunks.append(chunk)
        assert any(c.type == StreamChunkType.TEXT for c in chunks)
        assert chunks[-1].type == StreamChunkType.DONE

    @pytest.mark.asyncio
    async def test_stream_tool_calls(self) -> None:
        provider = MockProvider()
        tc = ToolCall(id="tc1", name="bash", arguments={})
        provider.add_tool_response([tc])
        msgs = [Message(role=Role.USER, content="run")]
        chunks = []
        async for chunk in provider.stream(msgs):
            chunks.append(chunk)
        types = [c.type for c in chunks]
        assert StreamChunkType.TOOL_CALL in types
        assert StreamChunkType.DONE in types


class TestMockProviderReset:
    @pytest.mark.asyncio
    async def test_reset(self) -> None:
        provider = MockProvider()
        provider.add_response(content="first")
        msgs = [Message(role=Role.USER, content="hi")]
        await provider.chat(msgs)
        assert provider.call_count == 1

        provider.reset()
        assert provider.call_count == 0
        # After reset, index is back to 0, so queued response is available again
        resp = await provider.chat(msgs)
        assert resp.content == "first"
