"""Agent event hooks for TUI updates.

Bridges agent events (from the EventBus/EventType system) to
Textual Messages for reactive TUI updates. Handles debouncing,
batching, and event filtering.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

from attocode.tui.events import (
    AgentCompleted,
    AgentStarted,
    BudgetWarning,
    CacheStats,
    CompactionCompleted,
    DoomLoopWarning,
    IterationUpdate,
    LLMCompleted,
    LLMStarted,
    LLMStreamChunk,
    LLMStreamEnd,
    LLMStreamStart,
    PhaseTransition,
    StatusUpdate,
    SwarmStatusUpdate,
    ToolCompleted,
    ToolStarted,
)
from attocode.types.events import EventType


class EventFilterLevel(StrEnum):
    """How much event detail to show in the TUI."""

    MINIMAL = "minimal"     # Only errors and completions
    NORMAL = "normal"       # Standard tool/LLM events
    VERBOSE = "verbose"     # All events including debug
    DEBUG = "debug"         # Everything, including internal state


@dataclass(slots=True)
class EventStats:
    """Statistics about events processed."""

    total_events: int = 0
    events_by_type: dict[str, int] = field(default_factory=dict)
    events_dropped: int = 0
    last_event_time: float = 0.0


@dataclass(slots=True)
class DebouncedEvent:
    """An event waiting to be dispatched after a debounce period."""

    event_type: str
    data: dict[str, Any]
    timestamp: float
    dispatch_at: float


class AgentEventBridge:
    """Bridges agent events to TUI message dispatch.

    Subscribes to the agent's EventBus and translates events into
    Textual Messages that widgets can react to.

    Args:
        post_message: Callable to post a Textual Message (typically app.post_message).
        filter_level: How much detail to show.
        debounce_ms: Debounce interval for high-frequency events.
    """

    def __init__(
        self,
        post_message: Callable[..., Any],
        *,
        filter_level: EventFilterLevel = EventFilterLevel.NORMAL,
        debounce_ms: float = 100.0,
    ) -> None:
        self._post = post_message
        self._filter_level = filter_level
        self._debounce_ms = debounce_ms
        self._stats = EventStats()
        self._debounce_queue: dict[str, DebouncedEvent] = {}
        self._debounce_task: asyncio.Task[None] | None = None
        self._running = False
        self._handlers: dict[str, Callable[..., Any]] = {
            EventType.START.value: self._on_agent_started,
            EventType.COMPLETE.value: self._on_agent_completed,
            EventType.ERROR.value: self._on_agent_error,
            EventType.TOOL_START.value: self._on_tool_started,
            EventType.TOOL_COMPLETE.value: self._on_tool_completed,
            EventType.TOOL_ERROR.value: self._on_tool_error,
            EventType.LLM_START.value: self._on_llm_started,
            EventType.LLM_COMPLETE.value: self._on_llm_completed,
            EventType.BUDGET_WARNING.value: self._on_budget_warning,
            EventType.BUDGET_EXHAUSTED.value: self._on_budget_exhausted,
            EventType.ITERATION.value: self._on_iteration,
            EventType.SWARM_START.value: self._on_swarm_status,
            EventType.COMPACTION_START.value: self._on_compaction,
            EventType.COMPACTION_COMPLETE.value: self._on_compaction_done,
            EventType.LLM_STREAM_START.value: self._on_llm_stream_start,
            EventType.LLM_STREAM_CHUNK.value: self._on_llm_stream_chunk,
            EventType.LLM_STREAM_END.value: self._on_llm_stream_end,
            EventType.INSIGHT_PHASE_CHANGE.value: self._on_phase_transition,
            EventType.INSIGHT_DOOM_LOOP.value: self._on_doom_loop,
        }

    @property
    def stats(self) -> EventStats:
        return self._stats

    @property
    def filter_level(self) -> EventFilterLevel:
        return self._filter_level

    @filter_level.setter
    def filter_level(self, value: EventFilterLevel) -> None:
        self._filter_level = value

    def start(self) -> None:
        """Start the event bridge (begin processing events)."""
        self._running = True

    def stop(self) -> None:
        """Stop the event bridge."""
        self._running = False
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

    def handle_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Handle an incoming agent event.

        This is the main entry point - call this from the EventBus
        subscription callback.

        Args:
            event_type: The event type string (e.g. "tool.started").
            data: Event data dictionary.
        """
        if not self._running:
            return

        self._stats.total_events += 1
        self._stats.last_event_time = time.monotonic()
        self._stats.events_by_type[event_type] = (
            self._stats.events_by_type.get(event_type, 0) + 1
        )

        # Check filter level
        if not self._should_show(event_type):
            self._stats.events_dropped += 1
            return

        # Route to handler
        handler = self._handlers.get(event_type)
        if handler:
            handler(data or {})

    def _should_show(self, event_type: str) -> bool:
        """Check if an event should be shown at the current filter level."""
        if self._filter_level == EventFilterLevel.DEBUG:
            return True
        if self._filter_level == EventFilterLevel.VERBOSE:
            return True
        if self._filter_level == EventFilterLevel.NORMAL:
            # Skip high-frequency internal events
            return event_type not in {
                "context.check",
                "budget.check",
                "phase.transition",
            }
        # MINIMAL: only errors and completions
        return event_type in {
            EventType.COMPLETE.value,
            EventType.ERROR.value,
            EventType.TOOL_ERROR.value,
            EventType.BUDGET_EXHAUSTED.value,
        }

    # ─── Event handlers ──────────────────────────────────────────────────

    def _on_agent_started(self, data: dict[str, Any]) -> None:
        self._post(AgentStarted())

    def _on_agent_completed(self, data: dict[str, Any]) -> None:
        self._post(AgentCompleted(
            success=data.get("success", True),
            response=data.get("response", ""),
            error=data.get("error"),
        ))

    def _on_agent_error(self, data: dict[str, Any]) -> None:
        self._post(StatusUpdate(
            text=f"Error: {data.get('error', 'unknown')}",
            mode="error",
        ))

    def _on_tool_started(self, data: dict[str, Any]) -> None:
        self._post(ToolStarted(
            tool_id=data.get("tool_id", ""),
            name=data.get("tool_name", ""),
            args=data.get("args"),
        ))

    def _on_tool_completed(self, data: dict[str, Any]) -> None:
        self._post(ToolCompleted(
            tool_id=data.get("tool_id", ""),
            name=data.get("tool_name", ""),
            result=data.get("result"),
            error=data.get("error"),
        ))

    def _on_tool_error(self, data: dict[str, Any]) -> None:
        self._post(ToolCompleted(
            tool_id=data.get("tool_id", ""),
            name=data.get("tool_name", ""),
            error=data.get("error", "unknown error"),
        ))

    def _on_llm_started(self, data: dict[str, Any]) -> None:
        self._post(LLMStarted())

    def _on_llm_completed(self, data: dict[str, Any]) -> None:
        self._post(LLMCompleted(
            tokens=data.get("tokens", 0),
            cost=data.get("cost", 0.0),
        ))
        # Extract and emit cache stats if present
        cache_read = data.get("cache_read_tokens", 0) or data.get("cache_read", 0)
        cache_write = data.get("cache_write_tokens", 0) or data.get("cache_write", 0)
        input_tokens = data.get("input_tokens", 0)
        output_tokens = data.get("output_tokens", 0)
        if cache_read or cache_write or input_tokens or output_tokens:
            self._post(CacheStats(
                cache_read=cache_read,
                cache_write=cache_write,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ))

    def _on_budget_warning(self, data: dict[str, Any]) -> None:
        self._post(BudgetWarning(
            usage_fraction=data.get("usage_fraction", 0.0),
            message=data.get("message", ""),
        ))

    def _on_budget_exhausted(self, data: dict[str, Any]) -> None:
        self._post(StatusUpdate(
            text="Budget exhausted",
            mode="error",
        ))

    def _on_iteration(self, data: dict[str, Any]) -> None:
        self._post(IterationUpdate(
            iteration=data.get("iteration", 0),
        ))

    def _on_swarm_status(self, data: dict[str, Any]) -> None:
        self._post(SwarmStatusUpdate(status=data))

    def _on_llm_stream_start(self, data: dict[str, Any]) -> None:
        self._post(LLMStreamStart())

    def _on_llm_stream_chunk(self, data: dict[str, Any]) -> None:
        content = data.get("content", "")
        chunk_type = data.get("chunk_type", "text")
        if content:
            self._post(LLMStreamChunk(content=content, chunk_type=chunk_type))

    def _on_llm_stream_end(self, data: dict[str, Any]) -> None:
        self._post(LLMStreamEnd(
            tokens=data.get("tokens", 0),
            cost=data.get("cost", 0.0),
        ))

    def _on_compaction(self, data: dict[str, Any]) -> None:
        self._post(StatusUpdate(
            text="Compacting context...",
            mode="info",
        ))

    def _on_compaction_done(self, data: dict[str, Any]) -> None:
        saved = data.get("tokens_saved", 0)
        self._post(StatusUpdate(
            text=f"Compaction complete ({saved:,} tokens saved)",
            mode="info",
        ))
        self._post(CompactionCompleted(
            tokens_saved=saved,
            new_usage=data.get("new_usage", 0.0),
        ))

    def _on_phase_transition(self, data: dict[str, Any]) -> None:
        self._post(PhaseTransition(
            old_phase=data.get("old_phase", ""),
            new_phase=data.get("new_phase", ""),
        ))

    def _on_doom_loop(self, data: dict[str, Any]) -> None:
        self._post(DoomLoopWarning(
            tool_name=data.get("tool_name", ""),
            count=data.get("count", 0),
        ))


# ─── Message pruning ────────────────────────────────────────────────────────

@dataclass(slots=True)
class PruneConfig:
    """Configuration for message pruning in the TUI."""

    max_visible_messages: int = 200
    prune_batch_size: int = 50
    keep_system_messages: bool = True
    keep_recent_count: int = 50


def prune_messages(
    messages: list[Any],
    config: PruneConfig,
) -> list[Any]:
    """Prune old messages for TUI display.

    Keeps system messages and the most recent messages,
    removing the oldest non-system messages when the limit
    is exceeded.

    Args:
        messages: Current message list.
        config: Pruning configuration.

    Returns:
        Pruned message list.
    """
    if len(messages) <= config.max_visible_messages:
        return messages

    # Separate system and non-system messages
    system: list[Any] = []
    non_system: list[Any] = []

    for msg in messages:
        role = getattr(msg, "role", None)
        if config.keep_system_messages and role and str(role) == "system":
            system.append(msg)
        else:
            non_system.append(msg)

    # Keep only the most recent non-system messages
    keep = config.keep_recent_count
    if len(non_system) > keep:
        pruned_non_system = non_system[-keep:]
    else:
        pruned_non_system = non_system

    # Combine: system messages + recent non-system
    return system + pruned_non_system
