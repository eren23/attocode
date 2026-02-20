"""Z.AI (ZhipuAI) provider — OpenAI-compatible API for GLM models."""

from __future__ import annotations

import os

from attocode.errors import ProviderError
from attocode.providers.openai import OpenAIProvider

DEFAULT_API_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-5"


class ZAIProvider(OpenAIProvider):
    """Z.AI provider for GLM-5 and other ZhipuAI models.

    Uses the OpenAI-compatible API at api.z.ai.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 120.0,
    ) -> None:
        resolved_key = api_key or os.environ.get("ZAI_API_KEY", "")
        if not resolved_key:
            raise ProviderError("ZAI_API_KEY not set", provider="zai", retryable=False)
        # Pass to OpenAI base with Z.AI endpoint
        super().__init__(
            api_key=resolved_key,
            model=model,
            api_url=api_url,
            timeout=timeout,
        )

    @property
    def name(self) -> str:
        return "zai"
