"""Tests for microcompact() and ToolDecayProfile."""

from __future__ import annotations

from attocode.integrations.context.compaction import (
    TOOL_DECAY_PROFILES,
    ToolDecayProfile,
    _DEFAULT_PROFILE,
    microcompact,
)
from attocode.types.messages import Message, Role, ToolCall


def _assistant_with_tool_calls(calls: list[ToolCall]) -> Message:
    """Helper: build an assistant message carrying tool calls."""
    return Message(role=Role.ASSISTANT, content="", tool_calls=calls)


def _tool_result(tool_call_id: str, content: str) -> Message:
    """Helper: build a tool-result message."""
    return Message(role=Role.TOOL, content=content, tool_call_id=tool_call_id)


def test_microcompact_clears_old_tool_results() -> None:
    """Tool results older than max_age_turns are replaced with a cleared marker."""
    # glob_files has max_age_turns=4.  We put it at the start and set current_turn=10
    # so the age (10 - 0 = 10) exceeds 4.
    tc = ToolCall(id="tc1", name="glob_files", arguments={})
    messages: list[Message] = [
        _assistant_with_tool_calls([tc]),
        _tool_result("tc1", "file1.py\nfile2.py\n" * 200),
    ]

    cleared = microcompact(messages, current_turn=10)

    assert cleared == 1
    assert messages[1].content.startswith("[Cleared:")
    assert "glob_files" in messages[1].content


def test_microcompact_preserves_recent() -> None:
    """Tool results that are younger than max_age_turns are not touched."""
    # edit_file has max_age_turns=8.  Place it at current_turn - 2, so age = 2.
    tc = ToolCall(id="tc1", name="edit_file", arguments={})
    original_content = "edited something important"
    messages: list[Message] = [
        # Pad with assistant messages so _estimate_turn gives turn=8
        *[Message(role=Role.ASSISTANT, content="thinking") for _ in range(8)],
        _assistant_with_tool_calls([tc]),
        _tool_result("tc1", original_content),
    ]

    cleared = microcompact(messages, current_turn=10)

    assert cleared == 0
    assert messages[-1].content == original_content


def test_microcompact_respects_priority() -> None:
    """Low-priority tools are cleared before high-priority tools at the same age."""
    # Both at age > max_age_turns, but glob_files (priority=1) should be cleared
    # before edit_file (priority=7).  Both will be cleared since both exceed their
    # max_age, but glob goes first in the candidate sort order.
    tc_glob = ToolCall(id="tc_glob", name="glob_files", arguments={})
    tc_edit = ToolCall(id="tc_edit", name="edit_file", arguments={})

    messages: list[Message] = [
        _assistant_with_tool_calls([tc_glob, tc_edit]),
        _tool_result("tc_glob", "glob output " * 100),
        _tool_result("tc_edit", "edit output " * 100),
    ]

    # current_turn=20 ensures both are old enough (age=20)
    # glob_files max_age=4, edit_file max_age=8 — both exceeded
    cleared = microcompact(messages, current_turn=20)

    assert cleared == 2
    # Both cleared
    assert messages[1].content.startswith("[Cleared:")
    assert messages[2].content.startswith("[Cleared:")

    # Now test that at an intermediate age only the lower-priority one is cleared:
    # age=6 exceeds glob_files max_age (4) but not edit_file max_age (8)
    tc_glob2 = ToolCall(id="tc_glob2", name="glob_files", arguments={})
    tc_edit2 = ToolCall(id="tc_edit2", name="edit_file", arguments={})
    messages2: list[Message] = [
        _assistant_with_tool_calls([tc_glob2, tc_edit2]),
        _tool_result("tc_glob2", "glob output " * 100),
        _tool_result("tc_edit2", "edit output " * 100),
    ]

    cleared2 = microcompact(messages2, current_turn=6)
    assert cleared2 == 1
    assert messages2[1].content.startswith("[Cleared:")
    assert not messages2[2].content.startswith("[Cleared:")


def test_microcompact_no_op_empty() -> None:
    """Empty message list returns 0 cleared."""
    assert microcompact([], current_turn=10) == 0


def test_tool_decay_profile_defaults() -> None:
    """Unknown tool names fall back to _DEFAULT_PROFILE (max_age=4, priority=3)."""
    assert _DEFAULT_PROFILE.tool_name == "_default"
    assert _DEFAULT_PROFILE.max_age_turns == 4
    assert _DEFAULT_PROFILE.priority == 3
    assert _DEFAULT_PROFILE.preview_length == 150

    # Verify that a known tool (edit_file) has its own profile, different from default
    edit_profile = TOOL_DECAY_PROFILES["edit_file"]
    assert edit_profile.max_age_turns == 8
    assert edit_profile.priority == 7
