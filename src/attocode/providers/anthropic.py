"""Anthropic API provider using httpx."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx

from attocode.errors import ProviderError
from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    ImageContentBlock,
    Message,
    MessageWithStructuredContent,
    Role,
    StopReason,
    StreamChunk,
    TextContentBlock,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DEFAULT_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 8192
API_VERSION = "2023-06-01"
# Claude 4.7 and later reject a non-default temperature, top_p, or top_k with a 400.
NO_SAMPLING_PREFIXES = (
    "claude-opus-4-7", "claude-opus-4-8", "claude-opus-5", "claude-sonnet-5",
    "claude-fable", "claude-mythos",
)
# Adaptive thinking. Opus 5.5 and Fable cannot turn thinking off, and turning it off on
# Opus 5 can put tool calls in the visible text. Low effort keeps cost near the old
# thinking-off runs. Prefixes, so claude-opus-5 also matches claude-opus-5-5.
ADAPTIVE_THINKING_PREFIXES = ("claude-sonnet-5", "claude-opus-5", "claude-fable", "claude-mythos")
# ponytail: one effort for every request; make it a ChatOptions field if a caller needs more.
THINKING_EFFORT = "low"
THINKING_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking"})

class AnthropicProvider:
    """Anthropic API provider using httpx."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 600.0,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ProviderError("ANTHROPIC_API_KEY not set", provider="anthropic", retryable=False)
        self._model = model
        self._max_tokens = max_tokens
        self._api_url = api_url
        self._timeout = timeout
        self._extra_headers = extra_headers or {}
        self._client = self._create_client()

    def _create_client(self) -> httpx.AsyncClient:
        """Create a fresh httpx client."""
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
                **self._extra_headers,
            },
        )

    def _ensure_client(self) -> httpx.AsyncClient:
        """Return the client, recreating it if closed."""
        if self._client.is_closed:
            self._client = self._create_client()
        return self._client

    @property
    def name(self) -> str:
        return "anthropic"

    async def chat(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> ChatResponse:
        client = self._ensure_client()
        body = self._build_body(messages, options)

        try:
            response = await client.post(self._api_url, json=body)
            if _thinking_rejected(response.status_code, response.text) and _strip_thinking(messages):
                response = await client.post(self._api_url, json=self._build_body(messages, options))
            response.raise_for_status()
            return self._parse_response(response.json(), body["model"])
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            raise ProviderError(
                f"Anthropic API error {status}: {e.response.text[:500]}",
                provider="anthropic",
                status_code=status,
                retryable=status in (429, 500, 502, 503, 529),
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError("Anthropic API timeout", provider="anthropic", retryable=True) from e
        except httpx.RequestError as e:
            raise ProviderError(f"Anthropic request error: {e}", provider="anthropic", retryable=True) from e

    async def chat_stream(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat response from the Anthropic API."""
        from attocode.integrations.streaming.handler import adapt_anthropic_stream

        client = self._ensure_client()

        try:
            for attempt in range(2):
                body = {**self._build_body(messages, options), "stream": True}
                async with client.stream("POST", self._api_url, json=body) as response:
                    if response.status_code >= 400:
                        # Must read body INSIDE async-with before response closes
                        await response.aread()
                        status = response.status_code
                        if attempt == 0 and _thinking_rejected(status, response.text) and _strip_thinking(messages):
                            continue
                        error_body = response.text[:500]
                        raise ProviderError(
                            f"Anthropic API error {status}: {error_body}",
                            provider="anthropic",
                            status_code=status,
                            retryable=status in (429, 500, 502, 503, 529),
                        )
                    async for chunk in adapt_anthropic_stream(response.aiter_lines()):
                        yield chunk
                    return
        except ProviderError:
            raise
        except httpx.TimeoutException as e:
            raise ProviderError("Anthropic API timeout", provider="anthropic", retryable=True) from e
        except httpx.RequestError as e:
            raise ProviderError(f"Anthropic request error: {e}", provider="anthropic", retryable=True) from e

    def _build_body(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None,
    ) -> dict[str, Any]:
        model = (options and options.model) or self._model
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": (options and options.max_tokens) or self._max_tokens,
            "messages": self._format_messages(messages),
        }

        if options and options.temperature is not None and not model.startswith(NO_SAMPLING_PREFIXES):
            body["temperature"] = options.temperature
        if model.startswith(ADAPTIVE_THINKING_PREFIXES):
            # "summarized" fills the TUI thinking panel. The default, "omitted", sends empty text.
            body["thinking"] = {"type": "adaptive", "display": "summarized"}
            body["output_config"] = {"effort": THINKING_EFFORT}

        system_msgs = [m for m in messages if m.role == Role.SYSTEM]
        if system_msgs:
            body["system"] = self._format_system(system_msgs)
            body["messages"] = [m for m in body["messages"] if m.get("role") != "system"]

        if options and options.tools:
            body["tools"] = [self._format_tool(t) for t in options.tools]
        return body

    def _format_messages(self, messages: list[Message | MessageWithStructuredContent]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue
            formatted = self._format_single(msg)
            if formatted:
                result.append(formatted)
        # A trailing assistant turn is a prefill, which Claude 4.6 and later reject
        # with a 400. The loop leaves one after a text-only max_tokens stop, so ask
        # for the continuation in a user turn.
        if result and result[-1]["role"] == "assistant":
            result.append({
                "role": "user",
                "content": "Your previous response was cut off. Continue from where it stopped.",
            })
        return result

    def _format_single(self, msg: Message | MessageWithStructuredContent) -> dict[str, Any] | None:
        if msg.role == Role.TOOL:
            return {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": str(msg.content)}],
            }
        raw = (msg.metadata or {}).get("raw_content") if msg.role == Role.ASSISTANT else None
        # Thinking blocks go back unchanged, in their original order. Use the raw blocks
        # only while they still pair with the message's tool calls.
        if raw and [b["id"] for b in raw if b["type"] == "tool_use"] == [tc.id for tc in msg.tool_calls or []]:
            return {"role": "assistant", "content": raw}
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            blocks: list[dict[str, Any]] = []
            content = msg.content
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            for tc in msg.tool_calls:
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
            return {"role": "assistant", "content": blocks}
        content = msg.content
        if isinstance(content, list):
            blocks = []
            for block in content:
                if isinstance(block, TextContentBlock):
                    b: dict[str, Any] = {"type": "text", "text": block.text}
                    if block.cache_control:
                        b["cache_control"] = {"type": block.cache_control.type}
                    blocks.append(b)
                elif isinstance(block, ImageContentBlock):
                    from attocode.types.messages import ImageSourceType
                    if block.source.type == ImageSourceType.URL:
                        blocks.append({
                            "type": "image",
                            "source": {"type": "url", "url": block.source.data},
                        })
                    else:
                        blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": block.source.media_type, "data": block.source.data},
                        })
            return {"role": str(msg.role), "content": blocks}
        return {"role": str(msg.role), "content": content}

    def _format_system(self, msgs: list[Message | MessageWithStructuredContent]) -> str | list[dict[str, Any]]:
        if len(msgs) == 1 and isinstance(msgs[0].content, str):
            return msgs[0].content
        blocks: list[dict[str, Any]] = []
        for msg in msgs:
            if isinstance(msg.content, str):
                blocks.append({"type": "text", "text": msg.content})
        return blocks

    def _format_tool(self, tool: ToolDefinition) -> dict[str, Any]:
        return {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}

    def _parse_response(self, data: dict[str, Any], model: str) -> ChatResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        thinking: str | None = None

        for block in data.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block.get("input", {})))
            elif block["type"] == "thinking":
                thinking = block.get("thinking", "")

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            cache_read_tokens=usage_data.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage_data.get("cache_creation_input_tokens", 0),
        )
        from attocode.providers.base import get_model_pricing

        pricing = get_model_pricing(model)
        usage.cost = pricing.estimate_cost(
            usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
        )

        stop = data.get("stop_reason", "end_turn")
        stop_reason = StopReason.TOOL_USE if stop == "tool_use" else (StopReason.MAX_TOKENS if stop == "max_tokens" else StopReason.END_TURN)

        content = data.get("content", [])
        return ChatResponse(
            content="\n".join(text_parts),
            tool_calls=tool_calls or None,
            usage=usage,
            model=model,
            stop_reason=stop_reason,
            thinking=thinking,
            raw_content=content if any(b["type"] in THINKING_BLOCK_TYPES for b in content) else None,
        )

    async def close(self) -> None:
        await self._client.aclose()


def _thinking_rejected(status: int, text: str) -> bool:
    """The API rejected a thinking block's signature.

    Opus 5.5 and Fable 5.1 bind each thinking block to the history before it. Compaction
    and tool-result truncation edit that history, so the API rejects the later blocks.
    """
    return status == 400 and "signature" in text and "thinking" in text


def _strip_thinking(messages: list[Message | MessageWithStructuredContent]) -> bool:
    """Drop the stored thinking blocks from the history. Return True if there were any.

    The API accepts turns without their thinking. This changes the caller's messages, so
    later requests do not send the same rejected blocks again.
    """
    stripped = False
    for msg in messages:
        if msg.metadata and msg.metadata.pop("raw_content", None) is not None:
            stripped = True
    return stripped
