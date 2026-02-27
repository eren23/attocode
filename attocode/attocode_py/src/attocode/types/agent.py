"""Agent-related types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentStatus(StrEnum):
    """Current status of an agent."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CompletionReason(StrEnum):
    """Why the agent finished."""

    COMPLETED = "completed"
    BUDGET_LIMIT = "budget_limit"
    CANCELLED = "cancelled"
    ERROR = "error"
    MAX_ITERATIONS = "max_iterations"
    FUTURE_INTENT = "future_intent"
    INCOMPLETE_ACTION = "incomplete_action"
    OPEN_TASKS = "open_tasks"


class TaskStatus(StrEnum):
    """Status of a plan task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class AgentState(StrEnum):
    """Internal state of the agent execution loop."""

    INITIALIZING = "initializing"
    THINKING = "thinking"
    EXECUTING = "executing"
    WAITING = "waiting"
    COMPACTING = "compacting"
    WRAPPING_UP = "wrapping_up"


@dataclass
class AgentMetrics:
    """Cumulative metrics for an agent run."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    estimated_cost: float = 0.0
    duration_ms: float = 0.0

    def add_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Record token usage from an LLM call."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.llm_calls += 1
        self.estimated_cost += cost


@dataclass
class PlanTask:
    """A single task in an agent plan."""

    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    result: str | None = None


@dataclass
class OpenTaskSummary:
    """Summary of open tasks."""

    pending: int = 0
    in_progress: int = 0
    blocked: int = 0

    @property
    def total(self) -> int:
        return self.pending + self.in_progress + self.blocked

    @property
    def has_open(self) -> bool:
        return self.total > 0


@dataclass
class AgentPlan:
    """The agent current plan."""

    goal: str
    tasks: list[PlanTask] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return all(t.status == TaskStatus.COMPLETED for t in self.tasks)

    @property
    def progress(self) -> float:
        if not self.tasks:
            return 1.0
        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        return completed / len(self.tasks)

    @property
    def current_task(self) -> PlanTask | None:
        for t in self.tasks:
            if t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
                return t
        return None


@dataclass
class AgentCompletionStatus:
    """Completion status of an agent run."""

    success: bool
    reason: CompletionReason = CompletionReason.COMPLETED
    details: str | None = None


@dataclass
class RecoveryInfo:
    """Information about agent recovery from errors."""

    recovered: bool = False
    attempts: int = 0
    last_error: str | None = None


@dataclass
class AgentConfig:
    """Configuration for an agent."""

    model: str | None = None
    provider: str | None = None
    api_key: str | None = None
    max_iterations: int = 100
    max_tokens: int | None = None
    temperature: float | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    sandbox_enabled: bool = False
    debug: bool = False


@dataclass
class AgentResult:
    """Result of an agent run."""

    success: bool
    response: str
    completion: AgentCompletionStatus | None = None
    metrics: AgentMetrics | None = None
    error: str | None = None
    open_tasks: OpenTaskSummary | None = None
    recovery: RecoveryInfo | None = None
