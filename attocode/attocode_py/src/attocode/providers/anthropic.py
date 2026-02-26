"""Anthropic API provider using httpx."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from attocode.errors import ProviderError
from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    ContentBlock,
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

DEFAULT_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 8192
API_VERSION = "2023-06-01"

class AnthropicProvider:
    """Anthropic API provider using httpx."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 120.0,
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
        model = (options and options.model) or self._model
        max_tokens = (options and options.max_tokens) or self._max_tokens

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": self._format_messages(messages),
        }

        if options and options.temperature is not None:
            body["temperature"] = options.temperature

        system_msgs = [m for m in messages if m.role == Role.SYSTEM]
        if system_msgs:
            body["system"] = self._format_system(system_msgs)
            body["messages"] = [m for m in body["messages"] if m.get("role") != "system"]

        if options and options.tools:
            body["tools"] = [self._format_tool(t) for t in options.tools]

        try:
            response = await client.post(self._api_url, json=body)
            response.raise_for_status()
            return self._parse_response(response.json(), model)
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
        model = (options and options.model) or self._model
        max_tokens = (options and options.max_tokens) or self._max_tokens

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": self._format_messages(messages),
            "stream": True,
        }

        if options and options.temperature is not None:
            body["temperature"] = options.temperature

        system_msgs = [m for m in messages if m.role == Role.SYSTEM]
        if system_msgs:
            body["system"] = self._format_system(system_msgs)
            body["messages"] = [m for m in body["messages"] if m.get("role") != "system"]

        if options and options.tools:
            body["tools"] = [self._format_tool(t) for t in options.tools]

        try:
            async with client.stream("POST", self._api_url, json=body) as response:
                if response.status_code >= 400:
                    # Must read body INSIDE async-with before response closes
                    await response.aread()
                    status = response.status_code
                    error_body = response.text[:500]
                    raise ProviderError(
                        f"Anthropic API error {status}: {error_body}",
                        provider="anthropic",
                        status_code=status,
                        retryable=status in (429, 500, 502, 503, 529),
                    )
                async for chunk in adapt_anthropic_stream(response.aiter_lines()):
                    yield chunk
        except ProviderError:
            raise
        except httpx.TimeoutException as e:
            raise ProviderError("Anthropic API timeout", provider="anthropic", retryable=True) from e
        except httpx.RequestError as e:
            raise ProviderError(f"Anthropic request error: {e}", provider="anthropic", retryable=True) from e

    def _format_messages(self, messages: list[Message | MessageWithStructuredContent]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue
            formatted = self._format_single(msg)
            if formatted:
                result.append(formatted)
        return result

    def _format_single(self, msg: Message | MessageWithStructuredContent) -> dict[str, Any] | None:
        if msg.role == Role.TOOL:
            return {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": str(msg.content)}],
            }
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
                    blocks.append({
                        "type": "image",
                        "source": {"type": block.source.type, "media_type": block.source.media_type, "data": block.source.data},
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

        return ChatResponse(
            content="\n".join(text_parts),
            tool_calls=tool_calls or None,
            usage=usage,
            model=model,
            stop_reason=stop_reason,
            thinking=thinking,
        )

    async def close(self) -> None:
        await self._client.aclose()
