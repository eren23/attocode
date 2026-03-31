"""Tests for message_builder — build_forked_messages and fork cache sharing."""

from __future__ import annotations

import pytest

from attocode.agent.message_builder import (
    FORK_PLACEHOLDER_RESULT,
    FORK_TAG,
    build_forked_messages,
    build_initial_messages,
)
from attocode.types.messages import (
    Message,
    MessageWithStructuredContent,
    Role,
    TextContentBlock,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_parent_messages(system_text: str = "You are helpful.") -> list[Message]:
    """Build a minimal parent message list: [system, user]."""
    return [
        Message(role=Role.SYSTEM, content=system_text),
        Message(role=Role.USER, content="Do something"),
    ]


# ---------------------------------------------------------------------------
# build_forked_messages — happy path
# ---------------------------------------------------------------------------
class TestBuildForkedMessages:
    def test_returns_three_messages(self) -> None:
        parent = _make_parent_messages()
        result = build_forked_messages(parent, "child task")
        assert len(result) == 3

    def test_system_message_is_byte_identical(self) -> None:
        """The first message must be the exact same object for cache hits."""
        parent = _make_parent_messages("Custom system prompt")
        result = build_forked_messages(parent, "child task")
        assert result[0] is parent[0]
        assert result[0].content == "Custom system prompt"

    def test_fork_context_contains_tag(self) -> None:
        parent = _make_parent_messages()
        result = build_forked_messages(parent, "child task")
        fork_ctx = result[1]
        assert isinstance(fork_ctx, Message)
        assert FORK_TAG in fork_ctx.content
        assert FORK_PLACEHOLDER_RESULT in fork_ctx.content

    def test_fork_context_role_is_user(self) -> None:
        parent = _make_parent_messages()
        result = build_forked_messages(parent, "child task")
        assert result[1].role == Role.USER

    def test_directive_message_contains_task(self) -> None:
        parent = _make_parent_messages()
        result = build_forked_messages(parent, "refactor module X")
        directive = result[2]
        assert isinstance(directive, Message)
        assert "refactor module X" in directive.content
        assert directive.role == Role.USER

    def test_directive_identifies_fork_role(self) -> None:
        parent = _make_parent_messages()
        result = build_forked_messages(parent, "task")
        assert "fork subagent" in result[2].content.lower()

    def test_custom_fork_tag(self) -> None:
        parent = _make_parent_messages()
        result = build_forked_messages(parent, "task", fork_tag="[CUSTOM_FORK]")
        assert "[CUSTOM_FORK]" in result[1].content


# ---------------------------------------------------------------------------
# build_forked_messages — error cases
# ---------------------------------------------------------------------------
class TestBuildForkedMessagesErrors:
    def test_empty_parent_raises(self) -> None:
        with pytest.raises(ValueError, match="empty parent messages"):
            build_forked_messages([], "task")

    def test_recursive_fork_detected_plain_message(self) -> None:
        parent = [
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content=f"{FORK_TAG}\ncontext"),
            Message(role=Role.USER, content="original task"),
        ]
        with pytest.raises(ValueError, match="Recursive forking"):
            build_forked_messages(parent, "child task")

    def test_recursive_fork_detected_structured_content(self) -> None:
        parent = [
            Message(role=Role.SYSTEM, content="system"),
            MessageWithStructuredContent(
                role=Role.USER,
                content=[TextContentBlock(text=f"some {FORK_TAG} text")],
            ),
        ]
        with pytest.raises(ValueError, match="Recursive forking"):
            build_forked_messages(parent, "child task")

    def test_no_false_positive_without_tag(self) -> None:
        """Regular messages without the fork tag should NOT raise."""
        parent = [
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content="normal user message"),
            Message(role=Role.ASSISTANT, content="normal assistant reply"),
        ]
        result = build_forked_messages(parent, "task")
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Integration: build_initial_messages -> build_forked_messages round-trip
# ---------------------------------------------------------------------------
class TestForkRoundTrip:
    def test_fork_from_initial_messages(self) -> None:
        """Forking from build_initial_messages() output should work."""
        initial = build_initial_messages(
            "Hello",
            system_prompt="You are helpful.",
        )
        forked = build_forked_messages(initial, "sub-task")
        # System prompt preserved exactly
        assert forked[0].content == "You are helpful."
        assert forked[0].role == Role.SYSTEM
        # Fork context + directive
        assert len(forked) == 3

    def test_double_fork_prevented(self) -> None:
        """Forking a fork should raise."""
        initial = build_initial_messages("Hello", system_prompt="sys")
        forked = build_forked_messages(initial, "sub-task")
        with pytest.raises(ValueError, match="Recursive forking"):
            build_forked_messages(forked, "sub-sub-task")
