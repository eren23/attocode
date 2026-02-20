"""Mock LLM provider for testing."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    Message,
    MessageWithStructuredContent,
    StopReason,
    StreamChunk,
    StreamChunkType,
    TokenUsage,
    ToolCall,
)


@dataclass
class MockProvider:
    """Mock LLM provider for testing."""

    responses: list[ChatResponse] = field(default_factory=list)
    response_fn: Callable[
        [list[Message | MessageWithStructuredContent], ChatOptions | None],
        Awaitable[ChatResponse],
    ] | None = None
    default_response: ChatResponse = field(
        default_factory=lambda: ChatResponse(
            content="Mock response",
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
    )
    call_history: list[
        tuple[list[Message | MessageWithStructuredContent], ChatOptions | None]
    ] = field(default_factory=list)
    _response_index: int = field(default=0, init=False)

    @property
    def name(self) -> str:
        return "mock"

    @property
    def call_count(self) -> int:
        return len(self.call_history)

    async def chat(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> ChatResponse:
        self.call_history.append((messages, options))
        if self.response_fn is not None:
            return await self.response_fn(messages, options)
        if self._response_index < len(self.responses):
            resp = self.responses[self._response_index]
            self._response_index += 1
            return resp
        return self.default_response

    async def stream(
        self,
        messages: list[Message],
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        resp = await self.chat(messages, options)
        if resp.content:
            yield StreamChunk(type=StreamChunkType.TEXT, content=resp.content)
        if resp.tool_calls:
            for tc in resp.tool_calls:
                yield StreamChunk(type=StreamChunkType.TOOL_CALL, tool_call=tc)
        yield StreamChunk(type=StreamChunkType.DONE)

    def add_response(
        self,
        content: str = "",
        tool_calls: list[ToolCall] | None = None,
        stop_reason: StopReason = StopReason.END_TURN,
        usage: TokenUsage | None = None,
        thinking: str | None = None,
    ) -> MockProvider:
        self.responses.append(
            ChatResponse(
                content=content,
                tool_calls=tool_calls,
                stop_reason=stop_reason,
                usage=usage or TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
                thinking=thinking,
            )
        )
        return self

    def add_tool_response(self, tool_calls: list[ToolCall], content: str = "") -> MockProvider:
        return self.add_response(content=content, tool_calls=tool_calls, stop_reason=StopReason.TOOL_USE)

    def reset(self) -> None:
        self.call_history.clear()
        self._response_index = 0

    async def close(self) -> None:
        """No-op for mock provider."""
