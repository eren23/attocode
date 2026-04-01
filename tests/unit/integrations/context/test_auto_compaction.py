"""Tests for auto-compaction manager."""

from __future__ import annotations

from attocode.integrations.context.auto_compaction import (
    AutoCompactionManager,
    CompactionStatus,
)
from attocode.types.messages import Message, Role, ToolCall


def _make_messages(count: int, content_size: int = 100) -> list[Message]:
    """Create test messages with specified content size."""
    return [
        Message(role=Role.SYSTEM, content="system prompt"),
    ] + [
        Message(role=Role.USER if i % 2 == 0 else Role.ASSISTANT, content="x" * content_size)
        for i in range(count)
    ]


class TestAutoCompactionCheck:
    def test_ok_under_threshold(self) -> None:
        mgr = AutoCompactionManager(max_context_tokens=100000)
        msgs = _make_messages(5, content_size=10)
        result = mgr.check(msgs)
        assert result.status == CompactionStatus.OK

    def test_warning_at_threshold(self) -> None:
        mgr = AutoCompactionManager(max_context_tokens=100, warning_threshold=0.5)
        msgs = _make_messages(10, content_size=50)
        result = mgr.check(msgs)
        # With tiktoken counting, this should be above warning
        assert result.status in (CompactionStatus.WARNING, CompactionStatus.NEEDS_COMPACTION)

    def test_needs_compaction(self) -> None:
        mgr = AutoCompactionManager(max_context_tokens=50, compaction_threshold=0.5)
        msgs = _make_messages(10, content_size=100)
        result = mgr.check(msgs)
        assert result.status == CompactionStatus.NEEDS_COMPACTION


class TestAutoCompactionCompact:
    def test_compact_keeps_system(self) -> None:
        mgr = AutoCompactionManager()
        msgs = _make_messages(10)
        result = mgr.compact(msgs, "Summary of work done")
        assert result[0].role == Role.SYSTEM

    def test_compact_injects_summary(self) -> None:
        mgr = AutoCompactionManager()
        msgs = _make_messages(10)
        result = mgr.compact(msgs, "Did X, Y, Z")
        contents = [m.content for m in result]
        assert any("Did X, Y, Z" in c for c in contents)

    def test_compact_with_extra_context(self) -> None:
        mgr = AutoCompactionManager()
        msgs = _make_messages(10)
        result = mgr.compact(msgs, "Summary", extra_context=["Goal: build API", "Learned: use async"])
        contents = " ".join(m.content for m in result)
        assert "Goal: build API" in contents

    def test_compact_reduces_messages(self) -> None:
        mgr = AutoCompactionManager()
        msgs = _make_messages(50)
        result = mgr.compact(msgs, "Summary")
        assert len(result) < len(msgs)


class TestCompactToolPairPreservation:
    def test_compact_does_not_orphan_tool_results(self) -> None:
        """compact() should include the assistant message when recent slice starts at a TOOL msg."""
        mgr = AutoCompactionManager(min_messages_to_keep=2)
        msgs = [
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content="old msg 1"),
            Message(role=Role.ASSISTANT, content="old msg 2"),
            Message(role=Role.USER, content="old msg 3"),
            Message(role=Role.ASSISTANT, content="", tool_calls=[
                ToolCall(id="tc-1", name="read", arguments={}),
            ]),
            Message(role=Role.TOOL, content="file contents", tool_call_id="tc-1"),
            Message(role=Role.USER, content="thanks"),
        ]
        result = mgr.compact(msgs, "Summary of work")
        tool_msgs = [m for m in result if m.role == Role.TOOL]
        for tm in tool_msgs:
            idx = result.index(tm)
            found = False
            for j in range(idx - 1, -1, -1):
                if result[j].role == Role.ASSISTANT and result[j].tool_calls:
                    tc_ids = {tc.id for tc in result[j].tool_calls}
                    if tm.tool_call_id in tc_ids:
                        found = True
                        break
            assert found, f"Orphaned tool result: tool_call_id={tm.tool_call_id}"

    def test_emergency_compact_does_not_orphan_tool_results(self) -> None:
        """emergency_compact() should include assistant message with tool results."""
        mgr = AutoCompactionManager(min_messages_to_keep=4)
        msgs = [
            Message(role=Role.SYSTEM, content="system"),
        ] + [
            Message(role=Role.USER, content=f"old {i}")
            for i in range(20)
        ] + [
            Message(role=Role.ASSISTANT, content="", tool_calls=[
                ToolCall(id="tc-e", name="bash", arguments={}),
            ]),
            Message(role=Role.TOOL, content="output", tool_call_id="tc-e"),
            Message(role=Role.USER, content="ok"),
            Message(role=Role.ASSISTANT, content="done"),
        ]
        result = mgr.emergency_compact(msgs)
        tool_msgs = [m for m in result if m.role == Role.TOOL]
        for tm in tool_msgs:
            idx = result.index(tm)
            found = False
            for j in range(idx - 1, -1, -1):
                if result[j].role == Role.ASSISTANT and result[j].tool_calls:
                    tc_ids = {tc.id for tc in result[j].tool_calls}
                    if tm.tool_call_id in tc_ids:
                        found = True
                        break
            assert found, f"Orphaned tool result: tool_call_id={tm.tool_call_id}"


class TestSummaryPrompt:
    def test_prompt_content(self) -> None:
        mgr = AutoCompactionManager()
        prompt = mgr.create_summary_prompt()
        assert "summary" in prompt.lower()
        assert "accomplished" in prompt.lower()
