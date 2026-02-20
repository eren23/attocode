"""Agent event types.

Comprehensive event system covering lifecycle, execution, multi-agent,
policy, context, resilience, insight, and subagent categories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    """Types of agent events.

    Organized into categories:
    - Lifecycle: start, complete, error, shutdown
    - Execution: iteration, tool.*, llm.*
    - Budget: budget.*
    - Context: compaction.*, context.*
    - Multi-agent: subagent.*, swarm.*
    - Policy: policy.*, permission.*
    - Session: session.*
    - Mode: mode.*
    - Plan: plan.*
    - Quality: quality.*, learning.*
    - Resilience: resilience.*, circuit_breaker.*
    - MCP: mcp.*
    - Undo: undo.*
    - Insight: insight.*
    """

    # --- Lifecycle ---
    START = "start"
    COMPLETE = "complete"
    ERROR = "error"
    SHUTDOWN = "shutdown"

    # --- Execution core ---
    ITERATION = "iteration"
    THINKING = "thinking"
    RESPONSE = "response"

    # --- Tool events ---
    TOOL_START = "tool.start"
    TOOL_COMPLETE = "tool.complete"
    TOOL_ERROR = "tool.error"
    TOOL_APPROVAL_REQUESTED = "tool.approval.requested"
    TOOL_APPROVAL_GRANTED = "tool.approval.granted"
    TOOL_APPROVAL_DENIED = "tool.approval.denied"
    TOOL_BLOCKED = "tool.blocked"
    TOOL_COERCED = "tool.coerced"

    # --- LLM events ---
    LLM_START = "llm.start"
    LLM_COMPLETE = "llm.complete"
    LLM_ERROR = "llm.error"
    LLM_RETRY = "llm.retry"
    LLM_STREAM_START = "llm.stream.start"
    LLM_STREAM_CHUNK = "llm.stream.chunk"
    LLM_STREAM_END = "llm.stream.end"

    # --- Budget events ---
    BUDGET_WARNING = "budget.warning"
    BUDGET_EXHAUSTED = "budget.exhausted"
    BUDGET_CHECK = "budget.check"
    BUDGET_EXTENSION_REQUESTED = "budget.extension.requested"
    BUDGET_EXTENSION_GRANTED = "budget.extension.granted"
    BUDGET_EXTENSION_DENIED = "budget.extension.denied"

    # --- Context / Compaction events ---
    COMPACTION = "compaction"
    COMPACTION_START = "compaction.start"
    COMPACTION_COMPLETE = "compaction.complete"
    COMPACTION_ERROR = "compaction.error"
    CONTEXT_OVERFLOW = "context.overflow"
    CONTEXT_BREAKDOWN = "context.breakdown"

    # --- Session events ---
    SESSION_CREATED = "session.created"
    SESSION_LOADED = "session.loaded"
    SESSION_SAVED = "session.saved"
    SESSION_RESUMED = "session.resumed"
    SESSION_FORKED = "session.forked"
    SESSION_CHECKPOINT = "session.checkpoint"

    # --- Mode events ---
    MODE_CHANGED = "mode.changed"
    MODE_WRITE_INTERCEPTED = "mode.write.intercepted"

    # --- Plan events ---
    PLAN_CREATED = "plan.created"
    PLAN_STEP_START = "plan.step.start"
    PLAN_STEP_COMPLETE = "plan.step.complete"
    PLAN_APPROVED = "plan.approved"
    PLAN_REJECTED = "plan.rejected"
    PLAN_UPDATED = "plan.updated"

    # --- Subagent events ---
    SUBAGENT_SPAWN = "subagent.spawn"
    SUBAGENT_COMPLETE = "subagent.complete"
    SUBAGENT_ERROR = "subagent.error"
    SUBAGENT_ITERATION = "subagent.iteration"
    SUBAGENT_PHASE = "subagent.phase"
    SUBAGENT_WRAPUP_STARTED = "subagent.wrapup.started"
    SUBAGENT_WRAPUP_COMPLETED = "subagent.wrapup.completed"
    SUBAGENT_TIMEOUT_HARD_KILL = "subagent.timeout.hard_kill"

    # --- Swarm events ---
    SWARM_START = "swarm.start"
    SWARM_COMPLETE = "swarm.complete"
    SWARM_TASK_QUEUED = "swarm.task.queued"
    SWARM_TASK_START = "swarm.task.start"
    SWARM_TASK_COMPLETE = "swarm.task.complete"
    SWARM_TASK_FAILED = "swarm.task.failed"
    SWARM_WAVE_START = "swarm.wave.start"
    SWARM_WAVE_COMPLETE = "swarm.wave.complete"
    SWARM_WORKER_ASSIGNED = "swarm.worker.assigned"
    SWARM_WORKER_RELEASED = "swarm.worker.released"

    # --- Policy events ---
    POLICY_EVALUATION = "policy.evaluation"
    POLICY_OVERRIDE = "policy.override"
    PERMISSION_GRANTED = "permission.granted"
    PERMISSION_DENIED = "permission.denied"
    PERMISSION_REMEMBERED = "permission.remembered"

    # --- Quality events ---
    QUALITY_CHECK = "quality.check"
    QUALITY_SCORE = "quality.score"
    LEARNING_PROPOSED = "learning.proposed"
    LEARNING_APPROVED = "learning.approved"
    LEARNING_REJECTED = "learning.rejected"
    HEALTH_CHECK = "health.check"

    # --- Resilience events ---
    RESILIENCE_RETRY = "resilience.retry"
    RESILIENCE_FALLBACK = "resilience.fallback"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker.open"
    CIRCUIT_BREAKER_HALF_OPEN = "circuit_breaker.half_open"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker.closed"

    # --- MCP events ---
    MCP_CONNECT = "mcp.connect"
    MCP_DISCONNECT = "mcp.disconnect"
    MCP_TOOL_DISCOVERED = "mcp.tool.discovered"
    MCP_TOOL_CALL = "mcp.tool.call"
    MCP_TOOL_ERROR = "mcp.tool.error"

    # --- Undo events ---
    UNDO_TRACKED = "undo.tracked"
    UNDO_EXECUTED = "undo.executed"
    UNDO_FAILED = "undo.failed"

    # --- Insight / Loop detection ---
    INSIGHT_DOOM_LOOP = "insight.doom_loop"
    INSIGHT_SATURATION = "insight.saturation"
    INSIGHT_NUDGE = "insight.nudge"
    INSIGHT_PHASE_CHANGE = "insight.phase_change"


class EventCategory(StrEnum):
    """Categories for event grouping."""

    LIFECYCLE = "lifecycle"
    EXECUTION = "execution"
    TOOL = "tool"
    LLM = "llm"
    BUDGET = "budget"
    CONTEXT = "context"
    SESSION = "session"
    MODE = "mode"
    PLAN = "plan"
    SUBAGENT = "subagent"
    SWARM = "swarm"
    POLICY = "policy"
    QUALITY = "quality"
    RESILIENCE = "resilience"
    MCP = "mcp"
    UNDO = "undo"
    INSIGHT = "insight"


# Map events to categories
EVENT_CATEGORIES: dict[EventType, EventCategory] = {}
for _evt in EventType:
    _name = _evt.value
    if _name in ("start", "complete", "error", "shutdown"):
        EVENT_CATEGORIES[_evt] = EventCategory.LIFECYCLE
    elif _name.startswith("tool."):
        EVENT_CATEGORIES[_evt] = EventCategory.TOOL
    elif _name.startswith("llm."):
        EVENT_CATEGORIES[_evt] = EventCategory.LLM
    elif _name.startswith("budget."):
        EVENT_CATEGORIES[_evt] = EventCategory.BUDGET
    elif _name.startswith(("compaction", "context.")):
        EVENT_CATEGORIES[_evt] = EventCategory.CONTEXT
    elif _name.startswith("session."):
        EVENT_CATEGORIES[_evt] = EventCategory.SESSION
    elif _name.startswith("mode."):
        EVENT_CATEGORIES[_evt] = EventCategory.MODE
    elif _name.startswith("plan."):
        EVENT_CATEGORIES[_evt] = EventCategory.PLAN
    elif _name.startswith("subagent."):
        EVENT_CATEGORIES[_evt] = EventCategory.SUBAGENT
    elif _name.startswith("swarm."):
        EVENT_CATEGORIES[_evt] = EventCategory.SWARM
    elif _name.startswith(("policy.", "permission.")):
        EVENT_CATEGORIES[_evt] = EventCategory.POLICY
    elif _name.startswith(("quality.", "learning.", "health.")):
        EVENT_CATEGORIES[_evt] = EventCategory.QUALITY
    elif _name.startswith(("resilience.", "circuit_breaker.")):
        EVENT_CATEGORIES[_evt] = EventCategory.RESILIENCE
    elif _name.startswith("mcp."):
        EVENT_CATEGORIES[_evt] = EventCategory.MCP
    elif _name.startswith("undo."):
        EVENT_CATEGORIES[_evt] = EventCategory.UNDO
    elif _name.startswith("insight."):
        EVENT_CATEGORIES[_evt] = EventCategory.INSIGHT
    else:
        EVENT_CATEGORIES[_evt] = EventCategory.EXECUTION


def get_event_category(event_type: EventType) -> EventCategory:
    """Get the category for an event type."""
    return EVENT_CATEGORIES.get(event_type, EventCategory.EXECUTION)


@dataclass
class AgentEvent:
    """An event emitted during agent execution."""

    type: EventType
    task: str | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    result: str | None = None
    error: str | None = None
    tokens: int | None = None
    cost: float | None = None
    iteration: int | None = None
    metadata: dict[str, Any] | None = None
    # Extended fields for rich events
    session_id: str | None = None
    agent_id: str | None = None
    parent_id: str | None = None
    duration_ms: float | None = None
    timestamp: float | None = None

    @property
    def category(self) -> EventCategory:
        """Get the category of this event."""
        return get_event_category(self.type)
