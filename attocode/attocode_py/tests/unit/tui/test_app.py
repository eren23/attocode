"""Tests for the main TUI app."""

from __future__ import annotations

import pytest

from attocode.tui.app import AttocodeApp
from attocode.tui.events import (
    AgentCompleted,
    AgentStarted,
    IterationUpdate,
    StatusUpdate,
    ToolCompleted,
    ToolStarted,
)
from attocode.tui.widgets.input_area import PromptInput
from attocode.tui.widgets.message_log import MessageLog
from attocode.tui.widgets.status_bar import StatusBar
from attocode.tui.widgets.tool_calls import ToolCallsPanel


class TestAttocodeAppComposition:
    """Test app composition without running Textual."""

    @pytest.mark.asyncio
    async def test_app_creates(self) -> None:
        app = AttocodeApp()
        assert app is not None
        assert app.approval_bridge is not None
        assert app.budget_bridge is not None

    @pytest.mark.asyncio
    async def test_app_with_callbacks(self) -> None:
        submitted = []
        cancelled = []
        app = AttocodeApp(
            on_submit=lambda v: submitted.append(v),
            on_cancel=lambda: cancelled.append(True),
            model_name="claude-sonnet-4-20250514",
            git_branch="main",
        )
        assert app._model_name == "claude-sonnet-4-20250514"
        assert app._git_branch == "main"


class TestAttocodeAppPilot:
    """Test app behavior using Textual's async pilot."""

    @pytest.mark.asyncio
    async def test_app_mounts(self) -> None:
        app = AttocodeApp()
        async with app.run_test() as pilot:
            # Verify widgets are mounted
            assert app.query_one("#message-log", MessageLog)
            assert app.query_one("#tool-panel", ToolCallsPanel)
            assert app.query_one("#input-area", PromptInput)
            assert app.query_one("#status-bar", StatusBar)

    @pytest.mark.asyncio
    async def test_status_bar_initial(self) -> None:
        app = AttocodeApp(model_name="test-model", git_branch="feat/x")
        async with app.run_test() as pilot:
            status = app.query_one("#status-bar", StatusBar)
            assert status.mode == "ready"
            assert status.model_name == "test-model"
            assert status.git_branch == "feat/x"

    @pytest.mark.asyncio
    async def test_agent_lifecycle(self) -> None:
        app = AttocodeApp()
        async with app.run_test() as pilot:
            # Start agent
            app.post_message(AgentStarted())
            await pilot.pause()

            status = app.query_one("#status-bar", StatusBar)
            assert status.mode != "ready"

            # Complete agent
            app.post_message(AgentCompleted(success=True, response="Done"))
            await pilot.pause()

            assert status.mode == "ready"

    @pytest.mark.asyncio
    async def test_tool_lifecycle(self) -> None:
        app = AttocodeApp()
        async with app.run_test() as pilot:
            app.post_message(AgentStarted())
            await pilot.pause()

            # Tool start
            app.post_message(ToolStarted(tool_id="t1", name="read_file", args={"path": "x.py"}))
            await pilot.pause()

            status = app.query_one("#status-bar", StatusBar)
            assert "read_file" in status.mode

            # Tool complete
            app.post_message(ToolCompleted(tool_id="t1", name="read_file", result="ok"))
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_iteration_update(self) -> None:
        app = AttocodeApp()
        async with app.run_test() as pilot:
            app.post_message(IterationUpdate(iteration=5))
            await pilot.pause()

            status = app.query_one("#status-bar", StatusBar)
            assert status.iteration == 5

    @pytest.mark.asyncio
    async def test_status_update(self) -> None:
        app = AttocodeApp()
        async with app.run_test() as pilot:
            app.post_message(StatusUpdate(text="compacting"))
            await pilot.pause()

            status = app.query_one("#status-bar", StatusBar)
            assert status.mode == "compacting"

    @pytest.mark.asyncio
    async def test_clear_screen(self) -> None:
        app = AttocodeApp()
        async with app.run_test() as pilot:
            log = app.query_one("#message-log", MessageLog)
            log.add_system_message("Test message")

            await pilot.press("ctrl+l")
            await pilot.pause()
            # After clear, log should be empty (no assertion on content, just no crash)

    @pytest.mark.asyncio
    async def test_public_api_methods(self) -> None:
        app = AttocodeApp()
        async with app.run_test() as pilot:
            # These should not crash
            app.add_system_message("hello")
            app.update_budget(0.5)
            app.update_context(0.3)

            status = app.query_one("#status-bar", StatusBar)
            assert status.budget_pct == pytest.approx(0.5)
            assert status.context_pct == pytest.approx(0.3)
