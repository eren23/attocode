"""Tests for role-based agent modes (Code/Architect/Ask/Orchestrate)."""

from __future__ import annotations

import pytest

from attocode.integrations.utilities.mode_manager import (
    AGENT_TOOLS,
    EXEC_TOOLS,
    MODE_PROMPTS,
    MODE_TOOL_ACCESS,
    READ_TOOLS,
    WRITE_TOOLS,
    AgentMode,
    ModeManager,
)


class TestRoleModeEnum:
    """Test that all new role-based modes exist in the enum."""

    def test_code_mode_exists(self) -> None:
        assert AgentMode.CODE == "code"

    def test_architect_mode_exists(self) -> None:
        assert AgentMode.ARCHITECT == "architect"

    def test_ask_mode_exists(self) -> None:
        assert AgentMode.ASK == "ask"

    def test_orchestrate_mode_exists(self) -> None:
        assert AgentMode.ORCHESTRATE == "orchestrate"

    def test_original_modes_still_exist(self) -> None:
        """Existing modes must not be broken."""
        assert AgentMode.BUILD == "build"
        assert AgentMode.PLAN == "plan"
        assert AgentMode.REVIEW == "review"
        assert AgentMode.DEBUG == "debug"

    def test_all_modes_have_tool_access(self) -> None:
        for mode in AgentMode:
            assert mode in MODE_TOOL_ACCESS, f"Missing tool access for {mode}"

    def test_all_modes_have_prompts(self) -> None:
        for mode in AgentMode:
            assert mode in MODE_PROMPTS, f"Missing prompt for {mode}"


class TestCodeModeToolAccess:
    """Code mode should have full access (same as BUILD)."""

    def test_allows_read(self) -> None:
        mgr = ModeManager(mode=AgentMode.CODE)
        for tool in READ_TOOLS:
            assert mgr.check_tool_access(tool).allowed, f"CODE should allow {tool}"

    def test_allows_write(self) -> None:
        mgr = ModeManager(mode=AgentMode.CODE)
        for tool in WRITE_TOOLS:
            assert mgr.check_tool_access(tool).allowed, f"CODE should allow {tool}"

    def test_allows_exec(self) -> None:
        mgr = ModeManager(mode=AgentMode.CODE)
        for tool in EXEC_TOOLS:
            assert mgr.check_tool_access(tool).allowed, f"CODE should allow {tool}"

    def test_allows_agent_tools(self) -> None:
        mgr = ModeManager(mode=AgentMode.CODE)
        for tool in AGENT_TOOLS:
            assert mgr.check_tool_access(tool).allowed, f"CODE should allow {tool}"

    def test_tool_access_matches_build(self) -> None:
        assert MODE_TOOL_ACCESS[AgentMode.CODE] == MODE_TOOL_ACCESS[AgentMode.BUILD]


