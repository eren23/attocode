"""Tests for architect/editor dual-model workflow."""

from __future__ import annotations

import pytest

from attocode.core.dual_model import (
    ArchitectPlan,
    DualModelConfig,
    DualModelWorkflow,
    EditorResult,
)


class TestDualModelConfig:
    def test_defaults(self) -> None:
        config = DualModelConfig()
        assert config.enabled is False
        assert config.architect_model == ""
        assert config.editor_model == ""

    def test_custom(self) -> None:
        config = DualModelConfig(
            architect_model="claude-opus-4-20250514",
            editor_model="claude-haiku-4-20250414",
            enabled=True,
        )
        assert config.enabled is True


class TestDualModelWorkflow:
    def test_not_enabled_without_architect_model(self) -> None:
        wf = DualModelWorkflow(DualModelConfig(enabled=True))
        assert wf.enabled is False

    def test_enabled_with_config(self) -> None:
        wf = DualModelWorkflow(DualModelConfig(
            enabled=True,
            architect_model="claude-opus-4-20250514",
        ))
        assert wf.enabled is True

    def test_architect_prompt(self) -> None:
        wf = DualModelWorkflow(DualModelConfig())
        prompt = wf.create_architect_prompt("Fix the login bug", context="Users report 500 errors")
        assert "ARCHITECT" in prompt
        assert "Fix the login bug" in prompt
        assert "500 errors" in prompt
        assert "NOT to write code" in prompt

    def test_editor_prompt(self) -> None:
        wf = DualModelWorkflow(DualModelConfig())
        plan = ArchitectPlan(
            analysis="Need to fix auth middleware",
            proposed_changes=[
                {"file": "src/auth.py", "description": "Add error handling"},
            ],
        )
        prompt = wf.create_editor_prompt(plan)
        assert "EDITOR" in prompt
        assert "auth middleware" in prompt
        assert "src/auth.py" in prompt

    def test_editor_prompt_with_files(self) -> None:
        wf = DualModelWorkflow(DualModelConfig())
        plan = ArchitectPlan(analysis="Fix bug")
        prompt = wf.create_editor_prompt(
            plan,
            file_contents={"src/main.py": "def main(): pass"},
        )
        assert "src/main.py" in prompt
        assert "def main" in prompt

    def test_parse_architect_response_confidence(self) -> None:
        wf = DualModelWorkflow(DualModelConfig())
        response = "## Plan\nFix the bug.\n\nConfidence: 85%\n"
        plan = wf.parse_architect_response(response)
        assert plan.confidence == pytest.approx(0.85)

    def test_parse_architect_response_changes(self) -> None:
        wf = DualModelWorkflow(DualModelConfig())
        response = (
            "## Changes\n"
            "1. src/auth.py: Add validation\n"
            "2. src/routes.py: Update handler\n"
        )
        plan = wf.parse_architect_response(response)
        assert len(plan.proposed_changes) == 2
        assert plan.proposed_changes[0]["file"] == "src/auth.py"

    def test_parse_architect_response_no_confidence(self) -> None:
        wf = DualModelWorkflow(DualModelConfig())
        plan = wf.parse_architect_response("Just do the thing.")
        assert plan.confidence == 0.0

    def test_record_editor_result(self) -> None:
        wf = DualModelWorkflow(DualModelConfig())
        result = wf.record_editor_result(["a.py", "b.py"])
        assert result.files_modified == ["a.py", "b.py"]
        assert wf.stats.editor_calls == 1
        assert wf.stats.total_files_modified == 2

    def test_stats_accumulate(self) -> None:
        wf = DualModelWorkflow(DualModelConfig())
        wf.parse_architect_response("Plan 1")
        wf.parse_architect_response("Plan 2")
        wf.record_editor_result(["a.py"])
        assert wf.stats.architect_calls == 2
        assert wf.stats.editor_calls == 1

    def test_last_plan_tracked(self) -> None:
        wf = DualModelWorkflow(DualModelConfig())
        assert wf.last_plan is None
        wf.parse_architect_response("Some plan")
        assert wf.last_plan is not None
        assert "Some plan" in wf.last_plan.analysis
