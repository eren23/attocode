"""Tests for compaction utilities."""

from __future__ import annotations

from attocode.integrations.context.compaction import (
    adjust_slice_for_tool_pairs,
    compact_tool_outputs,
    emergency_truncation,
    truncate_tool_output,
)
from attocode.types.messages import Message, Role, ToolCall


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

    def test_preserves_tool_pairs(self) -> None:
        """Emergency truncation should not orphan tool results."""
        msgs = [
            Message(role=Role.SYSTEM, content="system"),
        ] + [
            Message(role=Role.USER, content=f"msg {i}")
            for i in range(15)
        ] + [
            Message(role=Role.ASSISTANT, content="", tool_calls=[
                ToolCall(id="tc-1", name="read", arguments={}),
            ]),
            Message(role=Role.TOOL, content="file contents", tool_call_id="tc-1"),
            Message(role=Role.USER, content="thanks"),
        ]
        # preserve_recent=2 would slice at the TOOL msg, orphaning it
        result = emergency_truncation(msgs, preserve_recent=2)
        tool_msgs = [m for m in result if m.role == Role.TOOL]
        for tm in tool_msgs:
            # Every tool result must have a preceding assistant with matching tool_call
            idx = result.index(tm)
            found = False
            for j in range(idx - 1, -1, -1):
                if result[j].role == Role.ASSISTANT and result[j].tool_calls:
                    tc_ids = {tc.id for tc in result[j].tool_calls}
                    if tm.tool_call_id in tc_ids:
                        found = True
                        break
            assert found, f"Orphaned tool result: tool_call_id={tm.tool_call_id}"


class TestAdjustSliceForToolPairs:
    def test_no_adjustment_on_user_message(self) -> None:
        msgs = [
            Message(role=Role.USER, content="a"),
            Message(role=Role.ASSISTANT, content="b"),
            Message(role=Role.USER, content="c"),
        ]
        assert adjust_slice_for_tool_pairs(msgs, 2) == 2

    def test_includes_assistant_with_tool_calls(self) -> None:
        """Slice starting at TOOL msg should pull back to include assistant."""
        msgs = [
            Message(role=Role.USER, content="do it"),
            Message(role=Role.ASSISTANT, content="", tool_calls=[
                ToolCall(id="tc-1", name="bash", arguments={}),
            ]),
            Message(role=Role.TOOL, content="result", tool_call_id="tc-1"),
            Message(role=Role.USER, content="next"),
        ]
        # Slice at index 2 (the TOOL msg) should adjust to 1 (the assistant)
        assert adjust_slice_for_tool_pairs(msgs, 2) == 1

    def test_includes_multiple_tool_results(self) -> None:
        """Slice starting at second TOOL msg should still pull back to assistant."""
        msgs = [
            Message(role=Role.USER, content="do it"),
            Message(role=Role.ASSISTANT, content="", tool_calls=[
                ToolCall(id="tc-1", name="read", arguments={}),
                ToolCall(id="tc-2", name="grep", arguments={}),
            ]),
            Message(role=Role.TOOL, content="r1", tool_call_id="tc-1"),
            Message(role=Role.TOOL, content="r2", tool_call_id="tc-2"),
            Message(role=Role.USER, content="next"),
        ]
        assert adjust_slice_for_tool_pairs(msgs, 3) == 1
        assert adjust_slice_for_tool_pairs(msgs, 2) == 1

    def test_skips_orphaned_tool_results(self) -> None:
        """TOOL msgs without preceding assistant+tool_calls are skipped."""
        msgs = [
            Message(role=Role.USER, content="compacted"),
            Message(role=Role.TOOL, content="orphan", tool_call_id="old"),
            Message(role=Role.USER, content="next"),
        ]
        # Should skip past the orphan TOOL msg
        assert adjust_slice_for_tool_pairs(msgs, 1) == 2

    def test_zero_index(self) -> None:
        msgs = [Message(role=Role.TOOL, content="x", tool_call_id="tc")]
        assert adjust_slice_for_tool_pairs(msgs, 0) == 1

    def test_boundary_at_end(self) -> None:
        msgs = [Message(role=Role.USER, content="a")]
        assert adjust_slice_for_tool_pairs(msgs, 5) == 5
