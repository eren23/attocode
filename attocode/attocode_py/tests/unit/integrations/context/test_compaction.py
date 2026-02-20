"""Tests for compaction utilities."""

from __future__ import annotations

from attocode.integrations.context.compaction import (
    compact_tool_outputs,
    emergency_truncation,
    truncate_tool_output,
)
from attocode.types.messages import Message, Role


class TestCompactToolOutputs:
    def test_compacts_long_tool_output(self) -> None:
        msgs = [
            Message(role=Role.USER, content="do something"),
            Message(role=Role.TOOL, content="x" * 500, tool_call_id="tc_1"),
            Message(role=Role.ASSISTANT, content="done"),
        ]
        count = compact_tool_outputs(msgs, preview_length=100, preserve_recent=1)
        assert count == 1
        assert len(msgs[1].content) < 200

    def test_preserves_recent(self) -> None:
        msgs = [
            Message(role=Role.TOOL, content="x" * 500, tool_call_id="tc_1"),
            Message(role=Role.TOOL, content="y" * 500, tool_call_id="tc_2"),
        ]
        compact_tool_outputs(msgs, preview_length=100, preserve_recent=1)
        # Last message preserved
        assert len(msgs[-1].content) == 500

    def test_skips_non_tool_messages(self) -> None:
        msgs = [
            Message(role=Role.USER, content="x" * 500),
            Message(role=Role.ASSISTANT, content="y" * 500),
        ]
        count = compact_tool_outputs(msgs, preview_length=100, preserve_recent=0)
        assert count == 0

    def test_skips_short_messages(self) -> None:
        msgs = [
            Message(role=Role.TOOL, content="short", tool_call_id="tc_1"),
        ]
        count = compact_tool_outputs(msgs, preview_length=100, preserve_recent=0)
        assert count == 0


class TestTruncateToolOutput:
    def test_short_not_truncated(self) -> None:
        assert truncate_tool_output("hello", max_chars=100) == "hello"

    def test_long_truncated(self) -> None:
        long_text = "a" * 10000
        result = truncate_tool_output(long_text, max_chars=100)
        assert len(result) < 10000
        assert "truncated" in result

    def test_preserves_start_and_end(self) -> None:
        text = "START" + "x" * 1000 + "END"
        result = truncate_tool_output(text, max_chars=100)
        assert result.startswith("START")
        assert result.endswith("END")


class TestEmergencyTruncation:
    def test_keeps_system_and_recent(self) -> None:
        msgs = [
            Message(role=Role.SYSTEM, content="system"),
        ] + [
            Message(role=Role.USER, content=f"msg {i}")
            for i in range(20)
        ]
        result = emergency_truncation(msgs, preserve_recent=5)
        assert result[0].role == Role.SYSTEM
        assert len(result) <= 7  # system + work_log + 5 recent

    def test_injects_work_log(self) -> None:
        msgs = [
            Message(role=Role.SYSTEM, content="system"),
        ] + [
            Message(role=Role.USER, content=f"msg {i}")
            for i in range(20)
        ]
        result = emergency_truncation(msgs, preserve_recent=3, work_log_summary="did stuff")
        # Should have work log injection
        has_summary = any("did stuff" in m.content for m in result if m.content)
        assert has_summary

    def test_no_op_for_short(self) -> None:
        msgs = [
            Message(role=Role.SYSTEM, content="s"),
            Message(role=Role.USER, content="u"),
        ]
        result = emergency_truncation(msgs, preserve_recent=5)
        assert len(result) == 2
