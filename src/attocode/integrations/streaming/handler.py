"""Streaming response handler.

Processes streaming LLM responses, accumulating text chunks,
tool calls, and usage data into a final ChatResponse.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from attocode.types.messages import (
    ChatResponse,
    StreamChunk,
    StreamChunkType,
    TokenUsage,
    ToolCall,
)

# =============================================================================
# Types
# =============================================================================


@dataclass
class StreamConfig:
    """Streaming configuration."""

    enabled: bool = True
    buffer_size: int = 50  # Chars before flushing
    show_typing_indicator: bool = True


@dataclass
class _StreamState:
    """Internal accumulator for stream processing."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    current_tool_call: dict[str, Any] | None = None
    usage: TokenUsage | None = None


StreamEventListener = Callable[[str, dict[str, Any]], None]
StreamCallback = Callable[[StreamChunk], None]


# =============================================================================
# Stream Handler
# =============================================================================


class StreamHandler:
    """Handles streaming responses from LLM providers.

    Accumulates chunks into a final ChatResponse, with buffered
    text emission and tool call assembly.
    """

    def __init__(self, config: StreamConfig | None = None) -> None:
        self._config = config or StreamConfig()
        self._listeners: list[StreamEventListener] = []
        self._buffer: str = ""

    async def process_stream(
        self,
        stream: AsyncIterator[StreamChunk],
        on_chunk: StreamCallback | None = None,
    ) -> ChatResponse:
        """Process a streaming response into a final ChatResponse."""
        state = _StreamState()
        self._emit("stream.start", {})

        try:
            async for chunk in stream:
                self._process_chunk(chunk, state, on_chunk)
        except Exception as exc:
            self._emit("stream.error", {"error": str(exc)})
            raise

        # Flush remaining buffer
        if self._buffer:
            self._emit("stream.text", {"content": self._buffer})
            self._buffer = ""

        response = ChatResponse(
            content=state.content,
            tool_calls=state.tool_calls if state.tool_calls else None,
            usage=state.usage,
        )
        self._emit("stream.complete", {"response": response})
        return response

    def _process_chunk(
        self,
        chunk: StreamChunk,
        state: _StreamState,
        on_chunk: StreamCallback | None,
    ) -> None:
        """Process a single stream chunk."""
        match chunk.type:
            case StreamChunkType.TEXT:
                if chunk.content:
                    state.content += chunk.content
                    self._buffer += chunk.content
                    if len(self._buffer) >= self._config.buffer_size:
                        self._emit("stream.text", {"content": self._buffer})
                        self._buffer = ""

            case StreamChunkType.THINKING:
                if chunk.content:
                    self._emit("stream.thinking", {"content": chunk.content})

            case StreamChunkType.TOOL_CALL:
                if chunk.tool_call:
                    state.tool_calls.append(chunk.tool_call)
                    self._emit(
                        "stream.tool_call", {"tool_call": chunk.tool_call}
                    )

            case StreamChunkType.USAGE:
                if chunk.usage:
                    state.usage = chunk.usage

            case StreamChunkType.ERROR:
                if chunk.error:
                    self._emit("stream.error", {"error": chunk.error})

            case StreamChunkType.DONE:
                if self._buffer:
                    self._emit("stream.text", {"content": self._buffer})
                    self._buffer = ""

        if on_chunk:
            on_chunk(chunk)

    def on(self, listener: StreamEventListener) -> Callable[[], None]:
        """Subscribe to stream events. Returns unsubscribe function."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def is_enabled(self) -> bool:
        """Check if streaming is enabled."""
        return self._config.enabled

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass


# =============================================================================
# SSE Adapters
# =============================================================================


async def adapt_openrouter_stream(
    lines: AsyncIterator[str],
) -> AsyncIterator[StreamChunk]:
    """Convert OpenRouter/OpenAI SSE lines to StreamChunk iterator.

    Expects lines from an httpx streaming response (response.aiter_lines()).
    Accumulates tool call deltas across chunks (name and arguments may
    arrive in separate SSE events) before yielding complete ToolCalls.
    """
    import json

    # Accumulate tool call deltas by index across SSE chunks.
    # Each entry tracks: id, name, and an arguments buffer.
    pending_tool_calls: dict[int, dict[str, Any]] = {}

    def _flush_tool_calls() -> list[StreamChunk]:
        """Yield StreamChunks for all accumulated tool calls and clear state."""
        chunks: list[StreamChunk] = []
        for _idx in sorted(pending_tool_calls):
            tc = pending_tool_calls[_idx]
            name = tc.get("name", "")
            if not name:
                continue
            args_str = tc.get("arguments", "")
            parse_error = None
            try:
                args = json.loads(args_str) if args_str else {}
            except (json.JSONDecodeError, TypeError) as exc:
                args = {}
                parse_error = f"Failed to parse arguments: {exc}. Raw: {str(args_str)[:500]}"
            chunks.append(
                StreamChunk(
                    type=StreamChunkType.TOOL_CALL,
                    tool_call=ToolCall(
                        id=tc.get("id", ""),
                        name=name,
                        arguments=args,
                        parse_error=parse_error,
                    ),
                )
            )
        pending_tool_calls.clear()
        return chunks

    async for line in lines:
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            for chunk in _flush_tool_calls():
                yield chunk
            yield StreamChunk(type=StreamChunkType.DONE)
            return

        try:
            parsed = json.loads(data)
            choice = (parsed.get("choices") or [{}])[0]
            delta = choice.get("delta", {})
            finish_reason = choice.get("finish_reason")

            if delta.get("content"):
                yield StreamChunk(
                    type=StreamChunkType.TEXT, content=delta["content"]
                )

            if delta.get("tool_calls"):
                for tc_delta in delta["tool_calls"]:
                    idx = tc_delta.get("index", 0)
                    if idx not in pending_tool_calls:
                        pending_tool_calls[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                    entry = pending_tool_calls[idx]
                    if tc_delta.get("id"):
                        entry["id"] = tc_delta["id"]
                    fn = tc_delta.get("function", {})
                    if fn.get("name"):
                        entry["name"] = fn["name"]
                    if "arguments" in fn:
                        entry["arguments"] += fn["arguments"]

            # Flush accumulated tool calls when the model signals stop
            if finish_reason == "tool_calls":
                for chunk in _flush_tool_calls():
                    yield chunk

            usage = parsed.get("usage")
            if usage:
                yield StreamChunk(
                    type=StreamChunkType.USAGE,
                    usage=TokenUsage(
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                    ),
                )
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            pass

    # Stream ended without [DONE] — flush any pending tool calls and
    # yield DONE so the caller doesn't hang waiting for a sentinel that
    # never arrives.  MiniMax sometimes closes the connection without it.
    for chunk in _flush_tool_calls():
        yield chunk
    yield StreamChunk(type=StreamChunkType.DONE)


async def adapt_anthropic_stream(
    lines: AsyncIterator[str],
) -> AsyncIterator[StreamChunk]:
    """Convert Anthropic SSE lines to StreamChunk iterator.

    Expects lines from an httpx streaming response (response.aiter_lines()).
    """
    import json

    current_tool_id: str | None = None
    current_tool_name: str | None = None
    tool_args_json: str = ""
    _in_thinking_block: bool = False

    async for line in lines:
        if not line.startswith("data: "):
            continue
        data = line[6:]

        try:
            parsed = json.loads(data)
            event_type = parsed.get("type")

            if event_type == "content_block_start":
                block = parsed.get("content_block", {})
                if block.get("type") == "tool_use":
                    current_tool_id = block.get("id", "")
                    current_tool_name = block.get("name", "")
                    tool_args_json = ""
                    _in_thinking_block = False
                elif block.get("type") == "thinking":
                    _in_thinking_block = True

            elif event_type == "content_block_delta":
                delta = parsed.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield StreamChunk(
                        type=StreamChunkType.TEXT, content=delta["text"]
                    )
                elif delta.get("type") == "thinking_delta":
                    yield StreamChunk(
                        type=StreamChunkType.THINKING, content=delta.get("thinking", "")
                    )
                elif delta.get("type") == "input_json_delta":
                    tool_args_json += delta.get("partial_json", "")

            elif event_type == "content_block_stop":
                _in_thinking_block = False
                if current_tool_id and current_tool_name:
                    try:
                        args = json.loads(tool_args_json) if tool_args_json else {}
                    except json.JSONDecodeError:
                        args = {}
                    yield StreamChunk(
                        type=StreamChunkType.TOOL_CALL,
                        tool_call=ToolCall(
                            id=current_tool_id,
                            name=current_tool_name,
                            arguments=args,
                        ),
                    )
                    current_tool_id = None
                    current_tool_name = None
                    tool_args_json = ""

            elif event_type == "message_delta":
                usage = parsed.get("usage", {})
                if usage:
                    yield StreamChunk(
                        type=StreamChunkType.USAGE,
                        usage=TokenUsage(
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                            total_tokens=(
                                usage.get("input_tokens", 0)
                                + usage.get("output_tokens", 0)
                            ),
                        ),
                    )

            elif event_type == "message_stop":
                yield StreamChunk(type=StreamChunkType.DONE)
                return

        except (json.JSONDecodeError, KeyError):
            pass

    yield StreamChunk(type=StreamChunkType.DONE)


def format_chunk_for_terminal(chunk: StreamChunk) -> str:
    """Format a stream chunk for terminal output."""
    match chunk.type:
        case StreamChunkType.TEXT:
            return chunk.content or ""
        case StreamChunkType.TOOL_CALL:
            name = chunk.tool_call.name if chunk.tool_call else "unknown"
            return f"\nTool: {name}\n"
        case StreamChunkType.ERROR:
            return f"\nError: {chunk.error}\n"
        case StreamChunkType.DONE:
            return "\n"
        case _:
            return ""
