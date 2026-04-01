"""Tests for tool deferral (ToolDeferralManager, schema builder)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from attocode.integrations.tool_deferral import (
    DEFAULT_DEFERRED,
    DeferredTool,
    ToolDeferralManager,
    build_deferred_toolsystem,
)


def test_default_deferred_includes_lsp_and_search() -> None:
    names = {d.name for d in DEFAULT_DEFERRED}
    assert "lsp_definition" in names
    assert "semantic_search" in names
    assert "lsp_call_hierarchy" in names


def test_search_matches_keyword_phrase() -> None:
    mgr = ToolDeferralManager(
        deferred_tools=[
            DeferredTool(
                name="lsp_definition",
                intent_keywords=["goto definition", "definition"],
                search_hint="Go to def",
            ),
        ],
    )
    results = mgr.search("please goto definition of main")
    assert len(results) >= 1
    assert results[0].tool_name == "lsp_definition"
    assert results[0].confidence >= 0.5


def test_search_sorts_by_confidence() -> None:
    mgr = ToolDeferralManager(
        deferred_tools=[
            DeferredTool(name="weak_tool", intent_keywords=["maybe"], search_hint="w"),
            DeferredTool(
                name="strong_tool",
                intent_keywords=["semantic search", "embeddings"],
                search_hint="s",
            ),
        ],
    )
    results = mgr.search("semantic search embeddings for auth")
    assert results[0].tool_name == "strong_tool"


def test_mark_deferred_and_immediate() -> None:
    mgr = ToolDeferralManager(deferred_tools=[])
    mgr.mark_deferred("custom", intent_keywords=["x"], search_hint="hint")
    assert mgr.is_deferred("custom")
    assert "custom" in mgr.get_deferred_names()
    mgr.mark_immediate("custom")
    assert not mgr.is_deferred("custom")


def test_get_immediate_names_filters_deferred() -> None:
    reg = MagicMock()
    reg.list_tools = MagicMock(return_value=["read_file", "lsp_definition", "bash"])
    mgr = ToolDeferralManager(registry=reg)
    immediate = mgr.get_immediate_names()
    assert immediate is not None
    assert "read_file" in immediate
    assert "bash" in immediate
    assert "lsp_definition" not in immediate


def test_get_immediate_names_none_without_registry() -> None:
    mgr = ToolDeferralManager(registry=None, deferred_tools=[])
    assert mgr.get_immediate_names() is None


def test_should_defer_reflects_membership() -> None:
    mgr = ToolDeferralManager(deferred_tools=[DeferredTool(name="z", search_hint="")])
    assert mgr.should_defer("z") is True
    assert mgr.should_defer("read_file") is False


def test_build_toolsearch_message_includes_tool_name() -> None:
    mgr = ToolDeferralManager(
        deferred_tools=[
            DeferredTool(name="lsp_hover", search_hint="Hover help", intent_keywords=[]),
        ],
    )
    msg = mgr.build_toolsearch_message("lsp_hover", "type signature")
    assert "lsp_hover" in msg
    assert "[ToolSearch Result]" in msg
    assert "Hover help" in msg


def test_build_search_results_message_no_match() -> None:
    mgr = ToolDeferralManager(deferred_tools=[])
    msg = mgr.build_search_results_message("nothing relevant")
    assert "No deferred tools match" in msg


def test_build_search_results_message_lists_matches() -> None:
    mgr = ToolDeferralManager(
        deferred_tools=[
            DeferredTool(
                name="security_scan",
                intent_keywords=["security audit"],
                search_hint="Scan",
            ),
        ],
    )
    msg = mgr.build_search_results_message("run a security audit")
    assert "[ToolSearch]" in msg
    assert "security_scan" in msg


def test_search_for_tool() -> None:
    mgr = ToolDeferralManager(
        deferred_tools=[
            DeferredTool(
                name="semantic_search",
                intent_keywords=["semantic"],
                search_hint="",
            ),
        ],
    )
    hit = mgr.search_for_tool("semantic_search", "semantic code search")
    assert hit is not None
    assert hit.tool_name == "semantic_search"


def test_build_deferred_toolsystem_include_in_schema() -> None:
    mgr = ToolDeferralManager(
        deferred_tools=[
            DeferredTool(name="alpha", search_hint="A tool"),
        ],
    )
    doc = build_deferred_toolsystem(mgr, include_in_schema=True)
    assert "Deferred Tools" in doc
    assert "alpha" in doc
    assert "ToolSearch" in doc


def test_build_deferred_toolsystem_minimal_when_false() -> None:
    mgr = ToolDeferralManager(
        deferred_tools=[DeferredTool(name="x", search_hint="")],
    )
    assert build_deferred_toolsystem(mgr, include_in_schema=False) == ""
