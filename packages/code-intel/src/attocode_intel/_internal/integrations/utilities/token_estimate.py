"""Token estimation using tiktoken."""

from __future__ import annotations

import tiktoken

# Default encoding for Claude / GPT-4 class models
_DEFAULT_ENCODING = "cl100k_base"
_encoder: tiktoken.Encoding | None = None

# Shared ratio for quick estimation without tiktoken
CHARS_PER_TOKEN = 3.5


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding(_DEFAULT_ENCODING)
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken.

    Falls back to character-based estimation if tiktoken fails.
    """
    if not text:
        return 0
    try:
        return len(_get_encoder().encode(text))
    except Exception:
        return estimate_tokens(text)


def estimate_tokens(text: str) -> int:
    """Quick character-based token estimation without tiktoken."""
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    """Estimate total tokens for a list of message dicts."""
    total = 0
    for msg in messages:
        # Each message has ~4 token overhead for role/formatting
        total += 4
        content = msg.get("content", "")
        if content:
            total += count_tokens(content)
    return total
