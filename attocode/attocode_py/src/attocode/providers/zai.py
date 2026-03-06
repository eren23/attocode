"""Z.AI (ZhipuAI) provider — OpenAI-compatible API for GLM models.

The Z.AI coding plan endpoint (/coding/paas/) is text-only — it does not
accept image content blocks for any model.  When images are detected in
messages, this provider automatically strips them and logs a warning.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from attocode.errors import ProviderError
from attocode.providers.openai import OpenAIProvider

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

DEFAULT_API_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-5"


class ZAIProvider(OpenAIProvider):
    """Z.AI provider for GLM-5 and other ZhipuAI models.

    Uses the OpenAI-compatible API at api.z.ai.  The coding-plan
    endpoint is text-only, so images are stripped with a warning.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 600.0,
    ) -> None:
        resolved_key = api_key or os.environ.get("ZAI_API_KEY", "")
        if not resolved_key:
            raise ProviderError(
                "ZAI_API_KEY not set", provider="zai", retryable=False,
            )
        super().__init__(
            api_key=resolved_key,
            model=model,
            api_url=api_url,
            timeout=timeout,
        )

    @property
    def name(self) -> str:
        return "zai"

    @property
    def supports_vision(self) -> bool:
        # TODO(zai-vision): Enable once Z.AI coding plan endpoint
        # supports image content blocks. Currently /coding/paas/
        # returns 1210 for any model + image combination.
        # Options when re-enabling:
        # - Native VLM: switch model to glm-4.6v + endpoint to /paas/
        # - Describe-and-discard: side-call vision model, replace images
        #   with text descriptions, send text-only to glm-5
        return False

    # ------------------------------------------------------------------
    # Image handling
    # ------------------------------------------------------------------

    @staticmethod
    def _has_image_content(
        messages: list[Message | MessageWithStructuredContent],
    ) -> bool:
        """Check if any message contains image content blocks."""
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
        """Remove ImageContentBlocks from messages, keeping all other blocks.

        Uses a deny-list (filter out ImageContentBlock) rather than an
        allow-list so that future block types pass through safely.
        """
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

            non_image_blocks = [
                b for b in msg.content
                if not isinstance(b, ImageContentBlock)
            ]
            has_images = len(non_image_blocks) < len(msg.content)

            if not has_images:
                result.append(msg)
            elif len(non_image_blocks) == 0:
                # All-image message — replace with placeholder so the
                # message list never becomes empty or loses a turn.
                result.append(Message(
                    role=msg.role,
                    content="[image removed — not supported by this provider]",
                ))
            elif len(non_image_blocks) == 1:
                block = non_image_blocks[0]
                text = getattr(block, "text", str(block))
                result.append(Message(role=msg.role, content=text))
            else:
                result.append(MessageWithStructuredContent(
                    role=msg.role, content=non_image_blocks,
                ))

        return result

    def _maybe_strip_images(
        self,
        messages: list[Message | MessageWithStructuredContent],
    ) -> list[Message | MessageWithStructuredContent]:
        """Strip images if present, logging a warning. Shared by chat/chat_stream."""
        if self._has_image_content(messages):
            logger.warning(
                "Z.AI coding plan does not support inline images — "
                "images stripped from request"
            )
            return self._strip_images(messages)
        return messages

    # ------------------------------------------------------------------
    # Overridden chat methods
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> ChatResponse:
        messages = self._maybe_strip_images(messages)
        return await super().chat(messages, options)

    async def chat_stream(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        messages = self._maybe_strip_images(messages)
        async for chunk in super().chat_stream(messages, options):
            yield chunk
