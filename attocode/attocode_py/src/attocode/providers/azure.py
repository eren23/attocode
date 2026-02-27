"""Azure OpenAI provider adapter.

Connects to Azure-hosted OpenAI models using the Azure-specific
API endpoint format and authentication.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from attocode.errors import ProviderError
from attocode.types.messages import (
    CacheControl,
    ChatOptions,
    ChatResponse,
    Message,
    MessageWithStructuredContent,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)


@dataclass
class AzureConfig:
    """Configuration for Azure OpenAI."""

    endpoint: str = ""
    api_key: str = ""
    api_version: str = "2024-06-01"
    deployment: str = ""
    timeout: float = 600.0

    @classmethod
    def from_env(cls) -> AzureConfig:
        """Load from environment variables."""
        return cls(
            endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01"),
            deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        )


class AzureOpenAIProvider:
    """Azure OpenAI provider adapter.

    Uses httpx for async HTTP communication with Azure's OpenAI API.
    """

    def __init__(self, config: AzureConfig | None = None) -> None:
        self._config = config or AzureConfig.from_env()
        if not self._config.endpoint:
            raise ProviderError(
                "Azure endpoint is required (set AZURE_OPENAI_ENDPOINT)",
                provider="azure",
                retryable=False,
            )
        if not self._config.api_key:
            raise ProviderError(
                "Azure API key is required (set AZURE_OPENAI_API_KEY)",
                provider="azure",
                retryable=False,
            )
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "azure"

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.endpoint.rstrip("/"),
                headers={
                    "api-key": self._config.api_key,
                    "Content-Type": "application/json",
                },
                timeout=self._config.timeout,
            )
        return self._client

    async def chat(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> ChatResponse:
        """Send a chat completion request to Azure OpenAI."""
        client = self._ensure_client()
        opts = options or ChatOptions()

        deployment = opts.model or self._config.deployment
        if not deployment:
            raise ProviderError(
                "Deployment name is required", provider="azure", retryable=False,
            )

        url = (
            f"/openai/deployments/{deployment}/chat/completions"
            f"?api-version={self._config.api_version}"
        )

        body: dict[str, Any] = {
            "messages": [_format_message(m) for m in messages],
        }
        if opts.max_tokens:
            body["max_tokens"] = opts.max_tokens
        if opts.temperature is not None:
            body["temperature"] = opts.temperature
        if opts.tools:
            body["tools"] = [_format_tool(t) for t in opts.tools]

        try:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            retryable = status in (429, 500, 502, 503, 504)
            raise ProviderError(
                f"Azure API error: {status} {e.response.text[:200]}",
                provider="azure",
                status_code=status,
                retryable=retryable,
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"Azure request error: {e}",
                provider="azure",
                retryable=True,
            ) from e

        return _parse_response(data)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


def _format_message(msg: Message | MessageWithStructuredContent) -> dict[str, Any]:
    """Format a message for the Azure OpenAI API."""
    result: dict[str, Any] = {"role": msg.role.value if hasattr(msg.role, "value") else str(msg.role)}

    if hasattr(msg, "content") and msg.content:
        result["content"] = msg.content

    if hasattr(msg, "tool_calls") and msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else tc.arguments,
                },
            }
            for tc in msg.tool_calls
        ]

    if hasattr(msg, "tool_call_id") and msg.tool_call_id:
        result["tool_call_id"] = msg.tool_call_id

    return result


def _format_tool(tool: ToolDefinition) -> dict[str, Any]:
    """Format a tool definition for Azure OpenAI API."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        },
    }


def _parse_response(data: dict[str, Any]) -> ChatResponse:
    """Parse an Azure OpenAI API response."""
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})

    content = message.get("content", "")
    stop_reason = StopReason.STOP

    finish_reason = choice.get("finish_reason", "")
    if finish_reason == "tool_calls":
        stop_reason = StopReason.TOOL_USE
    elif finish_reason == "length":
        stop_reason = StopReason.MAX_TOKENS

    tool_calls: list[ToolCall] = []
    for tc_data in message.get("tool_calls", []):
        func = tc_data.get("function", {})
        args_str = func.get("arguments", "{}")
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            args = {"raw": args_str}
        tool_calls.append(ToolCall(
            id=tc_data.get("id", ""),
            name=func.get("name", ""),
            arguments=args,
        ))

    usage_data = data.get("usage", {})
    usage = TokenUsage(
        input_tokens=usage_data.get("prompt_tokens", 0),
        output_tokens=usage_data.get("completion_tokens", 0),
    )

    return ChatResponse(
        content=content or None,
        stop_reason=stop_reason,
        tool_calls=tool_calls,
        usage=usage,
        model=data.get("model", ""),
    )
