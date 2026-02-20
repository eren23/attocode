"""Main Textual TUI application for Attocode."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Footer, Static

from attocode.tui.bridges.approval_bridge import ApprovalBridge, BudgetBridge
from attocode.tui.dialogs.approval import ApprovalDialog, ApprovalResult
from attocode.tui.dialogs.budget import BudgetDialog
from attocode.tui.events import (
    AgentCompleted,
    AgentStarted,
    ApprovalRequired,
    BudgetWarning,
    IterationUpdate,
    LLMCompleted,
    LLMStarted,
    LLMStreamChunk,
    LLMStreamEnd,
    LLMStreamStart,
    StatusUpdate,
    SwarmStatusUpdate,
    ToolCompleted,
    ToolStarted,
)
from attocode.tui.widgets.agents_panel import AgentsPanel
from attocode.tui.widgets.input_area import PromptInput
from attocode.tui.widgets.message_log import MessageLog
from attocode.tui.widgets.plan_panel import PlanPanel
from attocode.tui.widgets.status_bar import StatusBar
from attocode.tui.widgets.streaming_buffer import StreamingBuffer
from attocode.tui.widgets.swarm_panel import SwarmPanel
from attocode.tui.widgets.tasks_panel import TasksPanel
from attocode.tui.widgets.thinking_panel import ThinkingPanel
from attocode.tui.widgets.tool_calls import ToolCallInfo, ToolCallsPanel

# Path to TCSS files
_STYLES_DIR = Path(__file__).parent / "styles"

_TYPING_FRAMES = (".  ", ".. ", "...", "   ")


class AttocodeApp(App):
    """Main TUI application for Attocode.

    Composes the message log, tool calls panel, input area,
    status bar, and optional panels (plan, tasks, agents).
    Handles keyboard shortcuts and dialog bridges.
    """

    CSS_PATH = [
        _STYLES_DIR / "app.tcss",
        _STYLES_DIR / "dialogs.tcss",
    ]

    TITLE = "Attocode"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+l", "clear_screen", "Clear", show=True),
        Binding("ctrl+p", "command_palette", "Help", show=True),
        Binding("ctrl+y", "copy_last", "Copy", show=True),
        Binding("escape", "cancel", "Cancel", show=False),
        # Alt-key toggles (using option-key unicode on macOS)
        Binding("ctrl+t", "toggle_tools", "Toggle Tools", show=False),
        Binding("ctrl+w", "toggle_swarm", "Swarm", show=False),
    ]

    def __init__(
        self,
        on_submit: Any = None,
        on_cancel: Any = None,
        model_name: str = "",
        git_branch: str = "",
        agent: Any = None,
        approval_bridge: ApprovalBridge | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        self._processing = False
        self._exit_pressed = False
        self._agent = agent

        # Bridges — use externally provided or create internal
        self.approval_bridge = approval_bridge or ApprovalBridge()
        self.budget_bridge = BudgetBridge()

        # Initial state
        self._model_name = model_name
        self._git_branch = git_branch

        # Streaming state
        self._streamed_response = False
        self._last_response = ""

        # Typing indicator state
        self._typing_timer: Timer | None = None
        self._typing_frame_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="main-container"):
            yield MessageLog(id="message-log")
            yield Static("", id="typing-indicator")
            yield StreamingBuffer(id="streaming-buffer")
            yield ThinkingPanel(id="thinking-panel")
            yield ToolCallsPanel(id="tool-panel")
            yield PlanPanel(id="plan-panel")
            yield TasksPanel(id="tasks-panel")
            yield AgentsPanel(id="agents-panel")
            yield SwarmPanel(id="swarm-panel")
        yield PromptInput(id="input-area")
        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize on mount."""
        status = self.query_one("#status-bar", StatusBar)
        status.model_name = self._model_name
        status.git_branch = self._git_branch

        # Set up bridge handlers
        self.approval_bridge.set_handler(self._show_approval_dialog)
        self.budget_bridge.set_handler(self._show_budget_dialog)

        # Welcome message
        log = self.query_one("#message-log", MessageLog)
        welcome = f"Attocode ({self._model_name or 'default model'})"
        if self._git_branch:
            welcome += f" on {self._git_branch}"
        welcome += "\nType a prompt to start, or /help for commands."
        log.add_system_message(welcome)

        # Focus input
        self.query_one("#input-area", PromptInput).focus_input()

    # --- Typing indicator ---

    def _start_typing_indicator(self) -> None:
        """Show animated 'Agent is thinking...' indicator."""
        indicator = self.query_one("#typing-indicator", Static)
        indicator.add_class("visible")
        self._typing_frame_index = 0
        self._update_typing_text()
        if self._typing_timer is None:
            self._typing_timer = self.set_interval(0.4, self._advance_typing)

    def _stop_typing_indicator(self) -> None:
        """Hide typing indicator."""
        if self._typing_timer is not None:
            self._typing_timer.stop()
            self._typing_timer = None
        try:
            indicator = self.query_one("#typing-indicator", Static)
            indicator.remove_class("visible")
            indicator.update("")
        except Exception:
            pass

    def _advance_typing(self) -> None:
        """Advance typing dots animation."""
        self._typing_frame_index = (self._typing_frame_index + 1) % len(_TYPING_FRAMES)
        self._update_typing_text()

    def _update_typing_text(self) -> None:
        """Update the typing indicator text."""
        try:
            from rich.text import Text
            indicator = self.query_one("#typing-indicator", Static)
            text = Text()
            text.append("\u283f ", style="blue")
            text.append("Agent is thinking", style="dim italic")
            text.append(_TYPING_FRAMES[self._typing_frame_index], style="dim italic")
            indicator.update(text)
        except Exception:
            pass

    # --- Message handlers ---

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Handle user prompt submission."""
        if self._processing:
            return

        text = event.value

        # Check for slash commands
        from attocode.commands import is_command
        if is_command(text):
            self._handle_slash_command(text)
            return

        log = self.query_one("#message-log", MessageLog)
        log.add_user_message(text)

        if self._on_submit:
            self._processing = True
            self._streamed_response = False
            self.query_one("#input-area", PromptInput).set_enabled(False)
            self.query_one("#status-bar", StatusBar).start_processing()
            self._start_typing_indicator()
            self._on_submit(text)

    def _handle_slash_command(self, text: str) -> None:
        """Handle a slash command synchronously."""
        import asyncio
        from attocode.commands import handle_command

        log = self.query_one("#message-log", MessageLog)
        log.add_user_message(text)

        async def _run() -> None:
            result = await handle_command(text, agent=self._agent, app=self)
            log.add_system_message(result.output)

        asyncio.ensure_future(_run())

    def on_agent_started(self, event: AgentStarted) -> None:
        """Agent execution started."""
        self._processing = True
        self._streamed_response = False
        self.query_one("#input-area", PromptInput).set_enabled(False)
        self.query_one("#status-bar", StatusBar).start_processing()
        self._start_typing_indicator()

    def on_agent_completed(self, event: AgentCompleted) -> None:
        """Agent execution completed."""
        self._processing = False
        self._stop_typing_indicator()
        log = self.query_one("#message-log", MessageLog)

        # Only add the message if we didn't already stream it
        if not self._streamed_response:
            if event.success:
                log.add_assistant_message(event.response)
                self._last_response = event.response
            else:
                log.add_error_message(event.error or "Agent failed")
        else:
            # Error case even if we streamed
            if not event.success and event.error:
                log.add_error_message(event.error)

        self._streamed_response = False
        self.query_one("#input-area", PromptInput).set_enabled(True)
        self.query_one("#status-bar", StatusBar).stop_processing()
        self.query_one("#tool-panel", ToolCallsPanel).clear_calls()
        self.query_one("#input-area", PromptInput).focus_input()

    def on_tool_started(self, event: ToolStarted) -> None:
        """Tool call started."""
        self._stop_typing_indicator()
        panel = self.query_one("#tool-panel", ToolCallsPanel)
        panel.add_call(
            ToolCallInfo(
                tool_id=event.tool_id,
                name=event.name,
                args=event.args,
                status="running",
            )
        )
        self.query_one("#status-bar", StatusBar).mode = f"calling {event.name}"
        log = self.query_one("#message-log", MessageLog)
        log.add_tool_message(event.name, "started")

    def on_tool_completed(self, event: ToolCompleted) -> None:
        """Tool call completed."""
        panel = self.query_one("#tool-panel", ToolCallsPanel)
        status = "error" if event.error else "completed"
        panel.update_call(
            event.tool_id,
            status=status,
            result=event.result,
            error=event.error,
        )
        self.query_one("#status-bar", StatusBar).mode = "thinking"
        if event.error:
            log = self.query_one("#message-log", MessageLog)
            log.add_tool_message(event.name, "error")

    def on_llm_started(self, event: LLMStarted) -> None:
        """LLM call started."""
        self._start_typing_indicator()
        self.query_one("#status-bar", StatusBar).mode = "thinking"

    def on_llm_completed(self, event: LLMCompleted) -> None:
        """LLM call completed."""
        status = self.query_one("#status-bar", StatusBar)
        status.cost += event.cost
        if self._agent:
            try:
                status.budget_pct = self._agent.get_budget_usage()
            except Exception:
                pass
            try:
                ctx = self._agent.context
                if ctx and ctx.compaction_manager:
                    check = ctx.compaction_manager.check(ctx.messages)
                    status.context_pct = check.usage_fraction
            except Exception:
                pass

    # --- Streaming handlers ---

    def on_llm_stream_start(self, event: LLMStreamStart) -> None:
        """LLM streaming started — show streaming buffer."""
        self._stop_typing_indicator()
        self.query_one("#streaming-buffer", StreamingBuffer).start()
        self.query_one("#thinking-panel", ThinkingPanel).start_thinking()
        self.query_one("#status-bar", StatusBar).mode = "streaming"

    def on_llm_stream_chunk(self, event: LLMStreamChunk) -> None:
        """A chunk of streaming content arrived."""
        if event.chunk_type == "thinking":
            self.query_one("#thinking-panel", ThinkingPanel).append_thinking(event.content)
        else:
            self.query_one("#streaming-buffer", StreamingBuffer).append_chunk(
                event.content, event.chunk_type
            )

    def on_llm_stream_end(self, event: LLMStreamEnd) -> None:
        """LLM streaming ended — finalize to message log."""
        buffer = self.query_one("#streaming-buffer", StreamingBuffer)
        thinking_panel = self.query_one("#thinking-panel", ThinkingPanel)

        final_text = buffer.get_final_text()
        if final_text:
            log = self.query_one("#message-log", MessageLog)
            log.add_assistant_message(final_text)
            self._streamed_response = True
            self._last_response = final_text

        buffer.stop()
        thinking_panel.stop_thinking()

        # Update cost and budget
        status = self.query_one("#status-bar", StatusBar)
        status.cost += event.cost
        if self._agent:
            try:
                status.budget_pct = self._agent.get_budget_usage()
            except Exception:
                pass
            try:
                ctx = self._agent.context
                if ctx and ctx.compaction_manager:
                    check = ctx.compaction_manager.check(ctx.messages)
                    status.context_pct = check.usage_fraction
            except Exception:
                pass

    # --- Other event handlers ---

    def on_budget_warning(self, event: BudgetWarning) -> None:
        """Budget warning."""
        log = self.query_one("#message-log", MessageLog)
        log.add_system_message(f"Budget: {event.message}")
        self.query_one("#status-bar", StatusBar).budget_pct = event.usage_fraction

    def on_iteration_update(self, event: IterationUpdate) -> None:
        """Iteration counter update."""
        self.query_one("#status-bar", StatusBar).iteration = event.iteration
        if self._agent:
            try:
                self.query_one("#status-bar", StatusBar).budget_pct = self._agent.get_budget_usage()
            except Exception:
                pass

    def on_status_update(self, event: StatusUpdate) -> None:
        """General status update."""
        self.query_one("#status-bar", StatusBar).mode = event.text
        if event.mode == "error":
            self.query_one("#message-log", MessageLog).add_error_message(event.text)
        elif event.mode == "info":
            self.query_one("#message-log", MessageLog).add_system_message(event.text)

    def on_swarm_status_update(self, event: SwarmStatusUpdate) -> None:
        """Swarm status snapshot update."""
        self.query_one("#swarm-panel", SwarmPanel).update_status(event.status)

    # --- Dialog bridges ---

    def _show_approval_dialog(
        self,
        tool_name: str,
        args: dict[str, Any],
        danger_level: str,
        context: str,
    ) -> None:
        """Show the approval dialog."""
        self.query_one("#status-bar", StatusBar).mode = "approving"

        def on_result(result: ApprovalResult) -> None:
            self.approval_bridge.resolve(result)
            if self._processing:
                self.query_one("#status-bar", StatusBar).mode = "thinking"

        self.push_screen(
            ApprovalDialog(tool_name, args, danger_level, context),
            callback=on_result,
        )

    def _show_budget_dialog(
        self,
        current_tokens: int,
        used_pct: float,
        requested_tokens: int,
        reason: str,
    ) -> None:
        """Show the budget extension dialog."""

        def on_result(approved: bool) -> None:
            self.budget_bridge.resolve(approved)

        self.push_screen(
            BudgetDialog(current_tokens, used_pct, requested_tokens, reason),
            callback=on_result,
        )

    # --- Actions ---

    def action_quit(self) -> None:
        """Quit the app (Ctrl+C)."""
        if self._processing and not self._exit_pressed:
            self._exit_pressed = True
            log = self.query_one("#message-log", MessageLog)
            log.add_system_message("Press Ctrl+C again to force quit")
            if self._on_cancel:
                self._on_cancel()
            return
        self.exit()

    def action_clear_screen(self) -> None:
        """Clear the message log (Ctrl+L)."""
        log = self.query_one("#message-log", MessageLog)
        log.clear()
        self.query_one("#tool-panel", ToolCallsPanel).clear_calls()

    def action_cancel(self) -> None:
        """Cancel current operation (Escape)."""
        if self._processing and self._on_cancel:
            self._on_cancel()

    def action_copy_last(self) -> None:
        """Copy the last agent response to the system clipboard (Ctrl+Y)."""
        if not self._last_response:
            self.add_system_message("Nothing to copy")
            return
        try:
            import subprocess
            import sys
            if sys.platform == "darwin":
                subprocess.run(
                    ["pbcopy"], input=self._last_response.encode(), check=True,
                )
            else:
                # Try xclip, then xsel
                try:
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=self._last_response.encode(), check=True,
                    )
                except FileNotFoundError:
                    subprocess.run(
                        ["xsel", "--clipboard", "--input"],
                        input=self._last_response.encode(), check=True,
                    )
            self.add_system_message(f"Copied {len(self._last_response)} chars to clipboard")
        except Exception as e:
            self.add_system_message(f"Copy failed: {e}")

    def action_command_palette(self) -> None:
        """Open the command palette (Ctrl+P)."""
        from attocode.tui.widgets.command_palette import (
            CommandPaletteScreen,
            CommandRegistry,
            register_default_commands,
        )

        registry = CommandRegistry()
        register_default_commands(registry)

        def on_selected(command: str | None) -> None:
            if command:
                self._handle_slash_command(command)

        self.push_screen(CommandPaletteScreen(registry), callback=on_selected)

    def action_toggle_tools(self) -> None:
        """Toggle tool call details."""
        self.query_one("#tool-panel", ToolCallsPanel).toggle_expanded()

    def action_toggle_swarm(self) -> None:
        """Toggle swarm panel visibility."""
        panel = self.query_one("#swarm-panel", SwarmPanel)
        panel.toggle_class("visible")

    # --- Public API ---

    def add_system_message(self, text: str) -> None:
        """Add a system message from outside the event loop."""
        try:
            log = self.query_one("#message-log", MessageLog)
            log.add_system_message(text)
        except Exception:
            pass

    def update_budget(self, budget_pct: float) -> None:
        """Update budget percentage."""
        try:
            self.query_one("#status-bar", StatusBar).budget_pct = budget_pct
        except Exception:
            pass

    def update_context(self, context_pct: float) -> None:
        """Update context percentage."""
        try:
            self.query_one("#status-bar", StatusBar).context_pct = context_pct
        except Exception:
            pass
