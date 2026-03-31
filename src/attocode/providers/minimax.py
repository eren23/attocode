"""MiniMax provider — OpenAI-compatible API for M2 models.

Uses the global API endpoint at api.minimax.io/v1/chat/completions.
Text-only — images are stripped automatically.

MiniMax quirks vs standard OpenAI API:
- temperature must be in (0.0, 1.0] (exclusive of 0.0)
- stream_options may not be supported
- presence_penalty, frequency_penalty, logit_bias are ignored
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING, Any

import httpx

from attocode.errors import ProviderError
from attocode.providers.openai import OpenAIProvider
from attocode.providers.openai_compat import describe_request_error

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from attocode.types.messages import (
        ChatOptions,
        ChatResponse,
        Message,
        MessageWithStructuredContent,
        StreamChunk,
    )

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.minimax.io/v1/chat/completions"
DEFAULT_MODEL = "MiniMax-M2.7"

# MiniMax rejects temperature=0.0; clamp to this minimum
_MIN_TEMPERATURE = 0.01

# MiniMax wraps reasoning in <think>...</think> tags
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class MinimaxProvider(OpenAIProvider):
    """MiniMax provider for M2 models using the OpenAI-compatible API.

    Supports streaming, tool use (M2.1+), and extended thinking.
    Vision is not supported — images are stripped with a warning.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 600.0,
    ) -> None:
        resolved_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        if not resolved_key:
            raise ProviderError(
                "MINIMAX_API_KEY not set — get one at https://platform.minimax.io",
                provider="minimax",
                retryable=False,
            )
        super().__init__(
            api_key=resolved_key,
            model=model,
            api_url=api_url,
            timeout=timeout,
        )

    @property
    def name(self) -> str:
        return "minimax"

    @property
    def supports_vision(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # Image handling
    # ------------------------------------------------------------------

    @staticmethod
    def _has_image_content(
        messages: list[Message | MessageWithStructuredContent],
    ) -> bool:
        from attocode.types.messages import ImageContentBlock

        for msg in messages:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, ImageContentBlock):
                        return True
        return False

    @staticmethod
    def _strip_images(
        messages: list[Message | MessageWithStructuredContent],
    ) -> list[Message | MessageWithStructuredContent]:
        from attocode.types.messages import (
            ImageContentBlock,
            Message,
            MessageWithStructuredContent,
        )

        result: list[Message | MessageWithStructuredContent] = []
        for msg in messages:
            if not isinstance(msg.content, list):
                result.append(msg)
                continue
            non_image = [b for b in msg.content if not isinstance(b, ImageContentBlock)]
            if len(non_image) == len(msg.content):
                result.append(msg)
            elif not non_image:
                result.append(Message(
                    role=msg.role,
                    content="[image removed — not supported by MiniMax]",
                ))
            elif len(non_image) == 1:
                result.append(Message(role=msg.role, content=getattr(non_image[0], "text", str(non_image[0]))))
            else:
                result.append(MessageWithStructuredContent(role=msg.role, content=non_image))
        return result

    def _maybe_strip_images(
        self,
        messages: list[Message | MessageWithStructuredContent],
    ) -> list[Message | MessageWithStructuredContent]:
        if self._has_image_content(messages):
            logger.warning("MiniMax does not support inline images — images stripped")
            return self._strip_images(messages)
        return messages

    # ------------------------------------------------------------------
    # Think-tag stripping
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Remove <think>...</think> blocks from MiniMax responses."""
        return _THINK_RE.sub("", text).strip()

    def _parse_response(self, data: dict[str, Any], model: str) -> ChatResponse:
        """Parse response and strip think tags from content."""
        result = super()._parse_response(data, model)
        if result.content:
            cleaned = self._strip_think_tags(result.content)
            if cleaned != result.content:
                # Replace content on the response object
                object.__setattr__(result, "content", cleaned) if hasattr(result, "__dataclass_fields__") else setattr(result, "content", cleaned)
        return result

    # ------------------------------------------------------------------
    # Body building — MiniMax-specific parameter adjustments
    # ------------------------------------------------------------------

    def _build_body(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Build the request body with MiniMax-specific adjustments."""
        model = (options and options.model) or self._model
        body: dict[str, Any] = {
            "model": model,
            "messages": self._format_messages(messages),
        }
        if options and options.max_tokens:
            body["max_tokens"] = options.max_tokens

        # Clamp temperature: MiniMax requires (0.0, 1.0] exclusive of 0.0
        temp = (options and options.temperature) if (options and options.temperature is not None) else None
        if temp is not None:
            body["temperature"] = max(temp, _MIN_TEMPERATURE)
        else:
            body["temperature"] = _MIN_TEMPERATURE

        if options and options.tools:
            body["tools"] = [self._format_tool(t) for t in options.tools]

        if stream:
            body["stream"] = True
            # Intentionally NOT setting stream_options — MiniMax may not support it

        return body

    # ------------------------------------------------------------------
    # Overridden chat methods
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> ChatResponse:
        messages = self._maybe_strip_images(messages)
        client = self._ensure_client()
        body = self._build_body(messages, options, stream=False)

        try:
            response = await client.post(self._api_url, json=body)
            response.raise_for_status()
            return self._parse_response(response.json(), body["model"])
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            raise ProviderError(
                f"MiniMax API error {status}: {e.response.text[:500]}",
                provider="minimax", status_code=status,
                retryable=status in (429, 500, 502, 503),
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"MiniMax request error: {describe_request_error(e)}",
                provider="minimax", retryable=True,
            ) from e

    async def chat_stream(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        from attocode.integrations.streaming.handler import adapt_openrouter_stream
        from attocode.types.messages import StreamChunk as SC, StreamChunkType

        messages = self._maybe_strip_images(messages)
        client = self._ensure_client()
        body = self._build_body(messages, options, stream=True)

        # Stateful think-tag filter for streaming chunks
        in_think = False
        buffer = ""

        try:
            async with client.stream("POST", self._api_url, json=body) as response:
                response.raise_for_status()
                async for chunk in adapt_openrouter_stream(response.aiter_lines()):
                    # Only filter TEXT chunks; pass through tool calls, usage, etc.
                    if chunk.type != StreamChunkType.TEXT or not chunk.content:
                        yield chunk
                        continue

                    text = chunk.content

                    # Track whether we're inside <think>...</think>
                    result_parts: list[str] = []
                    i = 0
                    while i < len(text):
                        if in_think:
                            end = text.find("</think>", i)
                            if end == -1:
                                break  # Still inside think block
                            in_think = False
                            i = end + len("</think>")
                        else:
                            start = text.find("<think>", i)
                            if start == -1:
                                result_parts.append(text[i:])
                                break
                            if start > i:
                                result_parts.append(text[i:start])
                            in_think = True
                            i = start + len("<think>")

                    filtered = "".join(result_parts)
                    if filtered:
                        yield SC(type=StreamChunkType.TEXT, content=filtered)

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            raise ProviderError(
                f"MiniMax API error {status}: {e.response.text[:500]}",
                provider="minimax", status_code=status,
                retryable=status in (429, 500, 502, 503),
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"MiniMax request error: {describe_request_error(e)}",
                provider="minimax", retryable=True,
            ) from e
        except httpx.StreamError as e:
            raise ProviderError(
                f"MiniMax stream error: {type(e).__name__}: {e}",
                provider="minimax", retryable=True,
            ) from e
