"""Tests for token estimation."""

from __future__ import annotations

from attocode.integrations.utilities.token_estimate import (
    count_tokens,
    estimate_tokens,
    estimate_messages_tokens,
)


class TestCountTokens:
    def test_empty(self) -> None:
        assert count_tokens("") == 0

    def test_simple_text(self) -> None:
        count = count_tokens("Hello, world!")
        assert count > 0
        assert count < 10

    def test_longer_text(self) -> None:
        text = "This is a longer text with multiple words and sentences. " * 10
        count = count_tokens(text)
        assert count > 50

    def test_code(self) -> None:
        code = "def hello():\n    print('hello world')\n"
        count = count_tokens(code)
        assert count > 5


class TestEstimateTokens:
    def test_empty(self) -> None:
        assert estimate_tokens("") == 0

    def test_simple(self) -> None:
        count = estimate_tokens("Hello world")
        assert count > 0

    def test_roughly_accurate(self) -> None:
        text = "word " * 100  # ~100 tokens
        est = estimate_tokens(text)
        # Should be within 2x
        assert 30 < est < 300


class TestEstimateMessagesTokens:
    def test_empty(self) -> None:
        assert estimate_messages_tokens([]) == 0

    def test_single_message(self) -> None:
        count = estimate_messages_tokens([{"role": "user", "content": "Hello"}])
        assert count > 0

    def test_multiple_messages(self) -> None:
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        count = estimate_messages_tokens(msgs)
        # Should account for overhead per message
        assert count > 12  # At least 4 per message overhead
