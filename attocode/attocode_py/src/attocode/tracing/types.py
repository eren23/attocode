"""Trace event types and data structures.

Defines the full taxonomy of trace events covering all agent execution phases:
sessions, iterations, LLM calls, tool execution, budget management, compaction,
subagent lifecycle, swarm orchestration, planning, quality, and more.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TraceEventKind(StrEnum):
    """Kinds of trace events.

    Covers every significant state transition in the agent lifecycle.
    Organised by subsystem for easy filtering.

    Subsystems:
    - Session: session_start, session_end
    - Iteration: iteration_start, iteration_end
    - LLM: llm_request, llm_response, llm_error, llm_retry
    - Tool: tool_start, tool_end, tool_error, tool_approval
    - Budget: budget_check, budget_warning, budget_exhausted
    - Compaction: compaction_start, compaction_end, context_overflow
    - Subagent: subagent_spawn, subagent_complete, subagent_error, subagent_timeout
    - Swarm: swarm_start, swarm_complete, swarm_wave_*, swarm_task_*
    - Plan: plan_created, plan_step_start, plan_step_complete
    - Quality: quality_check, learning_proposed
    - Error/Recovery: error, recovery
    - Mode: mode_change
    - MCP: mcp_connect, mcp_disconnect
    - File: file_change
    - Checkpoint: checkpoint
    - Custom: custom
    """

    # --- Session lifecycle ---
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # --- Iteration lifecycle ---
    ITERATION_START = "iteration_start"
    ITERATION_END = "iteration_end"

    # --- LLM interactions ---
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    LLM_ERROR = "llm_error"
    LLM_RETRY = "llm_retry"

    # --- Tool execution ---
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"
    TOOL_APPROVAL = "tool_approval"

    # --- Budget management ---
    BUDGET_CHECK = "budget_check"
    BUDGET_WARNING = "budget_warning"
    BUDGET_EXHAUSTED = "budget_exhausted"

    # --- Compaction / context ---
    COMPACTION_START = "compaction_start"
    COMPACTION_END = "compaction_end"
    CONTEXT_OVERFLOW = "context_overflow"

    # --- Subagent lifecycle ---
    SUBAGENT_SPAWN = "subagent_spawn"
    SUBAGENT_COMPLETE = "subagent_complete"
    SUBAGENT_ERROR = "subagent_error"
    SUBAGENT_TIMEOUT = "subagent_timeout"

    # --- Swarm orchestration ---
    SWARM_START = "swarm_start"
    SWARM_COMPLETE = "swarm_complete"
    SWARM_WAVE_START = "swarm_wave_start"
    SWARM_WAVE_COMPLETE = "swarm_wave_complete"
    SWARM_TASK_START = "swarm_task_start"
    SWARM_TASK_COMPLETE = "swarm_task_complete"
    SWARM_TASK_FAILED = "swarm_task_failed"

    # --- Planning ---
    PLAN_CREATED = "plan_created"
    PLAN_STEP_START = "plan_step_start"
    PLAN_STEP_COMPLETE = "plan_step_complete"

    # --- Quality / Learning ---
    QUALITY_CHECK = "quality_check"
    LEARNING_PROPOSED = "learning_proposed"

    # --- Error and recovery ---
    ERROR = "error"
    RECOVERY = "recovery"

    # --- Mode ---
    MODE_CHANGE = "mode_change"

    # --- MCP ---
    MCP_CONNECT = "mcp_connect"
    MCP_DISCONNECT = "mcp_disconnect"

    # --- File system ---
    FILE_CHANGE = "file_change"

    # --- Checkpoint ---
    CHECKPOINT = "checkpoint"

    # --- Extensibility ---
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# Category grouping
# ---------------------------------------------------------------------------

class TraceEventCategory(StrEnum):
    """Broad categories for trace event filtering and grouping."""

    SESSION = "session"
    ITERATION = "iteration"
    LLM = "llm"
    TOOL = "tool"
    BUDGET = "budget"
    COMPACTION = "compaction"
    SUBAGENT = "subagent"
    SWARM = "swarm"
    PLAN = "plan"
    QUALITY = "quality"
    ERROR = "error"
    MODE = "mode"
    MCP = "mcp"
    FILE = "file"
    CHECKPOINT = "checkpoint"
    CUSTOM = "custom"


#: Mapping from trace event kind to its category.
TRACE_EVENT_CATEGORIES: dict[TraceEventKind, TraceEventCategory] = {}

# Build the mapping from prefix conventions.
for _kind in TraceEventKind:
    _val = _kind.value
    if _val.startswith("session_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.SESSION
    elif _val.startswith("iteration_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.ITERATION
    elif _val.startswith("llm_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.LLM
    elif _val.startswith("tool_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.TOOL
    elif _val.startswith("budget_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.BUDGET
    elif _val.startswith(("compaction_", "context_")):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.COMPACTION
    elif _val.startswith("subagent_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.SUBAGENT
    elif _val.startswith("swarm_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.SWARM
    elif _val.startswith("plan_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.PLAN
    elif _val.startswith(("quality_", "learning_")):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.QUALITY
    elif _val in ("error", "recovery"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.ERROR
    elif _val.startswith("mode_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.MODE
    elif _val.startswith("mcp_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.MCP
    elif _val.startswith("file_"):
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.FILE
    elif _val == "checkpoint":
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.CHECKPOINT
    else:
        TRACE_EVENT_CATEGORIES[_kind] = TraceEventCategory.CUSTOM


def get_trace_event_category(kind: TraceEventKind) -> TraceEventCategory:
    """Return the category for *kind*, falling back to CUSTOM."""
    return TRACE_EVENT_CATEGORIES.get(kind, TraceEventCategory.CUSTOM)


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TraceEvent:
    """A single trace event recorded during agent execution.

    Every event carries an *event_id* (UUID-based), a *kind* tag, and a
    *timestamp* (epoch seconds).  Optional fields capture iteration context,
    hierarchical parent linkage, duration, and an open *data* dict for
    kind-specific payloads.
    """

    kind: TraceEventKind
    timestamp: float
    session_id: str
    event_id: str = ""
    iteration: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    parent_event_id: str | None = None
    duration_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = _short_uuid()

    @property
    def category(self) -> TraceEventCategory:
        """The broad category this event belongs to."""
        return get_trace_event_category(self.kind)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for JSON encoding."""
        d: dict[str, Any] = {
            "event_id": self.event_id,
            "kind": str(self.kind),
            "timestamp": self.timestamp,
            "session_id": self.session_id,
        }
        if self.iteration is not None:
            d["iteration"] = self.iteration
        if self.data:
            d["data"] = self.data
        if self.parent_event_id is not None:
            d["parent_event_id"] = self.parent_event_id
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TraceEvent:
        """Reconstruct a :class:`TraceEvent` from a plain dict.

        Tolerant of missing optional keys so that older JSONL files can still
        be loaded.
        """
        return cls(
            kind=TraceEventKind(raw["kind"]),
            timestamp=float(raw["timestamp"]),
            session_id=str(raw.get("session_id", "")),
            event_id=str(raw.get("event_id", "")),
            iteration=raw.get("iteration"),
            data=raw.get("data", {}),
            parent_event_id=raw.get("parent_event_id"),
            duration_ms=raw.get("duration_ms"),
        )


