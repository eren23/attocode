"""Tests for mode manager."""

from __future__ import annotations

import pytest

from attocode.integrations.utilities.mode_manager import (
    EXEC_TOOLS,
    MODE_PROMPTS,
    MODE_TOOL_ACCESS,
    READ_TOOLS,
    WRITE_TOOLS,
    AgentMode,
    ModeCheckResult,
    ModeManager,
    ProposedChange,
    _is_test_command,
)


class TestAgentMode:
    def test_enum_values(self) -> None:
        assert AgentMode.BUILD == "build"
        assert AgentMode.PLAN == "plan"
        assert AgentMode.REVIEW == "review"
        assert AgentMode.DEBUG == "debug"

    def test_all_modes_have_tool_access(self) -> None:
        for mode in AgentMode:
            assert mode in MODE_TOOL_ACCESS

    def test_all_modes_have_prompts(self) -> None:
        for mode in AgentMode:
            assert mode in MODE_PROMPTS


class TestProposedChange:
    def test_defaults(self) -> None:
        change = ProposedChange(
            tool_name="write_file",
            path="/tmp/foo.py",
            description="write_file on /tmp/foo.py",
            arguments={"path": "/tmp/foo.py", "content": "hello"},
        )
        assert not change.approved
        assert not change.rejected

    def test_approve(self) -> None:
        change = ProposedChange(
            tool_name="edit_file",
            path="a.py",
            description="edit_file on a.py",
            arguments={},
        )
        change.approved = True
        assert change.approved


class TestModeManagerInit:
    def test_default_mode_is_build(self) -> None:
        mgr = ModeManager()
        assert mgr.mode == AgentMode.BUILD

    def test_no_proposed_changes_initially(self) -> None:
        mgr = ModeManager()
        assert mgr.proposed_changes == []


class TestSwitchMode:
    def test_switch_to_plan(self) -> None:
        mgr = ModeManager()
        result = mgr.switch_mode(AgentMode.PLAN)
        assert mgr.mode == AgentMode.PLAN
        assert "plan" in result.lower()

    def test_switch_with_string(self) -> None:
        mgr = ModeManager()
        result = mgr.switch_mode("review")
        assert mgr.mode == AgentMode.REVIEW
        assert "review" in result.lower()

    def test_switch_invalid_mode_string(self) -> None:
        mgr = ModeManager()
        result = mgr.switch_mode("nonexistent")
        assert "Unknown mode" in result
        assert mgr.mode == AgentMode.BUILD  # unchanged

    def test_switch_tracks_history(self) -> None:
        mgr = ModeManager()
        mgr.switch_mode(AgentMode.PLAN)
        mgr.switch_mode(AgentMode.DEBUG)
        assert mgr._mode_history == [AgentMode.BUILD, AgentMode.PLAN]


class TestPreviousMode:
    def test_reverts_to_previous(self) -> None:
        mgr = ModeManager()
        mgr.switch_mode(AgentMode.REVIEW)
        result = mgr.previous_mode()
        assert mgr.mode == AgentMode.BUILD
        assert "build" in result.lower()

    def test_multiple_reverts(self) -> None:
        mgr = ModeManager()
        mgr.switch_mode(AgentMode.PLAN)
        mgr.switch_mode(AgentMode.DEBUG)
        mgr.previous_mode()
        assert mgr.mode == AgentMode.PLAN
        mgr.previous_mode()
        assert mgr.mode == AgentMode.BUILD

    def test_no_history(self) -> None:
        mgr = ModeManager()
        result = mgr.previous_mode()
        assert "No previous mode" in result
        assert mgr.mode == AgentMode.BUILD


