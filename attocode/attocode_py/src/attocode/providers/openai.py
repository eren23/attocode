"""OpenAI API provider using httpx."""

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
    Message,
    MessageWithStructuredContent,
    Role,
    StopReason,
    StreamChunk,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o"


def _describe_request_error(e: httpx.RequestError) -> str:
    """Build a descriptive error message for httpx request errors.

    httpx.ReadTimeout and similar errors often have empty str(e),
    so we fall back to the exception type name and include the
    chained cause when available.
    """
    msg = str(e)
    if not msg:
        msg = type(e).__name__
    if e.__cause__ and str(e.__cause__):
        msg = f"{msg} (caused by {type(e.__cause__).__name__}: {e.__cause__})"
    return msg


class OpenAIProvider:
    """OpenAI API provider using httpx."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 600.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise ProviderError("OPENAI_API_KEY not set", provider="openai", retryable=False)
        self._model = model
        self._api_url = api_url
        self._timeout = timeout
        self._client = self._create_client()

    def _create_client(self) -> httpx.AsyncClient:
        """Create a fresh httpx client."""
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
        )

    def _ensure_client(self) -> httpx.AsyncClient:
        """Return the client, recreating it if closed."""
        if self._client.is_closed:
            self._client = self._create_client()
        return self._client

    @property
    def name(self) -> str:
        return "openai"

    async def chat(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> ChatResponse:
        client = self._ensure_client()
        model = (options and options.model) or self._model
        body: dict[str, Any] = {"model": model, "messages": self._format_messages(messages)}
        if options and options.max_tokens:
            body["max_tokens"] = options.max_tokens
        if options and options.temperature is not None:
            body["temperature"] = options.temperature
        if options and options.tools:
            body["tools"] = [self._format_tool(t) for t in options.tools]

        try:
            response = await client.post(self._api_url, json=body)
            response.raise_for_status()
            return self._parse_response(response.json(), model)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            raise ProviderError(
                f"OpenAI API error {status}: {e.response.text[:500]}",
                provider="openai", status_code=status, retryable=status in (429, 500, 502, 503),
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"OpenAI request error: {_describe_request_error(e)}",
                provider="openai", retryable=True,
            ) from e

    async def chat_stream(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat response from the OpenAI API."""
        from attocode.integrations.streaming.handler import adapt_openrouter_stream

        client = self._ensure_client()
        model = (options and options.model) or self._model
        body: dict[str, Any] = {
            "model": model,
            "messages": self._format_messages(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if options and options.max_tokens:
            body["max_tokens"] = options.max_tokens
        if options and options.temperature is not None:
            body["temperature"] = options.temperature
        if options and options.tools:
            body["tools"] = [self._format_tool(t) for t in options.tools]

        try:
            async with client.stream("POST", self._api_url, json=body) as response:
                response.raise_for_status()
                async for chunk in adapt_openrouter_stream(response.aiter_lines()):
                    yield chunk
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            raise ProviderError(
                f"OpenAI API error {status}: {e.response.text[:500]}",
                provider="openai", status_code=status, retryable=status in (429, 500, 502, 503),
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"OpenAI request error: {_describe_request_error(e)}",
                provider="openai", retryable=True,
            ) from e
        except httpx.StreamError as e:
            raise ProviderError(
                f"OpenAI stream error: {type(e).__name__}: {e}",
                provider="openai", retryable=True,
            ) from e

    def _format_messages(self, messages: list[Message | MessageWithStructuredContent]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if msg.role == Role.TOOL:
                result.append({"role": "tool", "content": content, "tool_call_id": msg.tool_call_id or ""})
            elif msg.role == Role.ASSISTANT and msg.tool_calls:
                tc_list = [
                    {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in msg.tool_calls
                ]
                result.append({"role": "assistant", "content": content or None, "tool_calls": tc_list})
            else:
                result.append({"role": str(msg.role), "content": content})
        return result

    def _format_tool(self, tool: ToolDefinition) -> dict[str, Any]:
        return {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters}}

    def _parse_response(self, data: dict[str, Any], model: str) -> ChatResponse:
        choices = data.get("choices", [])
        if not choices:
            return ChatResponse(content="", model=model, stop_reason=StopReason.END_TURN)
        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content", "") or ""

        tool_calls: list[ToolCall] | None = None
        if raw_tc := message.get("tool_calls"):
            tool_calls = []
            for tc in raw_tc:
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=tc["id"], name=func["name"], arguments=args))

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        finish = choice.get("finish_reason", "stop")
        stop_reason = StopReason.TOOL_USE if finish == "tool_calls" else (StopReason.MAX_TOKENS if finish == "length" else StopReason.END_TURN)

        return ChatResponse(content=content, tool_calls=tool_calls, usage=usage, model=model, stop_reason=stop_reason)

    async def close(self) -> None:
        await self._client.aclose()
