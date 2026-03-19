"""Main Textual TUI application for Attocode."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Static

from attocode.tui.bridges.approval_bridge import ApprovalBridge, BudgetBridge
from attocode.tui.bridges.swarm_bridge import SwarmEventMessage
from attocode.tui.dialogs.approval import ApprovalDialog, ApprovalResult
from attocode.tui.dialogs.budget import BudgetDialog
from attocode.tui.screens.dashboard import DashboardScreen
from attocode.tui.screens.swarm_monitor import SwarmMonitorScreen
from attocode.tui.widgets.agent_internals_panel import AgentInternalsPanel
from attocode.tui.widgets.agents_panel import AgentsPanel
from attocode.tui.widgets.dashboard.live_dashboard import LiveTraceAccumulator
from attocode.tui.widgets.input_area import PromptInput
from attocode.tui.widgets.message_log import MessageLog
from attocode.tui.widgets.plan_panel import PlanPanel
from attocode.tui.widgets.status_bar import StatusBar
from attocode.tui.widgets.streaming_buffer import StreamingBuffer
from attocode.tui.widgets.swarm_panel import SwarmPanel
from attocode.tui.widgets.tasks_panel import TasksPanel
from attocode.tui.widgets.thinking_panel import ThinkingPanel
from attocode.tui.widgets.token_sparkline import TokenSparkline
from attocode.tui.widgets.tool_calls import ToolCallInfo, ToolCallsPanel
from attocode.tui.widgets.welcome_banner import WelcomeBanner

if TYPE_CHECKING:
    from textual.timer import Timer

    from attocode.tui.events import (
        AgentCompleted,
        AgentStarted,
        BudgetWarning,
        CacheStats,
        CompactionCompleted,
        DoomLoopWarning,
        IterationUpdate,
        LLMCompleted,
        LLMRetry,
        LLMStarted,
        LLMStreamChunk,
        LLMStreamEnd,
        LLMStreamStart,
        PhaseTransition,
        PlanUpdated,
        StatusUpdate,
        SwarmStatusUpdate,
        ToolCompleted,
        ToolStarted,
    )

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
        _STYLES_DIR / "swarm.tcss",
        _STYLES_DIR / "swarm_dashboard.tcss",
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
        Binding("ctrl+d", "toggle_dashboard", "Dashboard", show=True),
        Binding("ctrl+m", "toggle_swarm_monitor", "Swarm Monitor", show=True),
        Binding("ctrl+s", "swarm_dashboard", "Swarm Dashboard", show=False),
        Binding("ctrl+i", "toggle_internals", "Agent Internals", show=False),
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

        # Token sparkline history (last ~20 LLM calls)
        self._token_history: list[int] = []

        # Live dashboard accumulator (shared with DashboardScreen)
        self._live_accumulator = LiveTraceAccumulator()

        # Typing indicator state
        self._typing_timer: Timer | None = None
        self._typing_frame_index = 0

        # Active tools for AgentInternalsPanel: tool_id -> tool_name
        self._active_tools: dict[str, str] = {}

        # Coalesce high-frequency stream updates to keep the TUI responsive.
        self._pending_stream_text: list[str] = []
        self._pending_thinking_text: list[str] = []
        self._stream_flush_timer: Timer | None = None
        self._stream_chunks_since_window_start = 0
        self._stream_window_started_at = 0.0
        self._stream_chunks_seen_total = 0
        self._coalescing_live_updates = False

        # Rate-limit failure toasts (I4)
        self._last_failure_toast_time: float = 0.0

    def compose(self) -> ComposeResult:
        with Vertical(id="main-container"):
            yield WelcomeBanner(
                model=self._model_name,
                git_branch=self._git_branch,
                version=self._get_version(),
                id="welcome-banner",
            )
            yield MessageLog(id="message-log")
            yield Static("", id="typing-indicator")
            yield StreamingBuffer(id="streaming-buffer")
            yield ThinkingPanel(id="thinking-panel")
            yield ToolCallsPanel(id="tool-panel")
            yield PlanPanel(id="plan-panel")
            yield TasksPanel(id="tasks-panel")
            yield AgentsPanel(id="agents-panel")
            yield SwarmPanel(id="swarm-panel")
            yield AgentInternalsPanel(id="agent-internals")
            # Input + status bar inside the Vertical so they stack
            # (dock:bottom causes overlapping, not stacking)
            yield PromptInput(id="input-area")
            yield StatusBar(id="status-bar")
        yield Footer()

    async def on_unmount(self) -> None:
        """Clean up persistent resources on app teardown."""
        if self._stream_flush_timer is not None:
            self._stream_flush_timer.stop()
            self._stream_flush_timer = None
        # Detach swarm callback before closing agent
        if self._agent and hasattr(self._agent, "set_tui_swarm_callback"):
            self._agent.set_tui_swarm_callback(None)
        if self._agent and hasattr(self._agent, "close"):
            await self._agent.close()

    def on_mount(self) -> None:
        """Initialize on mount."""
        status = self.query_one("#status-bar", StatusBar)
        status.model_name = self._model_name
        status.git_branch = self._git_branch

        # Wire project name, max tokens, and context window from agent
        if self._agent:
            try:
                wd = getattr(self._agent, "working_dir", None)
                if wd:
                    status.project_name = Path(wd).name
            except Exception:
                pass
            try:
                budget = getattr(self._agent, "budget", None)
                if budget and hasattr(budget, "max_tokens"):
                    status.max_tokens = budget.max_tokens
            except Exception:
                pass
            # Set context window from model registry
            try:
                from attocode.providers.base import get_model_context_window
                model_id = getattr(getattr(self._agent, "config", None), "model", "") or self._model_name
                if model_id:
                    status.context_window = get_model_context_window(model_id)
            except Exception:
                pass

        # Prime all status metrics on first paint.
        self._sync_status_metrics(refresh_context_window=True)

        # Set up bridge handlers
        self.approval_bridge.set_handler(self._show_approval_dialog)
        self.budget_bridge.set_handler(self._show_budget_dialog)

        # Wire swarm event callback to push Textual messages
        if self._agent and hasattr(self._agent, "set_tui_swarm_callback"):
            self._agent.set_tui_swarm_callback(
                lambda evt: self.post_message(SwarmEventMessage(evt))
            )

        # Hint below banner
        log = self.query_one("#message-log", MessageLog)
        log.add_system_message("Type a prompt to start, or /help for commands.")

        # Focus input
        self.query_one("#input-area", PromptInput).focus_input()

    def _sync_status_metrics(self, *, refresh_context_window: bool = False) -> None:
        """Sync status bar context+budget values from the active agent."""
        if not self._agent:
            return
        status = self.query_one("#status-bar", StatusBar)
        try:
            budget = getattr(self._agent, "budget", None)
            if budget and hasattr(budget, "max_tokens"):
                status.max_tokens = int(budget.max_tokens)
        except Exception:
            pass
        try:
            ctx = self._agent.context
            if ctx:
                status.total_tokens = int(getattr(ctx.metrics, "total_tokens", 0))
                if ctx.compaction_manager:
                    check = ctx.compaction_manager.check(ctx.messages)
                    status.context_pct = check.usage_fraction
                    status.context_tokens = check.estimated_tokens
        except Exception:
            pass
        try:
            status.budget_pct = self._agent.get_budget_usage()
        except Exception:
            pass
        if refresh_context_window:
            try:
                from attocode.providers.base import get_model_context_window
                model_id = getattr(getattr(self._agent, "config", None), "model", "") or self._model_name
                if model_id:
                    status.context_window = get_model_context_window(model_id)
            except Exception:
                pass

    # --- Theme management ---

    @property
    def active_theme_name(self) -> str:
        """Get the current theme name (string alias safe from Textual's own current_theme)."""
        return self.theme or "textual-dark"

    def set_theme(self, theme_name: str) -> None:
        """Switch the app theme at runtime.

        Supports: dark, light, auto, or any registered Textual theme name.
        """
        theme_map = {
            "dark": "textual-dark",
            "light": "textual-light",
            "auto": "textual-dark",  # Default to dark for auto
        }
        resolved = theme_map.get(theme_name, theme_name)
        self.theme = resolved

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

    # --- Paste / drop handler ---

    def on_paste(self, event: Any) -> None:
        """Intercept paste events so drag-drop works anywhere in the TUI.

        When the user drops a file (or pastes text) outside the input area,
        redirect it to the input TextArea. This ensures image drag-drop
        works regardless of which widget has focus.
        """
        from textual.widgets import TextArea

        # If the input TextArea already has focus, let it handle normally
        if isinstance(self.focused, TextArea):
            return

        # Redirect the pasted text to the input area
        text = getattr(event, "text", "")
        if not text:
            return
        event.prevent_default()
        event.stop()
        input_area = self.query_one("#input-area", PromptInput)
        input_area.focus_input()
        ta = input_area.query_one("#prompt-input", TextArea)
        ta.insert(text)

    # --- Message handlers ---

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Handle user prompt submission."""
        if self._processing:
            return

        text = event.value
        images = event.images

        # Hide welcome banner on first interaction
        self._hide_welcome_banner()

        # Check for slash commands (but not file paths that start with /)
        from attocode.commands import is_command
        if is_command(text) and not images:
            # Guard: file-system paths like /Users/... aren't slash commands
            first_word = text.strip().split()[0] if text.strip() else ""
            if not (first_word.startswith("/") and ("/" in first_word[1:])):
                self._handle_slash_command(text)
                return

        # Vision capability is checked inside ProductionAgent.run() —
        # use pop_image_warning() after completion to surface warnings.
        log = self.query_one("#message-log", MessageLog)
        log.add_user_message(text, images=images or None)

        if self._on_submit:
            self._processing = True
            self._streamed_response = False
            self.query_one("#input-area", PromptInput).set_enabled(False)
            self.query_one("#status-bar", StatusBar).start_processing()
            self._start_typing_indicator()
            self._on_submit(text, images or None)

    def _handle_slash_command(self, text: str) -> None:
        """Handle a slash command synchronously."""
        from attocode.commands import handle_command

        log = self.query_one("#message-log", MessageLog)
        log.add_user_message(text)

        cmd = text.strip().split()[0] if text.strip() else ""

        async def _run() -> None:
            result = await handle_command(text, agent=self._agent, app=self)

            # Intercept /status and /budget for DataTable modal
            if cmd in ("/status", "/budget") and self._agent and result.output:
                rows: list[tuple[str, str]] = []
                for line in result.output.strip().split("\n"):
                    if ":" in line:
                        key, _, val = line.partition(":")
                        rows.append((key.strip(), val.strip()))
                if rows:
                    from attocode.tui.widgets.metrics_table import MetricsScreen
                    self.push_screen(MetricsScreen(cmd.lstrip("/").title(), rows))
                    self._sync_status_metrics()
                    return

            log.add_system_message(result.output)
            self._sync_status_metrics()

        asyncio.ensure_future(_run())

    def on_agent_started(self, event: AgentStarted) -> None:
        """Agent execution started."""
        self._hide_welcome_banner()
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

        # Show image warning if the agent stripped images due to provider/model
        if self._agent:
            image_warning = self._agent.pop_image_warning()
            if image_warning:
                log.add_system_message(image_warning)

        self._streamed_response = False
        self._active_tools.clear()
        self._reset_stream_coalescing()
        self.query_one("#input-area", PromptInput).set_enabled(True)
        self.query_one("#status-bar", StatusBar).stop_processing()
        self.query_one("#tool-panel", ToolCallsPanel).clear_calls()
        self.query_one("#input-area", PromptInput).focus_input()

        # Toast notification
        if event.success:
            self.notify("Task completed", severity="information", timeout=3)

        # Hide sparkline
        try:
            self.query_one("#token-sparkline", TokenSparkline).remove_class("visible")
        except Exception:
            pass

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

        # Track active tools for internals panel (keyed by tool_id)
        self._active_tools[event.tool_id] = event.name
        try:
            internals = self.query_one("#agent-internals", AgentInternalsPanel)
            internals.set_active_tools(list(self._active_tools.values()))
        except Exception:
            pass

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

        # Update active tools for internals panel (keyed by tool_id)
        self._active_tools.pop(event.tool_id, None)
        try:
            internals = self.query_one("#agent-internals", AgentInternalsPanel)
            internals.set_active_tools(list(self._active_tools.values()))
        except Exception:
            pass

        # Feed live dashboard accumulator
        self._live_accumulator.record_tool(event.name, error=bool(event.error))

        # Refresh file change stats
        self._update_file_stats()

    def on_llm_started(self, event: LLMStarted) -> None:
        """LLM call started."""
        self._start_typing_indicator()
        self.query_one("#status-bar", StatusBar).mode = "thinking"

    def on_llm_completed(self, event: LLMCompleted) -> None:
        """LLM call completed."""
        status = self.query_one("#status-bar", StatusBar)
        status.cost += event.cost
        status.total_tokens += event.tokens
        self._sync_status_metrics()

        # Feed live dashboard accumulator
        self._live_accumulator.record_llm(event.tokens, event.cost)

        # Update token sparkline
        self._update_sparkline(event.tokens)

    def on_llm_retry(self, event: LLMRetry) -> None:
        """LLM call is being retried — show status and toast."""
        self.query_one("#status-bar", StatusBar).mode = (
            f"retrying ({event.attempt + 1}/{event.max_retries + 1})"
        )
        self.notify(
            f"LLM retry {event.attempt + 1}/{event.max_retries + 1}: {event.error[:80]}",
            severity="warning",
            timeout=event.delay + 2,
        )

    # --- Streaming handlers ---

    def on_llm_stream_start(self, event: LLMStreamStart) -> None:
        """LLM streaming started — show streaming buffer."""
        self._stop_typing_indicator()
        self._reset_stream_coalescing()
        self.query_one("#streaming-buffer", StreamingBuffer).start()
        self.query_one("#thinking-panel", ThinkingPanel).start_thinking()
        self.query_one("#status-bar", StatusBar).mode = "streaming"

    def on_llm_stream_chunk(self, event: LLMStreamChunk) -> None:
        """A chunk of streaming content arrived."""
        self._record_stream_activity()
        if event.chunk_type == "thinking":
            self._pending_thinking_text.append(event.content)
        else:
            self._pending_stream_text.append(event.content)
        self._maybe_enable_stream_coalescing()

        if self._stream_flush_timer is None:
            self._stream_flush_timer = self.set_timer(0.05, self._flush_stream_chunks)

    def on_llm_stream_end(self, event: LLMStreamEnd) -> None:
        """LLM streaming ended — finalize to message log."""
        self._flush_stream_chunks()
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
        self._reset_stream_coalescing()

        # Feed live dashboard accumulator
        self._live_accumulator.record_llm(event.tokens, event.cost)

        # Update cost, budget, and tokens
        status = self.query_one("#status-bar", StatusBar)
        status.cost += event.cost
        status.total_tokens += event.tokens
        self._sync_status_metrics()

        # Update token sparkline
        self._update_sparkline(event.tokens)

    # --- Other event handlers ---

    def on_budget_warning(self, event: BudgetWarning) -> None:
        """Budget warning."""
        log = self.query_one("#message-log", MessageLog)
        log.add_system_message(f"Budget: {event.message}")
        self.query_one("#status-bar", StatusBar).budget_pct = event.usage_fraction

        # Feed live dashboard accumulator
        self._live_accumulator.budget_warnings += 1
        self._live_accumulator.last_budget_pct = event.usage_fraction

        # Toast notification
        severity = "warning" if event.usage_fraction < 0.9 else "error"
        self.notify(f"Budget at {event.usage_fraction:.0%}", severity=severity, timeout=5)

    def on_iteration_update(self, event: IterationUpdate) -> None:
        """Iteration counter update."""
        self.query_one("#status-bar", StatusBar).iteration = event.iteration
        self._sync_status_metrics()

        # Feed live dashboard accumulator
        self._live_accumulator.record_iteration(event.iteration)

    def on_status_update(self, event: StatusUpdate) -> None:
        """General status update."""
        self.query_one("#status-bar", StatusBar).mode = event.text
        if event.mode == "error":
            self.query_one("#message-log", MessageLog).add_error_message(event.text)
            self.notify(event.text, severity="error", timeout=6)
        elif event.mode == "warning":
            self.query_one("#message-log", MessageLog).add_system_message(event.text)
            self.notify(event.text, severity="warning", timeout=6)
        elif event.mode == "info":
            self.query_one("#message-log", MessageLog).add_system_message(event.text)
        self._sync_status_metrics()

    def on_swarm_status_update(self, event: SwarmStatusUpdate) -> None:
        """Swarm status snapshot update."""
        self.query_one("#swarm-panel", SwarmPanel).update_status(event.status)

        # Update status bar swarm indicator
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            s = event.status or {}
            st = s.get("status", {})
            queue = st.get("queue", {})
            budget = st.get("budget", {})
            phase = st.get("phase", "")

            status_bar.swarm_active = phase not in ("", "idle", "completed", "failed")
            status_bar.swarm_wave = str(st.get("current_wave", ""))
            status_bar.swarm_active_workers = len(st.get("active_workers", []))
            status_bar.swarm_done = queue.get("completed", 0)
            status_bar.swarm_total = queue.get("total", 0)
            status_bar.swarm_cost = budget.get("cost_used", 0.0)
        except Exception:
            pass

    # --- Swarm event handler ---

    def on_swarm_event_message(self, event: SwarmEventMessage) -> None:
        """Route swarm events to message log, toasts, and panel updates."""
        etype = event.event.get("type", "")
        data = event.event.get("data", {})
        log = self.query_one("#message-log", MessageLog)

        # Route key events to message log
        if etype == "swarm.start":
            log.add_swarm_phase("Swarm started", data.get("message", ""))
            # Auto-show swarm panel and hint
            try:
                self.query_one("#swarm-panel", SwarmPanel).add_class("visible")
            except Exception:
                pass
            log.add_system_message("Press Ctrl+S for full swarm dashboard")

        elif etype == "swarm.tasks.loaded":
            tasks = data.get("tasks", [])
            log.add_swarm_phase(
                f"Decomposed into {len(tasks)} tasks",
                f"{data.get('total_waves', '?')} waves",
            )

        elif etype == "swarm.task.dispatched":
            log.add_swarm_dispatch(
                data.get("description", data.get("task_id", "?")),
                worker=data.get("worker_name", ""),
                model=data.get("model", ""),
            )

        elif etype == "swarm.task.completed":
            files = data.get("files_modified") or []
            log.add_swarm_complete(
                data.get("description", data.get("task_id", "?")),
                quality_score=data.get("quality_score"),
                files=files,
            )

        elif etype == "swarm.task.failed":
            desc = data.get("description", data.get("task_id", "?"))
            fm = data.get("failure_mode", "")
            log.add_swarm_failure(desc, error=data.get("error", ""), failure_mode=fm)
            # Rate-limit per-task failure toasts to avoid spam on rapid failures
            import time as _time
            now = _time.time()
            if now - self._last_failure_toast_time > 3.0:
                self._last_failure_toast_time = now
                self.notify(
                    f"Task failed ({fm}): {desc[:40]}" if fm else f"Task failed: {desc[:40]}",
                    severity="error",
                    timeout=8,
                )

        elif etype == "swarm.wave.complete":
            wave = data.get("wave", "?")
            total = data.get("total_waves", "?")
            completed = data.get("completed", 0)
            failed = data.get("failed", 0)
            log.add_swarm_wave(wave, total, completed, failed)
            self.notify(
                f"Wave {wave}/{total}: {completed} done, {failed} failed",
                severity="information",
            )

        elif etype == "swarm.quality.rejected":
            desc = data.get("description", data.get("task_id", "?"))
            score = data.get("score")
            feedback = data.get("feedback", "")
            log.add_swarm_quality_reject(desc, score, feedback)
            self.notify(
                f"Quality rejected ({score}/5): {feedback[:50]}",
                severity="warning",
                timeout=6,
            )

        elif etype == "swarm.hollow_detected":
            streak = data.get("streak", data.get("hollow_streak", 0))
            self.notify(
                f"Hollow completion (streak: {streak})",
                severity="warning",
                timeout=4,
            )

        elif etype == "swarm.model.failover":
            from_model = data.get("from_model", "?")
            to_model = data.get("to_model", "?")
            self.notify(
                f"Failover: {from_model} \u2192 {to_model}",
                severity="warning",
                timeout=4,
            )

        elif etype == "swarm.paused":
            log.add_swarm_phase("Dispatch paused")
            self.notify("Swarm paused", severity="information")

        elif etype == "swarm.resumed":
            log.add_swarm_phase("Dispatch resumed")
            self.notify("Swarm resumed", severity="information")

        elif etype == "swarm.complete":
            log.add_swarm_phase("Swarm completed", data.get("message", ""))
            self.notify("Swarm execution complete!", severity="information", timeout=10)

        # Update SwarmPanel quality stats from event bridge state
        self._update_swarm_panel_from_event(event.event)

    def _flush_stream_chunks(self) -> None:
        """Flush buffered stream chunks into the visible widgets."""
        self._stream_flush_timer = None
        if self._pending_thinking_text:
            self.query_one("#thinking-panel", ThinkingPanel).append_thinking(
                "".join(self._pending_thinking_text)
            )
            self._pending_thinking_text.clear()
        if self._pending_stream_text:
            self.query_one("#streaming-buffer", StreamingBuffer).append_chunk(
                "".join(self._pending_stream_text),
                "text",
            )
            self._pending_stream_text.clear()

    def _record_stream_activity(self) -> None:
        """Track stream event rates and mark the UI as batched under load."""
        now = asyncio.get_running_loop().time()
        if self._stream_window_started_at == 0.0 or now - self._stream_window_started_at > 0.5:
            self._stream_window_started_at = now
            self._stream_chunks_since_window_start = 0
        self._stream_chunks_since_window_start += 1
        self._stream_chunks_seen_total += 1

    def _maybe_enable_stream_coalescing(self) -> None:
        """Enable the batched-live indicator once chunk volume gets high enough."""
        pending_chunks = len(self._pending_stream_text) + len(self._pending_thinking_text)
        if self._coalescing_live_updates:
            return
        if (
            self._stream_chunks_seen_total < 12
            and self._stream_chunks_since_window_start < 12
            and pending_chunks < 8
        ):
            return
        self._coalescing_live_updates = True
        self.query_one("#status-bar", StatusBar).live_updates_coalesced = True
        self.query_one("#message-log", MessageLog).add_system_message(
            "High event rate detected; batching live updates to keep the TUI responsive."
        )

    def _reset_stream_coalescing(self) -> None:
        """Clear batching state after a response finishes."""
        if self._stream_flush_timer is not None:
            self._stream_flush_timer.stop()
            self._stream_flush_timer = None
        self._pending_stream_text.clear()
        self._pending_thinking_text.clear()
        self._stream_chunks_since_window_start = 0
        self._stream_window_started_at = 0.0
        self._stream_chunks_seen_total = 0
        self._coalescing_live_updates = False
        try:
            self.query_one("#status-bar", StatusBar).live_updates_coalesced = False
        except Exception:
            pass

    def _update_swarm_panel_from_event(self, evt: dict) -> None:
        """Push quality stats and start time to SwarmPanel."""
        try:
            panel = self.query_one("#swarm-panel", SwarmPanel)
            etype = evt.get("type", "")
            if etype == "swarm.start" and panel._start_time == 0:
                import time as _time
                panel.set_start_time(evt.get("timestamp", 0) or _time.time())
            # Pull quality_stats from event bridge's public API
            if self._agent and hasattr(self._agent, "event_bridge"):
                bridge = self._agent.event_bridge
                if bridge and hasattr(bridge, "get_live_state"):
                    live_state = bridge.get_live_state()
                    qs = live_state.get("quality_stats", {})
                    if qs:
                        panel.update_quality_stats(qs)
        except Exception:
            pass

    def on_compaction_completed(self, event: CompactionCompleted) -> None:
        """Compaction event — update status bar and internals panel."""
        status = self.query_one("#status-bar", StatusBar)
        status.compaction_count += 1
        try:
            panel = self.query_one("#agent-internals", AgentInternalsPanel)
            panel.record_compaction(event.tokens_saved)
        except Exception:
            pass

    def on_phase_transition(self, event: PhaseTransition) -> None:
        """Economics phase changed."""
        self.query_one("#status-bar", StatusBar).phase = event.new_phase
        try:
            panel = self.query_one("#agent-internals", AgentInternalsPanel)
            panel.update_phase(event.new_phase)
        except Exception:
            pass

    def on_doom_loop_warning(self, event: DoomLoopWarning) -> None:
        """Doom loop warning."""
        self.notify(
            f"Doom loop: {event.tool_name} called {event.count} times",
            severity="warning",
            timeout=5,
        )
        try:
            panel = self.query_one("#agent-internals", AgentInternalsPanel)
            panel.set_doom_loop(event.tool_name, event.count)
        except Exception:
            pass

    def on_cache_stats(self, event: CacheStats) -> None:
        """Cache stats update — update status bar and internals panel."""
        try:
            panel = self.query_one("#agent-internals", AgentInternalsPanel)
            panel.update_cache_stats(
                event.cache_read, event.cache_write,
                event.input_tokens, event.output_tokens,
            )
            # Update status bar cache hit rate
            total = panel.input_tokens + panel.cache_read
            if total > 0:
                self.query_one("#status-bar", StatusBar).cache_hit_rate = (
                    panel.cache_read / total
                )
        except Exception:
            pass

    def on_plan_updated(self, event: PlanUpdated) -> None:
        """Plan data updated — show in PlanPanel."""
        try:
            plan_panel = self.query_one("#plan-panel", PlanPanel)
            plan_panel.set_plan(event.plan)
        except Exception:
            pass

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

    def action_toggle_internals(self) -> None:
        """Toggle agent internals panel (Ctrl+I)."""
        panel = self.query_one("#agent-internals", AgentInternalsPanel)
        panel.toggle_class("visible")

    def action_toggle_tasks(self) -> None:
        """Toggle tasks panel visibility."""
        panel = self.query_one("#tasks-panel", TasksPanel)
        panel.toggle_class("visible")

    def action_toggle_debug(self) -> None:
        """Alias debug toggle to internals panel."""
        self.action_toggle_internals()

    def action_toggle_dashboard(self) -> None:
        """Toggle the dashboard screen (Ctrl+D)."""
        trace_dir = ""
        if self._agent:
            wd = getattr(self._agent, "working_dir", "") or ""
            if wd:
                trace_dir = str(Path(wd) / ".attocode" / "traces")
        self.push_screen(
            DashboardScreen(
                agent=self._agent,
                trace_dir=trace_dir,
                accumulator=self._live_accumulator,
            )
        )

    def action_toggle_swarm_monitor(self) -> None:
        """Open fleet-level swarm monitor (Ctrl+M)."""
        root = "."
        if self._agent:
            wd = getattr(self._agent, "working_dir", "") or ""
            if wd:
                root = wd
        self.push_screen(SwarmMonitorScreen(root=root))

    def action_swarm_dashboard(self) -> None:
        """Open the AoT swarm dashboard (Ctrl+S)."""
        from attocode.tui.screens.swarm_dashboard import SwarmDashboardScreen

        state_fn = None
        event_bridge = None
        blackboard = None
        ast_service = None
        orch = None

        if self._agent and hasattr(self._agent, "_swarm_orchestrator"):
            orch = self._agent._swarm_orchestrator
            if orch and hasattr(orch, "get_state"):
                state_fn = orch.get_state
            if orch and hasattr(orch, "event_bridge"):
                event_bridge = orch.event_bridge
            if orch and hasattr(orch, "blackboard"):
                blackboard = orch.blackboard
            if orch and hasattr(orch, "ast_service"):
                ast_service = orch.ast_service

        self.push_screen(SwarmDashboardScreen(
            state_fn=state_fn,
            event_bridge=event_bridge,
            blackboard=blackboard,
            ast_service=ast_service,
            orchestrator=orch,
        ))

    # --- Helpers ---

    def _hide_welcome_banner(self) -> None:
        """Hide the welcome banner."""
        try:
            banner = self.query_one("#welcome-banner", WelcomeBanner)
            banner.display = False
        except Exception:
            pass

    @staticmethod
    def _get_version() -> str:
        """Return the package version string."""
        try:
            from attocode import __version__
            return __version__
        except Exception:
            return "0.1.0"

    def _update_file_stats(self) -> None:
        """Read file change tracker and update status bar file stats."""
        if not self._agent:
            return
        tracker = getattr(self._agent, "_file_change_tracker", None)
        if not tracker or not hasattr(tracker, "changes"):
            return
        try:
            changes = tracker.changes
            paths = {c.path for c in changes if not c.undone}
            added = deleted = 0
            for c in changes:
                if c.undone:
                    continue
                if c.after_content and c.before_content:
                    added += max(0, c.after_content.count("\n") - c.before_content.count("\n"))
                    deleted += max(0, c.before_content.count("\n") - c.after_content.count("\n"))
                elif c.after_content and not c.before_content:
                    added += c.after_content.count("\n") + 1
                elif c.before_content and not c.after_content:
                    deleted += c.before_content.count("\n") + 1
            status = self.query_one("#status-bar", StatusBar)
            status.files_changed = len(paths)
            status.lines_added = added
            status.lines_removed = deleted
        except Exception:
            pass

    def _update_sparkline(self, tokens: int) -> None:
        """Append a token count to the sparkline history and update the widget."""
        if tokens <= 0:
            return
        self._token_history.append(tokens)
        if len(self._token_history) > 20:
            self._token_history = self._token_history[-20:]
        try:
            try:
                sparkline = self.query_one("#token-sparkline", TokenSparkline)
            except Exception:
                # First data point — mount inside the Vertical, before the status bar
                sparkline = TokenSparkline(self._token_history, id="token-sparkline")
                status_bar = self.query_one("#status-bar", StatusBar)
                container = self.query_one("#main-container", Vertical)
                container.mount(sparkline, before=status_bar)
            sparkline.data = self._token_history
            sparkline.add_class("visible")
        except Exception:
            pass

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