@dataclass(slots=True)
class TraceSession:
    """Metadata and events for a complete tracing session.

    Populated by :class:`~attocode.tracing.collector.TraceCollector` and can
    be serialised/deserialised for post-hoc analysis.
    """

    session_id: str
    goal: str = ""
    model: str = ""
    start_time: float = 0.0
    end_time: float | None = None
    events: list[TraceEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        """Wall-clock duration of the session in seconds."""
        if self.end_time is None:
            return time.time() - self.start_time if self.start_time else 0.0
        return self.end_time - self.start_time

    @property
    def event_count(self) -> int:
        return len(self.events)


@dataclass(slots=True)
class TraceSummary:
    """Aggregate statistics for a trace session.

    Computed lazily by :meth:`TraceCollector.get_summary`.
    """

    session_id: str
    total_events: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    duration_seconds: float = 0.0
    iterations: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    errors: int = 0
    compactions: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict representation for JSON serialisation."""
        return {
            "session_id": self.session_id,
            "total_events": self.total_events,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "duration_seconds": round(self.duration_seconds, 3),
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "llm_calls": self.llm_calls,
            "errors": self.errors,
            "compactions": self.compactions,
        }


# ---------------------------------------------------------------------------
# Helper: create_trace_event
# ---------------------------------------------------------------------------

def create_trace_event(
    kind: TraceEventKind,
    session_id: str = "",
    *,
    iteration: int | None = None,
    data: dict[str, Any] | None = None,
    parent_event_id: str | None = None,
    duration_ms: float | None = None,
    event_id: str | None = None,
    timestamp: float | None = None,
) -> TraceEvent:
    """Convenience factory for :class:`TraceEvent`.

    Auto-fills *timestamp* (``time.time()``) and *event_id* (short UUID)
    when not supplied.

    Args:
        kind: The trace event kind.
        session_id: Session this event belongs to.
        iteration: Current agent iteration, if applicable.
        data: Arbitrary key-value payload.
        parent_event_id: ID of a parent event for hierarchical traces.
        duration_ms: Duration of the traced operation in milliseconds.
        event_id: Explicit event ID override; generated if ``None``.
        timestamp: Explicit timestamp override; ``time.time()`` if ``None``.

    Returns:
        A fully populated :class:`TraceEvent`.
    """
    return TraceEvent(
        kind=kind,
        timestamp=timestamp if timestamp is not None else time.time(),
        session_id=session_id,
        event_id=event_id or _short_uuid(),
        iteration=iteration,
        data=data or {},
        parent_event_id=parent_event_id,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Mapping helpers: TraceEventKind <-> EventType
# ---------------------------------------------------------------------------

# Lazy import to avoid circular dependency with types.events at module level.
_EVENT_TYPE_TO_KIND: dict[str, TraceEventKind] | None = None


def _build_event_type_mapping() -> dict[str, TraceEventKind]:
    """Build a best-effort mapping from EventType values to TraceEventKind."""
    mapping: dict[str, TraceEventKind] = {
        # --- Execution core (highest-frequency events) ---
        "iteration": TraceEventKind.ITERATION_START,
        "thinking": TraceEventKind.LLM_REQUEST,
        "response": TraceEventKind.LLM_RESPONSE,
        # LLM
        "llm.start": TraceEventKind.LLM_REQUEST,
        "llm.complete": TraceEventKind.LLM_RESPONSE,
        "llm.error": TraceEventKind.LLM_ERROR,
        "llm.retry": TraceEventKind.LLM_RETRY,
        "llm.stream.start": TraceEventKind.LLM_REQUEST,
        "llm.stream.chunk": TraceEventKind.LLM_RESPONSE,
        "llm.stream.end": TraceEventKind.LLM_RESPONSE,
        # Tool
        "tool.start": TraceEventKind.TOOL_START,
        "tool.complete": TraceEventKind.TOOL_END,
        "tool.error": TraceEventKind.TOOL_ERROR,
        "tool.approval.requested": TraceEventKind.TOOL_APPROVAL,
        "tool.approval.granted": TraceEventKind.TOOL_APPROVAL,
        "tool.approval.denied": TraceEventKind.TOOL_APPROVAL,
        "tool.blocked": TraceEventKind.TOOL_ERROR,
        "tool.coerced": TraceEventKind.TOOL_APPROVAL,
        # Budget
        "budget.check": TraceEventKind.BUDGET_CHECK,
        "budget.warning": TraceEventKind.BUDGET_WARNING,
        "budget.exhausted": TraceEventKind.BUDGET_EXHAUSTED,
        "budget.extension.requested": TraceEventKind.BUDGET_WARNING,
        "budget.extension.granted": TraceEventKind.BUDGET_CHECK,
        "budget.extension.denied": TraceEventKind.BUDGET_WARNING,
        # Compaction / context
        "compaction": TraceEventKind.COMPACTION_START,
        "compaction.start": TraceEventKind.COMPACTION_START,
        "compaction.complete": TraceEventKind.COMPACTION_END,
        "compaction.error": TraceEventKind.COMPACTION_END,
        "context.overflow": TraceEventKind.CONTEXT_OVERFLOW,
        "context.breakdown": TraceEventKind.CONTEXT_OVERFLOW,
        # Subagent
        "subagent.spawn": TraceEventKind.SUBAGENT_SPAWN,
        "subagent.complete": TraceEventKind.SUBAGENT_COMPLETE,
        "subagent.error": TraceEventKind.SUBAGENT_ERROR,
        "subagent.timeout.hard_kill": TraceEventKind.SUBAGENT_TIMEOUT,
        "subagent.iteration": TraceEventKind.SUBAGENT_SPAWN,
        "subagent.phase": TraceEventKind.SUBAGENT_SPAWN,
        "subagent.wrapup.started": TraceEventKind.SUBAGENT_COMPLETE,
        "subagent.wrapup.completed": TraceEventKind.SUBAGENT_COMPLETE,
        # Swarm
        "swarm.start": TraceEventKind.SWARM_START,
        "swarm.complete": TraceEventKind.SWARM_COMPLETE,
        "swarm.wave.start": TraceEventKind.SWARM_WAVE_START,
        "swarm.wave.complete": TraceEventKind.SWARM_WAVE_COMPLETE,
        "swarm.task.start": TraceEventKind.SWARM_TASK_START,
        "swarm.task.complete": TraceEventKind.SWARM_TASK_COMPLETE,
        "swarm.task.failed": TraceEventKind.SWARM_TASK_FAILED,
        "swarm.task.queued": TraceEventKind.SWARM_TASK_START,
        "swarm.worker.assigned": TraceEventKind.SWARM_WAVE_START,
        "swarm.worker.released": TraceEventKind.SWARM_WAVE_COMPLETE,
        # Plan
        "plan.created": TraceEventKind.PLAN_CREATED,
        "plan.step.start": TraceEventKind.PLAN_STEP_START,
        "plan.step.complete": TraceEventKind.PLAN_STEP_COMPLETE,
        "plan.approved": TraceEventKind.PLAN_STEP_COMPLETE,
        "plan.rejected": TraceEventKind.PLAN_CREATED,
        "plan.updated": TraceEventKind.PLAN_CREATED,
        # Quality / Learning
        "quality.check": TraceEventKind.QUALITY_CHECK,
        "quality.score": TraceEventKind.QUALITY_CHECK,
        "learning.proposed": TraceEventKind.LEARNING_PROPOSED,
        "learning.approved": TraceEventKind.LEARNING_PROPOSED,
        "learning.rejected": TraceEventKind.LEARNING_PROPOSED,
        "health.check": TraceEventKind.QUALITY_CHECK,
        # Mode
        "mode.changed": TraceEventKind.MODE_CHANGE,
        # MCP
        "mcp.connect": TraceEventKind.MCP_CONNECT,
        "mcp.disconnect": TraceEventKind.MCP_DISCONNECT,
        "mcp.tool.discovered": TraceEventKind.MCP_CONNECT,
        "mcp.tool.call": TraceEventKind.TOOL_START,
        "mcp.tool.error": TraceEventKind.TOOL_ERROR,
        # Session
        "session.checkpoint": TraceEventKind.CHECKPOINT,
        "session.created": TraceEventKind.SESSION_START,
        "session.loaded": TraceEventKind.SESSION_START,
        "session.saved": TraceEventKind.CHECKPOINT,
        "session.resumed": TraceEventKind.SESSION_START,
        "session.forked": TraceEventKind.SESSION_START,
        # Lifecycle
        "start": TraceEventKind.SESSION_START,
        "complete": TraceEventKind.SESSION_END,
        "shutdown": TraceEventKind.SESSION_END,
        "error": TraceEventKind.ERROR,
        # Policy / Permission
        "policy.evaluation": TraceEventKind.TOOL_APPROVAL,
        "policy.override": TraceEventKind.TOOL_APPROVAL,
        "permission.granted": TraceEventKind.TOOL_APPROVAL,
        "permission.denied": TraceEventKind.TOOL_APPROVAL,
        "permission.remembered": TraceEventKind.TOOL_APPROVAL,
        # Resilience
        "resilience.retry": TraceEventKind.RECOVERY,
        "resilience.fallback": TraceEventKind.RECOVERY,
        "circuit_breaker.open": TraceEventKind.ERROR,
        "circuit_breaker.half_open": TraceEventKind.RECOVERY,
        "circuit_breaker.closed": TraceEventKind.RECOVERY,
        # Undo
        "undo.tracked": TraceEventKind.FILE_CHANGE,
        "undo.executed": TraceEventKind.FILE_CHANGE,
        "undo.failed": TraceEventKind.ERROR,
        # Insight (economics)
        "insight.doom_loop": TraceEventKind.BUDGET_WARNING,
        "insight.saturation": TraceEventKind.BUDGET_WARNING,
        "insight.nudge": TraceEventKind.BUDGET_CHECK,
        "insight.phase_change": TraceEventKind.MODE_CHANGE,
    }
    return mapping


def event_type_to_trace_kind(event_type_value: str) -> TraceEventKind:
    """Convert an :class:`EventType` string value to a :class:`TraceEventKind`.

    Falls back to :attr:`TraceEventKind.CUSTOM` for unmapped values.
    """
    global _EVENT_TYPE_TO_KIND  # noqa: PLW0603
    if _EVENT_TYPE_TO_KIND is None:
        _EVENT_TYPE_TO_KIND = _build_event_type_mapping()
    return _EVENT_TYPE_TO_KIND.get(event_type_value, TraceEventKind.CUSTOM)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _short_uuid() -> str:
    """Generate a compact UUID-based identifier (first 12 hex chars)."""
    return uuid.uuid4().hex[:12]
