"""Tests for run context builder optimizations."""
from __future__ import annotations

import inspect

import pytest


def test_feature_init_gated_on_run_count():
    """Feature initialization only runs when run_count == 0."""
    from attocode.agent.run_context_builder import build_run_context

    source = inspect.getsource(build_run_context)
    # The feature_initializer import and call should be inside a run_count == 0 guard
    assert "agent._run_count == 0" in source
    assert "initialize_features" in source


def test_managers_persisted_after_first_run():
    """Managers from ctx are saved to agent after first run."""
    from attocode.agent.run_context_builder import build_run_context

    source = inspect.getsource(build_run_context)
    # After feature init, managers should be persisted back to the agent
    assert "agent._codebase_context = ctx.codebase_context" in source
    assert "agent._economics = ctx.economics" in source
    assert "agent._compaction_manager = ctx.compaction_manager" in source
    assert "agent._mode_manager = ctx.mode_manager" in source
    assert "agent._thread_manager = ctx.thread_manager" in source
    assert "agent._learning_store = ctx.learning_store" in source


def test_managers_reused_on_second_run():
    """On subsequent runs, managers are wired from agent back into ctx."""
    from attocode.agent.run_context_builder import build_run_context

    source = inspect.getsource(build_run_context)
    # The else branch should wire agent managers into the new ctx
    assert "ctx.mode_manager = agent._mode_manager" in source
    assert "ctx.codebase_context = agent._codebase_context" in source
    assert "ctx.economics = agent._economics" in source


def test_preseed_uses_user_message_not_tool_call():
    """Preseed map injected as user message, not fake tool_call."""
    from attocode.agent.run_context_builder import build_run_context

    source = inspect.getsource(build_run_context)
    assert "<system-context>" in source
    assert "role=Role.USER" in source
    # Should NOT have fake tool calls for the preseed injection
    assert 'name="get_repo_map"' not in source


def test_preseed_only_on_first_run():
    """Preseed map is only injected when run_count == 0."""
    from attocode.agent.run_context_builder import build_run_context

    source = inspect.getsource(build_run_context)
    # The preseed block is inside a run_count == 0 guard
    # Find the preseed section and confirm it checks run_count
    preseed_idx = source.find("_get_or_build_preseed")
    assert preseed_idx != -1
    # Look backwards for the guard -- it should be within the same block
    preceding = source[:preseed_idx]
    last_run_count_check = preceding.rfind("agent._run_count == 0")
    assert last_run_count_check != -1


def test_sync_setup_cached_on_subsequent_runs():
    """Skills and learning context are cached after first run."""
    from attocode.agent.run_context_builder import build_run_context

    source = inspect.getsource(build_run_context)
    assert "agent._cached_skills" in source
    assert "agent._cached_learning_context" in source


def test_effective_rules_prefers_config():
    """_effective_rules returns config rules when available."""
    from unittest.mock import MagicMock
    from attocode.agent.run_context_builder import _effective_rules

    agent = MagicMock()
    agent._config.rules = ["rule1", "rule2"]
    ctx = MagicMock()

    result = _effective_rules(agent, ctx)
    assert result == ["rule1", "rule2"]


def test_effective_rules_falls_back_to_loaded():
    """_effective_rules falls back to ctx loaded rules when config is empty."""
    from unittest.mock import MagicMock
    from attocode.agent.run_context_builder import _effective_rules

    agent = MagicMock()
    agent._config.rules = []
    ctx = MagicMock()
    ctx._loaded_rules = ["loaded_rule"]

    result = _effective_rules(agent, ctx)
    assert result == ["loaded_rule"]


def test_effective_rules_filters_empty_strings():
    """_effective_rules filters out empty/whitespace-only rules."""
    from unittest.mock import MagicMock
    from attocode.agent.run_context_builder import _effective_rules

    agent = MagicMock()
    agent._config.rules = ["good rule", "", "  ", "another"]
    ctx = MagicMock()

    result = _effective_rules(agent, ctx)
    assert result == ["good rule", "another"]


def test_session_metadata_resolves_project_root():
    """_session_metadata resolves project_root from working_dir if needed."""
    from unittest.mock import MagicMock
    from attocode.agent.run_context_builder import _session_metadata

    agent = MagicMock()
    agent._working_dir = "/some/path"
    agent._session_dir = None
    agent._project_root = ""

    meta = _session_metadata(agent)
    assert meta["working_dir"] == "/some/path"
    assert meta["project_root"]  # Should be resolved, not empty
