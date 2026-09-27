"""Tests for AnthropicProvider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from attocode.errors import ProviderError
from attocode.providers.anthropic import AnthropicProvider
from attocode.providers.base import get_model_pricing
from attocode.types.messages import (
    ChatOptions,
    Message,
    Role,
    StopReason,
    ToolCall,
    ToolDefinition,
)

MOCK_URL = "https://api.anthropic.com/v1/messages"
MOCK_REQUEST = httpx.Request("POST", MOCK_URL)


def _mock_response(status: int = 200, **kwargs) -> httpx.Response:
    """Create a mock httpx response with request set."""
    resp = httpx.Response(status, request=MOCK_REQUEST, **kwargs)
    return resp


@pytest.fixture
def provider() -> AnthropicProvider:
    return AnthropicProvider(api_key="sk-test")


class TestAnthropicProviderInit:
    def test_name(self, provider: AnthropicProvider) -> None:
        assert provider.name == "anthropic"

    def test_no_api_key(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"),
        ):
            AnthropicProvider()


class TestAnthropicChat:
    @pytest.mark.asyncio
    async def test_basic_chat(self, provider: AnthropicProvider) -> None:
        mock_response = _mock_response(json={
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })
        provider._client.post = AsyncMock(return_value=mock_response)

        msgs = [Message(role=Role.USER, content="Hi")]
        resp = await provider.chat(msgs)

        assert resp.content == "Hello!"
        assert resp.stop_reason == StopReason.END_TURN
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5

    @pytest.mark.asyncio
    async def test_tool_use_response(self, provider: AnthropicProvider) -> None:
        mock_response = _mock_response(json={
            "content": [
                {"type": "text", "text": "Let me check"},
                {"type": "tool_use", "id": "tc_1", "name": "read_file", "input": {"path": "foo.py"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 20, "output_tokens": 15},
        })
        provider._client.post = AsyncMock(return_value=mock_response)

        msgs = [Message(role=Role.USER, content="read foo.py")]
        resp = await provider.chat(msgs)

        assert resp.content == "Let me check"
        assert resp.has_tool_calls
        assert resp.tool_calls[0].name == "read_file"
        assert resp.tool_calls[0].arguments == {"path": "foo.py"}
        assert resp.stop_reason == StopReason.TOOL_USE

    @pytest.mark.asyncio
    async def test_thinking_response(self, provider: AnthropicProvider) -> None:
        mock_response = _mock_response(json={
            "content": [
                {"type": "thinking", "thinking": "Let me think about this..."},
                {"type": "text", "text": "The answer is 42"},
            ],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 30, "output_tokens": 20},
        })
        provider._client.post = AsyncMock(return_value=mock_response)

        msgs = [Message(role=Role.USER, content="What is 6*7?")]
        resp = await provider.chat(msgs)

        assert resp.content == "The answer is 42"
        assert resp.thinking == "Let me think about this..."

    @pytest.mark.asyncio
    async def test_empty_choices(self, provider: AnthropicProvider) -> None:
        mock_response = _mock_response(json={"content": [], "stop_reason": "end_turn", "usage": {}})
        provider._client.post = AsyncMock(return_value=mock_response)

        msgs = [Message(role=Role.USER, content="hi")]
        resp = await provider.chat(msgs)
        assert resp.content == ""

    @pytest.mark.asyncio
    async def test_cost_calculation(self, provider: AnthropicProvider) -> None:
        model = "claude-sonnet-5"
        mock_response = _mock_response(json={
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        })
        provider._client.post = AsyncMock(return_value=mock_response)

        msgs = [Message(role=Role.USER, content="hi")]
        opts = ChatOptions(model=model)
        resp = await provider.chat(msgs, opts)

        pricing = get_model_pricing(model)
        expected_cost = pricing.estimate_cost(1000, 500)
        assert abs(resp.usage.cost - expected_cost) < 1e-9

    @pytest.mark.asyncio
    async def test_cache_tokens(self, provider: AnthropicProvider) -> None:
        mock_response = _mock_response(json={
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 80,
                "cache_creation_input_tokens": 20,
            },
        })
        provider._client.post = AsyncMock(return_value=mock_response)

        msgs = [Message(role=Role.USER, content="hi")]
        resp = await provider.chat(msgs)
        assert resp.usage.cache_read_tokens == 80
        assert resp.usage.cache_creation_tokens == 20  # maps from cache_creation_input_tokens


class TestAnthropicFormatting:
    @pytest.mark.asyncio
    async def test_system_message_extraction(self, provider: AnthropicProvider) -> None:
        mock_response = _mock_response(json={
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {},
        })
        provider._client.post = AsyncMock(return_value=mock_response)

        msgs = [
            Message(role=Role.SYSTEM, content="You are helpful"),
            Message(role=Role.USER, content="hello"),
        ]
        await provider.chat(msgs)

        # Verify the call was made with system extracted
        call_args = provider._client.post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert body["system"] == "You are helpful"
        # User messages should not include system
        assert all(m.get("role") != "system" for m in body["messages"])

    @pytest.mark.asyncio
    async def test_tool_result_formatting(self, provider: AnthropicProvider) -> None:
        mock_response = _mock_response(json={
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {},
        })
        provider._client.post = AsyncMock(return_value=mock_response)

        msgs = [
            Message(role=Role.USER, content="read foo"),
            Message(role=Role.ASSISTANT, content="reading", tool_calls=[
                ToolCall(id="tc_1", name="read_file", arguments={"path": "foo.py"})
            ]),
            Message(role=Role.TOOL, content="file content here", tool_call_id="tc_1"),
        ]
        await provider.chat(msgs)

        call_args = provider._client.post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        # Tool result should be formatted as user message with tool_result block
        tool_msg = [m for m in body["messages"] if m.get("role") == "user" and isinstance(m.get("content"), list)]
        assert len(tool_msg) == 1
        assert tool_msg[0]["content"][0]["type"] == "tool_result"

    @pytest.mark.asyncio
    async def test_tool_definition_format(self, provider: AnthropicProvider) -> None:
        mock_response = _mock_response(json={
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {},
        })
        provider._client.post = AsyncMock(return_value=mock_response)

        tool_def = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
        )
        msgs = [Message(role=Role.USER, content="hi")]
        await provider.chat(msgs, ChatOptions(tools=[tool_def]))

        call_args = provider._client.post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "tools" in body
        assert body["tools"][0]["name"] == "test_tool"
        assert body["tools"][0]["input_schema"]["type"] == "object"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("model", "sends_temperature", "adaptive"),
        [
            ("claude-sonnet-4-6", True, False),
            ("claude-sonnet-5", False, True),
            ("claude-opus-5", False, True),
            ("claude-opus-5-5", False, True),
            ("claude-fable-5-1", False, True),
        ],
    )
    async def test_model_request_rules(
        self, provider: AnthropicProvider, model: str, sends_temperature: bool, adaptive: bool,
    ) -> None:
        provider._client.post = AsyncMock(return_value=_mock_response(json={
            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "usage": {},
        }))
        await provider.chat([Message(role=Role.USER, content="hi")], ChatOptions(model=model, temperature=0.0))
        body = provider._client.post.call_args.kwargs["json"]
        assert ("temperature" in body) is sends_temperature
        assert (body.get("thinking", {}).get("type") == "adaptive") is adaptive
        assert (body.get("output_config") == {"effort": "low"}) is adaptive

    def test_trailing_assistant_turn_gets_user_continuation(self, provider: AnthropicProvider) -> None:
        formatted = provider._format_messages([
            Message(role=Role.USER, content="write a long essay"),
            Message(role=Role.ASSISTANT, content="Part one"),
        ])
        assert formatted[-2] == {"role": "assistant", "content": "Part one"}
        assert formatted[-1]["role"] == "user"


THINKING_TURN = [
    {"type": "thinking", "thinking": "plan", "signature": "sig-1"},
    {"type": "text", "text": "Let me check"},
    {"type": "tool_use", "id": "tc_1", "name": "read_file", "input": {"path": "foo.py"}},
]


def _history(raw_content: list[dict]) -> list[Message]:
    return [
        Message(role=Role.USER, content="read foo"),
        Message(
            role=Role.ASSISTANT, content="Let me check",
            tool_calls=[ToolCall(id="tc_1", name="read_file", arguments={"path": "foo.py"})],
            metadata={"raw_content": raw_content},
        ),
        Message(role=Role.TOOL, content="file content", tool_call_id="tc_1"),
    ]


class TestAnthropicThinkingRoundTrip:
    @pytest.mark.asyncio
    async def test_thinking_blocks_go_back_unchanged(self, provider: AnthropicProvider) -> None:
        provider._client.post = AsyncMock(return_value=_mock_response(json={
            "content": THINKING_TURN, "stop_reason": "tool_use", "usage": {},
        }))
        resp = await provider.chat([Message(role=Role.USER, content="read foo")])
        assert resp.raw_content == THINKING_TURN

        await provider.chat(_history(resp.raw_content))
        sent = provider._client.post.call_args.kwargs["json"]["messages"]
        assert sent[1] == {"role": "assistant", "content": THINKING_TURN}

    def test_raw_blocks_dropped_when_tool_calls_changed(self, provider: AnthropicProvider) -> None:
        msgs = _history(THINKING_TURN)
        msgs[1].tool_calls = [ToolCall(id="tc_other", name="read_file", arguments={})]
        formatted = provider._format_messages(msgs)
        assert [b["type"] for b in formatted[1]["content"]] == ["text", "tool_use"]

    @pytest.mark.asyncio
    async def test_rejected_signature_strips_thinking_and_retries(self, provider: AnthropicProvider) -> None:
        rejected = _mock_response(400, text=(
            "messages.1.content.0: Invalid `signature` in `thinking` block. "
            "The block is bound to a different conversation."
        ))
        ok = _mock_response(json={"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "usage": {}})
        provider._client.post = AsyncMock(side_effect=[rejected, ok])

        msgs = _history(THINKING_TURN)
        resp = await provider.chat(msgs)

        assert resp.content == "ok"
        retry = provider._client.post.call_args_list[1].kwargs["json"]["messages"]
        assert [b["type"] for b in retry[1]["content"]] == ["text", "tool_use"]
        assert "raw_content" not in msgs[1].metadata  # later requests skip the rejected blocks too

    @pytest.mark.asyncio
    async def test_stream_rebuilds_blocks_with_signature(self) -> None:
        import json

        from attocode.integrations.streaming.handler import adapt_anthropic_stream
        from attocode.types.messages import StreamChunkType

        events = [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "pl"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "an"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig-1"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Let me check"}},
            {"type": "content_block_stop", "index": 1},
            {"type": "content_block_start", "index": 2, "content_block": {
                "type": "tool_use", "id": "tc_1", "name": "read_file", "input": {}}},
            {"type": "content_block_delta", "index": 2, "delta": {
                "type": "input_json_delta", "partial_json": '{"path": "foo.py"}'}},
            {"type": "content_block_stop", "index": 2},
            {"type": "message_stop"},
        ]

        async def lines():
            for e in events:
                yield f"data: {json.dumps(e)}"

        chunks = [c async for c in adapt_anthropic_stream(lines())]
        blocks = next(c.blocks for c in chunks if c.type == StreamChunkType.CONTENT_BLOCKS)
        assert blocks == THINKING_TURN


class TestAnthropicErrors:
    @pytest.mark.asyncio
    async def test_rate_limit_error(self, provider: AnthropicProvider) -> None:
        mock_response = httpx.Response(429, text="Rate limited")
        mock_response.request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        provider._client.post = AsyncMock(side_effect=httpx.HTTPStatusError("429", request=mock_response.request, response=mock_response))

        with pytest.raises(ProviderError) as exc_info:
            await provider.chat([Message(role=Role.USER, content="hi")])
        assert exc_info.value.retryable
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_server_error_retryable(self, provider: AnthropicProvider) -> None:
        for status in (500, 502, 503, 529):
            mock_response = httpx.Response(status, text="Server error")
            mock_response.request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            provider._client.post = AsyncMock(
                side_effect=httpx.HTTPStatusError(str(status), request=mock_response.request, response=mock_response)
            )

            with pytest.raises(ProviderError) as exc_info:
                await provider.chat([Message(role=Role.USER, content="hi")])
            assert exc_info.value.retryable, f"Status {status} should be retryable"

    @pytest.mark.asyncio
    async def test_auth_error_not_retryable(self, provider: AnthropicProvider) -> None:
        mock_response = httpx.Response(401, text="Unauthorized")
        mock_response.request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        provider._client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError("401", request=mock_response.request, response=mock_response)
        )

        with pytest.raises(ProviderError) as exc_info:
            await provider.chat([Message(role=Role.USER, content="hi")])
        assert not exc_info.value.retryable

    @pytest.mark.asyncio
    async def test_timeout_error(self, provider: AnthropicProvider) -> None:
        provider._client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with pytest.raises(ProviderError) as exc_info:
            await provider.chat([Message(role=Role.USER, content="hi")])
        assert exc_info.value.retryable

    @pytest.mark.asyncio
    async def test_network_error(self, provider: AnthropicProvider) -> None:
        provider._client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with pytest.raises(ProviderError) as exc_info:
            await provider.chat([Message(role=Role.USER, content="hi")])
        assert exc_info.value.retryable


class TestAnthropicClose:
    @pytest.mark.asyncio
    async def test_close(self, provider: AnthropicProvider) -> None:
        provider._client.aclose = AsyncMock()
        await provider.close()
        provider._client.aclose.assert_called_once()