class TestArchitectModeToolAccess:
    """Architect mode: read + markdown write only."""

    def test_allows_read(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        for tool in READ_TOOLS:
            assert mgr.check_tool_access(tool).allowed, f"ARCHITECT should allow {tool}"

    def test_allows_markdown_write(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.check_tool_access(
            "write_file", arguments={"path": "docs/design.md", "content": "# Design"}
        )
        assert result.allowed

    def test_allows_markdown_edit(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.check_tool_access(
            "edit_file", arguments={"file_path": "ARCHITECTURE.md"}
        )
        assert result.allowed

    def test_allows_dot_markdown_extension(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.check_tool_access(
            "write_file", arguments={"path": "notes.markdown", "content": "text"}
        )
        assert result.allowed

    def test_blocks_python_write(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.check_tool_access(
            "write_file", arguments={"path": "src/main.py", "content": "code"}
        )
        assert not result.allowed
        assert "ARCHITECT mode" in result.reason
        assert "markdown" in result.reason.lower()

    def test_blocks_edit_non_markdown(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.check_tool_access(
            "edit_file", arguments={"file_path": "config.yaml"}
        )
        assert not result.allowed
        assert "ARCHITECT mode" in result.reason

    def test_blocks_write_no_path(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.check_tool_access("write_file", arguments={})
        assert not result.allowed

    def test_blocks_write_no_arguments(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.check_tool_access("write_file")
        assert not result.allowed

    def test_blocks_exec(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.check_tool_access("bash", arguments={"command": "ls"})
        assert not result.allowed
        assert "architect mode" in result.reason.lower()

    def test_blocks_agent_tools(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.check_tool_access("spawn_agent")
        assert not result.allowed


class TestAskModeToolAccess:
    """Ask mode: read-only, no writes at all."""

    def test_allows_read(self) -> None:
        mgr = ModeManager(mode=AgentMode.ASK)
        for tool in READ_TOOLS:
            assert mgr.check_tool_access(tool).allowed, f"ASK should allow {tool}"

    def test_blocks_write(self) -> None:
        mgr = ModeManager(mode=AgentMode.ASK)
        for tool in WRITE_TOOLS:
            result = mgr.check_tool_access(tool)
            assert not result.allowed, f"ASK should block {tool}"
            assert "ask mode" in result.reason.lower()

    def test_blocks_exec(self) -> None:
        mgr = ModeManager(mode=AgentMode.ASK)
        result = mgr.check_tool_access("bash", arguments={"command": "echo hi"})
        assert not result.allowed

    def test_blocks_agent_tools(self) -> None:
        mgr = ModeManager(mode=AgentMode.ASK)
        result = mgr.check_tool_access("spawn_agent")
        assert not result.allowed

    def test_blocks_markdown_write(self) -> None:
        """Ask mode blocks ALL writes, including markdown (unlike Architect)."""
        mgr = ModeManager(mode=AgentMode.ASK)
        result = mgr.check_tool_access(
            "write_file", arguments={"path": "notes.md", "content": "text"}
        )
        assert not result.allowed


class TestOrchestrateModeToolAccess:
    """Orchestrate mode: full access."""

    def test_allows_read(self) -> None:
        mgr = ModeManager(mode=AgentMode.ORCHESTRATE)
        for tool in READ_TOOLS:
            assert mgr.check_tool_access(tool).allowed

    def test_allows_write(self) -> None:
        mgr = ModeManager(mode=AgentMode.ORCHESTRATE)
        for tool in WRITE_TOOLS:
            assert mgr.check_tool_access(tool).allowed

    def test_allows_exec(self) -> None:
        mgr = ModeManager(mode=AgentMode.ORCHESTRATE)
        for tool in EXEC_TOOLS:
            assert mgr.check_tool_access(tool).allowed

    def test_allows_agent_tools(self) -> None:
        mgr = ModeManager(mode=AgentMode.ORCHESTRATE)
        for tool in AGENT_TOOLS:
            assert mgr.check_tool_access(tool).allowed

    def test_tool_access_matches_build(self) -> None:
        assert MODE_TOOL_ACCESS[AgentMode.ORCHESTRATE] == MODE_TOOL_ACCESS[AgentMode.BUILD]


class TestRoleModePrompts:
    """Test that each role-based mode has an appropriate prompt."""

    def test_code_prompt(self) -> None:
        mgr = ModeManager(mode=AgentMode.CODE)
        text = mgr.get_system_prompt_supplement()
        assert "CODE" in text
        assert "Full tool access" in text

    def test_architect_prompt(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        text = mgr.get_system_prompt_supplement()
        assert "ARCHITECT" in text
        assert "markdown" in text.lower()

    def test_ask_prompt(self) -> None:
        mgr = ModeManager(mode=AgentMode.ASK)
        text = mgr.get_system_prompt_supplement()
        assert "ASK" in text
        assert "read" in text.lower()

    def test_orchestrate_prompt(self) -> None:
        mgr = ModeManager(mode=AgentMode.ORCHESTRATE)
        text = mgr.get_system_prompt_supplement()
        assert "ORCHESTRATE" in text
        assert "subtask" in text.lower()


class TestModeModelPreferences:
    """Test per-mode model preference get/set."""

    def test_default_is_none(self) -> None:
        mgr = ModeManager()
        assert mgr.get_mode_model() is None

    def test_set_and_get(self) -> None:
        mgr = ModeManager()
        mgr.set_mode_model(AgentMode.CODE, "claude-opus-4-20250514")
        assert mgr.get_mode_model(AgentMode.CODE) == "claude-opus-4-20250514"

    def test_set_with_string(self) -> None:
        mgr = ModeManager()
        mgr.set_mode_model("architect", "claude-sonnet-4-20250514")
        assert mgr.get_mode_model(AgentMode.ARCHITECT) == "claude-sonnet-4-20250514"

    def test_get_uses_current_mode(self) -> None:
        mgr = ModeManager(mode=AgentMode.ASK)
        mgr.set_mode_model(AgentMode.ASK, "claude-haiku-35")
        assert mgr.get_mode_model() == "claude-haiku-35"

    def test_get_unset_mode_returns_none(self) -> None:
        mgr = ModeManager()
        mgr.set_mode_model(AgentMode.CODE, "some-model")
        assert mgr.get_mode_model(AgentMode.ARCHITECT) is None

    def test_multiple_modes_independent(self) -> None:
        mgr = ModeManager()
        mgr.set_mode_model(AgentMode.CODE, "model-a")
        mgr.set_mode_model(AgentMode.ASK, "model-b")
        assert mgr.get_mode_model(AgentMode.CODE) == "model-a"
        assert mgr.get_mode_model(AgentMode.ASK) == "model-b"


class TestModeSwitchingBetweenOldAndNew:
    """Test switching between original and role-based modes."""

    def test_build_to_code(self) -> None:
        mgr = ModeManager()
        result = mgr.switch_mode("code")
        assert mgr.mode == AgentMode.CODE
        assert "code" in result.lower()

    def test_code_to_architect(self) -> None:
        mgr = ModeManager(mode=AgentMode.CODE)
        result = mgr.switch_mode(AgentMode.ARCHITECT)
        assert mgr.mode == AgentMode.ARCHITECT
        assert "architect" in result.lower()

    def test_architect_to_debug(self) -> None:
        mgr = ModeManager(mode=AgentMode.ARCHITECT)
        result = mgr.switch_mode("debug")
        assert mgr.mode == AgentMode.DEBUG
        assert "debug" in result.lower()

    def test_ask_to_build(self) -> None:
        mgr = ModeManager(mode=AgentMode.ASK)
        mgr.switch_mode("build")
        assert mgr.mode == AgentMode.BUILD

    def test_orchestrate_to_plan(self) -> None:
        mgr = ModeManager(mode=AgentMode.ORCHESTRATE)
        mgr.switch_mode("plan")
        assert mgr.mode == AgentMode.PLAN

    def test_previous_mode_works_with_new_modes(self) -> None:
        mgr = ModeManager()
        mgr.switch_mode("code")
        mgr.switch_mode("architect")
        mgr.previous_mode()
        assert mgr.mode == AgentMode.CODE
        mgr.previous_mode()
        assert mgr.mode == AgentMode.BUILD

    def test_history_tracks_new_modes(self) -> None:
        mgr = ModeManager()
        mgr.switch_mode("orchestrate")
        mgr.switch_mode("ask")
        assert mgr._mode_history == [AgentMode.BUILD, AgentMode.ORCHESTRATE]


class TestSlashCommandShortcuts:
    """Test that /code, /architect, /ask, /orchestrate route correctly.

    These tests verify the command routing logic by calling handle_command.
    """

    @pytest.mark.asyncio
    async def test_code_command(self) -> None:
        from unittest.mock import MagicMock

        from attocode.commands import handle_command
        from attocode.integrations.utilities.mode_manager import ModeManager

        agent = MagicMock()
        ctx = MagicMock()
        mode_mgr = ModeManager()
        ctx.mode_manager = mode_mgr
        agent.context = ctx

        result = await handle_command("/code", agent=agent)
        assert mode_mgr.mode == AgentMode.CODE

    @pytest.mark.asyncio
    async def test_architect_command(self) -> None:
        from unittest.mock import MagicMock

        from attocode.commands import handle_command
        from attocode.integrations.utilities.mode_manager import ModeManager

        agent = MagicMock()
        ctx = MagicMock()
        mode_mgr = ModeManager()
        ctx.mode_manager = mode_mgr
        agent.context = ctx

        result = await handle_command("/architect", agent=agent)
        assert mode_mgr.mode == AgentMode.ARCHITECT

    @pytest.mark.asyncio
    async def test_ask_command(self) -> None:
        from unittest.mock import MagicMock

        from attocode.commands import handle_command
        from attocode.integrations.utilities.mode_manager import ModeManager

        agent = MagicMock()
        ctx = MagicMock()
        mode_mgr = ModeManager()
        ctx.mode_manager = mode_mgr
        agent.context = ctx

        result = await handle_command("/ask", agent=agent)
        assert mode_mgr.mode == AgentMode.ASK

    @pytest.mark.asyncio
    async def test_orchestrate_command(self) -> None:
        from unittest.mock import MagicMock

        from attocode.commands import handle_command
        from attocode.integrations.utilities.mode_manager import ModeManager

        agent = MagicMock()
        ctx = MagicMock()
        mode_mgr = ModeManager()
        ctx.mode_manager = mode_mgr
        agent.context = ctx

        result = await handle_command("/orchestrate", agent=agent)
        assert mode_mgr.mode == AgentMode.ORCHESTRATE
