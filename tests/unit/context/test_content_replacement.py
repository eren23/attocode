"""Tests for ContentReplacementState, ReplacedContent, and CODE_INTEL_TOOLS."""

from __future__ import annotations

from attocode.integrations.context.compaction import (
    CODE_INTEL_TOOLS,
    ContentReplacementState,
)
from attocode.integrations.utilities.token_estimate import estimate_tokens


def test_record_and_query_replacement() -> None:
    """record_replacement stores data; get_evicted_code_intel returns code-intel entries."""
    state = ContentReplacementState()

    # Record a code-intel tool result
    state.record_replacement(
        message_id="msg-1",
        tool_name="ast_query",  # in CODE_INTEL_TOOLS
        original_content="symbol table data " * 50,
        turn_number=3,
        preview="symbol table data",
    )

    evicted = state.get_evicted_code_intel()
    assert len(evicted) == 1
    mid, rc = evicted[0]
    assert mid == "msg-1"
    assert rc.tool_name == "ast_query"
    assert rc.was_code_intel is True
    assert rc.turn_number == 3
    assert rc.original_token_estimate > 0


def test_code_intel_prioritized_over_regular() -> None:
    """Code-intel results appear before regular results in get_restorable."""
    state = ContentReplacementState()

    # Regular tool (large)
    state.record_replacement(
        message_id="msg-regular",
        tool_name="bash",
        original_content="x" * 4000,  # 1000 tokens
        turn_number=1,
    )
    # Code-intel tool (smaller)
    state.record_replacement(
        message_id="msg-intel",
        tool_name="semantic_search",
        original_content="y" * 2000,  # 500 tokens
        turn_number=2,
    )

    restorable = state.get_restorable(token_budget=5000)

    # Code-intel should come first despite being smaller
    assert restorable[0] == "msg-intel"
    assert restorable[1] == "msg-regular"


def test_get_restorable_respects_budget() -> None:
    """Token budget limits which items are returned."""
    state = ContentReplacementState()

    # Add three equal items
    for i in range(3):
        state.record_replacement(
            message_id=f"msg-{i}",
            tool_name="bash",
            original_content="a" * 1000,
            turn_number=i,
        )

    # Budget for only 2 items
    restorable = state.get_restorable(token_budget=2 * estimate_tokens("a" * 1000))
    assert len(restorable) == 2

    # Budget for 0
    restorable_zero = state.get_restorable(token_budget=0)
    assert len(restorable_zero) == 0


def test_clear_and_remove() -> None:
    """clear() empties all records; remove() removes a single record."""
    state = ContentReplacementState()

    state.record_replacement("a", "bash", "content a", turn_number=1)
    state.record_replacement("b", "bash", "content b", turn_number=2)

    # Remove one
    state.remove("a")
    assert state.evicted_count == 1

    # Re-add and then clear all
    state.record_replacement("c", "bash", "content c", turn_number=3)
    assert state.evicted_count == 2

    state.clear()
    assert state.evicted_count == 0
    assert state.total_evicted_tokens == 0


def test_total_evicted_tokens() -> None:
    """total_evicted_tokens returns the sum of all estimated tokens."""
    state = ContentReplacementState()

    state.record_replacement("a", "bash", "x" * 400, turn_number=1)
    state.record_replacement("b", "grep", "y" * 800, turn_number=2)

    assert state.total_evicted_tokens == estimate_tokens("x" * 400) + estimate_tokens("y" * 800)


def test_to_dict_serialization() -> None:
    """to_dict returns expected structure."""
    state = ContentReplacementState()

    state.record_replacement(
        message_id="msg-1",
        tool_name="ast_query",
        original_content="code analysis results here",
        turn_number=5,
        preview="code analysis",
    )

    d = state.to_dict()

    assert d["count"] == 1
    assert d["total_tokens"] == estimate_tokens("code analysis results here")
    assert d["code_intel_count"] == 1
    assert "msg-1" in d["items"]

    item = d["items"]["msg-1"]
    assert item["tool"] == "ast_query"
    assert item["turn"] == 5
    assert item["code_intel"] is True
    assert "code analysis" in item["preview"]
