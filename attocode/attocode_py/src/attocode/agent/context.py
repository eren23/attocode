"""AgentContext - dependency bundle for the agent execution engine."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from attocode.providers.base import LLMProvider
from attocode.tools.registry import ToolRegistry
from attocode.types.agent import AgentConfig, AgentMetrics
from attocode.types.budget import ExecutionBudget, STANDARD_BUDGET
from attocode.types.events import AgentEvent, EventType
from attocode.types.messages import Message, MessageWithStructuredContent


EventHandler = Callable[[AgentEvent], Any]
ApprovalCallback = Callable[..., Any]  # async (tool_name, args, danger, context) -> ApprovalResult


@dataclass
class AgentContext:
    """Bundle of all dependencies needed by the execution engine.

    This is the single object threaded through the execution loop,
    tool executor, response handler, and completion analyzer.
    """

    # Core dependencies
    provider: LLMProvider
    registry: ToolRegistry
    config: AgentConfig = field(default_factory=AgentConfig)
    budget: ExecutionBudget = field(default_factory=lambda: STANDARD_BUDGET)

    # State
    messages: list[Message | MessageWithStructuredContent] = field(default_factory=list)
    metrics: AgentMetrics = field(default_factory=AgentMetrics)
    iteration: int = 0

    # Cancellation
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    # Event system
    _event_handlers: list[EventHandler] = field(default_factory=list, repr=False)

    # System prompt
    system_prompt: str | None = None

    # Working directory
    working_dir: str = ""

    # Policy engine (optional - if None, all tools are auto-approved)
    policy_engine: Any = None  # PolicyEngine instance

    # Approval callback (optional - for TUI/interactive approval)
    approval_callback: ApprovalCallback | None = None

    # Economics manager (optional - for budget tracking)
    economics: Any = None  # ExecutionEconomicsManager instance

    # Auto-compaction manager (optional)
    compaction_manager: Any = None  # AutoCompactionManager instance

    # Session store (optional)
    session_store: Any = None  # SessionStore instance
    session_id: str | None = None

    # Context engineering tricks (optional)
    recitation_manager: Any = None  # RecitationManager instance
    failure_tracker: Any = None  # FailureTracker instance

    # Learning store (optional)
    learning_store: Any = None  # LearningStore instance

    # Auto-checkpoint (optional)
    auto_checkpoint: Any = None  # AutoCheckpointManager instance

    # MCP server configs (optional)
    mcp_server_configs: list[dict[str, Any]] = field(default_factory=list)

    # Goal (for recitation)
    goal: str | None = None

    # Mode manager (optional - for build/plan/review/debug modes)
    mode_manager: Any = None  # ModeManager instance

    # File change tracker (optional - for undo capability)
    file_change_tracker: Any = None  # FileChangeTracker instance

    # Thread manager (optional - for conversation forking)
    thread_manager: Any = None  # ThreadManager instance

    # Trace collector (optional - for execution tracing)
    trace_collector: Any = None  # TraceCollector instance

    def on_event(self, handler: EventHandler) -> None:
        """Register an event handler."""
        self._event_handlers.append(handler)

    def emit(self, event: AgentEvent) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception:
                pass  # Event handlers should not break the loop

    def emit_simple(
        self,
        event_type: EventType,
        **kwargs: Any,
    ) -> None:
        """Emit a simple event with keyword arguments."""
        self.emit(AgentEvent(type=event_type, **kwargs))

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()

    def cancel(self) -> None:
        """Request cancellation of the current execution."""
        self.cancelled.set()

    def check_iteration_budget(self) -> bool:
        """Check if we've exceeded the iteration limit.

        Returns True if we should continue, False if we should stop.
        """
        max_iter = self.budget.max_iterations or self.config.max_iterations
        if max_iter and self.iteration >= max_iter:
            return False
        return True

    def check_token_budget(self) -> bool:
        """Check if we've exceeded the token budget.

        Returns True if we should continue, False if we should stop.
        """
        if self.budget.max_tokens and self.metrics.total_tokens >= self.budget.max_tokens:
            return False
        return True

    def add_message(self, message: Message | MessageWithStructuredContent) -> None:
        """Add a message to the conversation history."""
        self.messages.append(message)

    def add_messages(self, messages: list[Message | MessageWithStructuredContent]) -> None:
        """Add multiple messages to the conversation history."""
        self.messages.extend(messages)