class TestCheckToolAccess:
    def test_build_allows_all(self) -> None:
        mgr = ModeManager()
        for tool in ["read_file", "write_file", "bash", "spawn_agent"]:
            result = mgr.check_tool_access(tool)
            assert result.allowed, f"Build mode should allow {tool}"

    def test_plan_allows_read(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        for tool in READ_TOOLS:
            result = mgr.check_tool_access(tool)
            assert result.allowed, f"Plan mode should allow read tool: {tool}"

    def test_plan_intercepts_writes(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        result = mgr.check_tool_access(
            "write_file",
            arguments={"path": "foo.py", "content": "hello"},
        )
        assert not result.allowed
        assert result.intercepted
        assert len(mgr.proposed_changes) == 1
        assert mgr.proposed_changes[0].path == "foo.py"

    def test_plan_intercept_uses_file_path_key(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        mgr.check_tool_access(
            "edit_file",
            arguments={"file_path": "bar.py"},
        )
        assert mgr.proposed_changes[0].path == "bar.py"

    def test_plan_blocks_exec(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        result = mgr.check_tool_access("bash")
        assert not result.allowed
        assert not result.intercepted

    def test_review_allows_read_only(self) -> None:
        mgr = ModeManager(mode=AgentMode.REVIEW)
        for tool in READ_TOOLS:
            assert mgr.check_tool_access(tool).allowed
        for tool in WRITE_TOOLS | EXEC_TOOLS:
            result = mgr.check_tool_access(tool)
            assert not result.allowed
            assert "review mode" in result.reason.lower()

    def test_debug_allows_read(self) -> None:
        mgr = ModeManager(mode=AgentMode.DEBUG)
        for tool in READ_TOOLS:
            assert mgr.check_tool_access(tool).allowed

    def test_debug_allows_test_commands(self) -> None:
        mgr = ModeManager(mode=AgentMode.DEBUG)
        result = mgr.check_tool_access("bash", arguments={"command": "pytest tests/"})
        assert result.allowed

    def test_debug_blocks_non_test_bash(self) -> None:
        mgr = ModeManager(mode=AgentMode.DEBUG)
        result = mgr.check_tool_access("bash", arguments={"command": "rm -rf /"})
        assert not result.allowed
        assert "test commands" in result.reason.lower()

    def test_debug_blocks_writes(self) -> None:
        mgr = ModeManager(mode=AgentMode.DEBUG)
        result = mgr.check_tool_access("write_file")
        assert not result.allowed


class TestSystemPromptSupplement:
    def test_build_mode_empty(self) -> None:
        mgr = ModeManager()
        assert mgr.get_system_prompt_supplement() == ""

    def test_plan_mode_has_text(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        text = mgr.get_system_prompt_supplement()
        assert "PLAN" in text
        assert "proposed changes" in text.lower()

    def test_review_mode_has_text(self) -> None:
        mgr = ModeManager(mode=AgentMode.REVIEW)
        text = mgr.get_system_prompt_supplement()
        assert "REVIEW" in text

    def test_debug_mode_has_text(self) -> None:
        mgr = ModeManager(mode=AgentMode.DEBUG)
        text = mgr.get_system_prompt_supplement()
        assert "DEBUG" in text


class TestProposedChanges:
    def test_approve_change(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        mgr.check_tool_access("write_file", arguments={"path": "x.py", "content": ""})
        result = mgr.approve_change(0)
        assert "Approved" in result
        assert mgr.proposed_changes[0].approved

    def test_reject_change(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        mgr.check_tool_access("write_file", arguments={"path": "x.py", "content": ""})
        result = mgr.reject_change(0)
        assert "Rejected" in result
        assert mgr.proposed_changes[0].rejected

    def test_approve_invalid_index(self) -> None:
        mgr = ModeManager()
        result = mgr.approve_change(5)
        assert "Invalid" in result

    def test_reject_invalid_index(self) -> None:
        mgr = ModeManager()
        result = mgr.reject_change(-1)
        assert "Invalid" in result

    def test_approve_all(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        mgr.check_tool_access("write_file", arguments={"path": "a.py", "content": ""})
        mgr.check_tool_access("edit_file", arguments={"path": "b.py"})
        result = mgr.approve_all_changes()
        assert "Approved 2" in result
        assert all(c.approved for c in mgr.proposed_changes)

    def test_reject_all(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        mgr.check_tool_access("write_file", arguments={"path": "a.py", "content": ""})
        result = mgr.reject_all_changes()
        assert "Rejected 1" in result

    def test_get_pending_changes(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        mgr.check_tool_access("write_file", arguments={"path": "a.py", "content": ""})
        mgr.check_tool_access("write_file", arguments={"path": "b.py", "content": ""})
        mgr.approve_change(0)
        pending = mgr.get_pending_changes()
        assert len(pending) == 1
        assert pending[0].path == "b.py"

    def test_format_changes_summary_empty(self) -> None:
        mgr = ModeManager()
        assert "No proposed changes" in mgr.format_changes_summary()

    def test_format_changes_summary(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        mgr.check_tool_access("write_file", arguments={"path": "a.py", "content": ""})
        mgr.approve_change(0)
        summary = mgr.format_changes_summary()
        assert "approved" in summary
        assert "1 total" in summary

    def test_clear_changes(self) -> None:
        mgr = ModeManager(mode=AgentMode.PLAN)
        mgr.check_tool_access("write_file", arguments={"path": "a.py", "content": ""})
        mgr.clear_changes()
        assert mgr.proposed_changes == []


class TestIsTestCommand:
    def test_pytest(self) -> None:
        assert _is_test_command("pytest tests/")
        assert _is_test_command("python -m pytest tests/")

    def test_npm_test(self) -> None:
        assert _is_test_command("npm test")
        assert _is_test_command("npm run test")

    def test_mypy(self) -> None:
        assert _is_test_command("mypy src/")

    def test_ruff(self) -> None:
        assert _is_test_command("ruff check .")

    def test_non_test_command(self) -> None:
        assert not _is_test_command("rm -rf /")
        assert not _is_test_command("echo hello")
        assert not _is_test_command("python script.py")
