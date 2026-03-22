"""Tests for file-driven project state."""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.integrations.persistence.project_state import (
    ProjectState,
    ProjectStateManager,
)


class TestProjectState:
    def test_empty_state(self) -> None:
        state = ProjectState()
        assert state.is_empty is True
        assert state.as_context_block() == ""

    def test_non_empty_state(self) -> None:
        state = ProjectState(state_content="Some decisions")
        assert state.is_empty is False

    def test_context_block(self) -> None:
        state = ProjectState(
            state_content="Decision 1",
            plan_content="Step 1\nStep 2",
            conventions_content="Use snake_case",
        )
        block = state.as_context_block()
        assert "Project State" in block
        assert "Decision 1" in block
        assert "Current Plan" in block
        assert "Code Conventions" in block


class TestProjectStateManager:
    def test_load_empty(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        state = mgr.load()
        assert state.is_empty is True

    def test_update_state(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        mgr.load()
        mgr.update_state("Decided to use PostgreSQL")

        state = mgr.load()
        assert "PostgreSQL" in state.state_content
        assert "Project State" in state.state_content

    def test_update_state_appends(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        mgr.load()
        mgr.update_state("First decision")
        mgr.update_state("Second decision")

        state = mgr.load()
        assert "First decision" in state.state_content
        assert "Second decision" in state.state_content

    def test_update_plan(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        mgr.load()
        mgr.update_plan("# Plan\n1. Do thing\n2. Do other thing")

        state = mgr.load()
        assert "Do thing" in state.plan_content

    def test_update_plan_overwrites(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        mgr.load()
        mgr.update_plan("Old plan")
        mgr.update_plan("New plan")

        state = mgr.load()
        assert "Old plan" not in state.plan_content
        assert "New plan" in state.plan_content

    def test_update_conventions(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        mgr.load()
        mgr.update_conventions("- Use type hints\n- Use dataclasses")

        state = mgr.load()
        assert "type hints" in state.conventions_content

    def test_clear_plan(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        mgr.load()
        mgr.update_plan("Some plan")
        mgr.clear_plan()

        state = mgr.load()
        assert state.plan_content == ""

    def test_clear_plan_no_file(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        mgr.load()
        mgr.clear_plan()  # Should not raise

    def test_get_state_entries(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        mgr.load()
        mgr.update_state("Entry one")
        mgr.update_state("Entry two")

        entries = mgr.get_state_entries()
        assert len(entries) == 2
        assert "Entry one" in entries[0]["content"]
        assert "Entry two" in entries[1]["content"]
        assert entries[0]["timestamp"]  # Has a timestamp

    def test_exists(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        assert mgr.exists() is False
        mgr.update_state("Create dir")
        assert mgr.exists() is True

    def test_project_dir_path(self, tmp_path: Path) -> None:
        mgr = ProjectStateManager(tmp_path)
        assert mgr.project_dir == tmp_path / ".attocode" / "project"

    def test_state_survives_reload(self, tmp_path: Path) -> None:
        mgr1 = ProjectStateManager(tmp_path)
        mgr1.load()
        mgr1.update_state("Persisted decision")
        mgr1.update_plan("Persisted plan")
        mgr1.update_conventions("Persisted conventions")

        # New manager instance (simulates restart)
        mgr2 = ProjectStateManager(tmp_path)
        state = mgr2.load()
        assert "Persisted decision" in state.state_content
        assert "Persisted plan" in state.plan_content
        assert "Persisted conventions" in state.conventions_content
