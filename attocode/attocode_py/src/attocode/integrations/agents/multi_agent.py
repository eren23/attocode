"""Multi-agent coordinator for parallel and sequential task execution.

Coordinates team-based execution with role-based task distribution,
consensus building, and event-driven lifecycle management.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from attocode.types.agent import AgentResult
from attocode.types.budget import ExecutionBudget, SUBAGENT_BUDGET


# =============================================================================
# Enums
# =============================================================================


class ConsensusStrategy(StrEnum):
    """Strategy for reaching consensus among agents."""

    VOTING = "voting"
    AUTHORITY = "authority"
    UNANIMOUS = "unanimous"
    FIRST_COMPLETE = "first-complete"


class CoordinationEventType(StrEnum):
    """Types of coordination events."""

    TEAM_START = "team.start"
    AGENT_SPAWN = "agent.spawn"
    AGENT_WORKING = "agent.working"
    AGENT_COMPLETE = "agent.complete"
    CONSENSUS_START = "consensus.start"
    CONSENSUS_REACHED = "consensus.reached"
    TEAM_COMPLETE = "team.complete"


# =============================================================================
# Data Types
# =============================================================================


@dataclass(slots=True)
class AgentRole:
    """Agent role definition."""

    name: str
    description: str = ""
    system_prompt: str = ""
    capabilities: list[str] = field(default_factory=list)
    authority: int = 5  # 0-10, higher = more authority
    model: str | None = None


@dataclass(slots=True)
class CoordinationEvent:
    """Event emitted during multi-agent coordination."""

    type: CoordinationEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class AgentTaskResult:
    """Result from a single agent in a team."""

    agent_id: str
    role: str
    success: bool
    output: str
    confidence: float = 0.5
    artifacts: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class Decision:
    """Consensus decision from multiple agents."""

    agreed: bool
    result: str
    votes: dict[str, bool] = field(default_factory=dict)
    dissent: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TeamResult:
    """Result from team-based execution."""

    success: bool
    task_results: list[AgentResult] = field(default_factory=list)
    consensus: Decision | None = None
    coordinator: str = ""
    duration_ms: float = 0.0


CoordinationEventListener = Callable[[CoordinationEvent], None]


# =============================================================================
# Built-in Roles
# =============================================================================

CODER_ROLE = AgentRole(
    name="coder",
    description="Expert software developer",
    system_prompt=(
        "You are an expert software developer. "
        "Focus on writing clean, maintainable code, "
        "following best practices, considering edge cases, "
        "and writing tests when appropriate."
    ),
    capabilities=["code", "debug", "refactor", "test"],
    authority=5,
)

REVIEWER_ROLE = AgentRole(
    name="reviewer",
    description="Code reviewer focused on quality",
    system_prompt=(
        "You are a code reviewer. "
        "Focus on security vulnerabilities, performance issues, "
        "code style and consistency, and potential bugs."
    ),
    capabilities=["review", "analyze", "security"],
    authority=6,
)

ARCHITECT_ROLE = AgentRole(
    name="architect",
    description="System architect",
    system_prompt=(
        "You are a system architect. "
        "Focus on overall system design, scalability considerations, "
        "technology choices, and integration patterns."
    ),
    capabilities=["design", "architect", "plan"],
    authority=8,
)

RESEARCHER_ROLE = AgentRole(
    name="researcher",
    description="Technical researcher",
    system_prompt=(
        "You are a technical researcher. "
        "Focus on finding relevant information, evaluating solutions, "
        "understanding trade-offs, and synthesizing knowledge."
    ),
    capabilities=["research", "analyze", "evaluate"],
    authority=4,
)


# =============================================================================
# Multi-Agent Coordinator
# =============================================================================


class MultiAgentCoordinator:
    """Coordinates multi-agent task execution.

    Supports parallel and sequential task execution with
    budget management and event emission.

    Example::

        coordinator = MultiAgentCoordinator()

        results = await coordinator.spawn_parallel(
            tasks=["Implement auth", "Write tests"],
            budget_per_agent=SUBAGENT_BUDGET,
        )
    """

    def __init__(self) -> None:
        self._listeners: list[CoordinationEventListener] = []
        self._active_agents: dict[str, str] = {}  # agent_id -> task
        self._results: dict[str, AgentResult] = {}
        self._agent_counter = 0

    # =========================================================================
    # Task Execution
    # =========================================================================

    async def spawn_parallel(
        self,
        tasks: list[str],
        budget_per_agent: ExecutionBudget | None = None,
        spawn_fn: Callable[..., Any] | None = None,
    ) -> list[AgentResult]:
        """Spawn multiple agents in parallel.

        Args:
            tasks: List of task descriptions.
            budget_per_agent: Budget for each agent.
            spawn_fn: Optional async function to spawn an agent.
                      Signature: (task: str, agent_id: str, budget: ExecutionBudget) -> AgentResult

        Returns:
            List of AgentResult, one per task.
        """
        budget = budget_per_agent or SUBAGENT_BUDGET

        self._emit(CoordinationEvent(
            type=CoordinationEventType.TEAM_START,
            data={"task_count": len(tasks), "mode": "parallel"},
        ))

        start_time = time.monotonic()

        # Create agent IDs and register
        agent_ids: list[str] = []
        for task in tasks:
            self._agent_counter += 1
            agent_id = f"agent-{self._agent_counter}"
            agent_ids.append(agent_id)
            self._active_agents[agent_id] = task

            self._emit(CoordinationEvent(
                type=CoordinationEventType.AGENT_SPAWN,
                data={"agent_id": agent_id, "task": task},
            ))

        # Run all agents in parallel
        if spawn_fn is not None:
            coros = [
                self._run_agent(agent_id, task, budget, spawn_fn)
                for agent_id, task in zip(agent_ids, tasks)
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            agent_results: list[AgentResult] = []
            for agent_id, result in zip(agent_ids, results):
                if isinstance(result, Exception):
                    agent_result = AgentResult(
                        success=False,
                        response="",
                        error=str(result),
                    )
                else:
                    agent_result = result
                agent_results.append(agent_result)
                self._results[agent_id] = agent_result
                self._active_agents.pop(agent_id, None)

                self._emit(CoordinationEvent(
                    type=CoordinationEventType.AGENT_COMPLETE,
                    data={
                        "agent_id": agent_id,
                        "success": agent_result.success,
                    },
                ))
        else:
            # No spawn function — return placeholder results
            agent_results = [
                AgentResult(
                    success=False,
                    response="",
                    error="No spawn function provided",
                )
                for _ in tasks
            ]
            for agent_id, result in zip(agent_ids, agent_results):
                self._results[agent_id] = result
                self._active_agents.pop(agent_id, None)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        self._emit(CoordinationEvent(
            type=CoordinationEventType.TEAM_COMPLETE,
            data={
                "task_count": len(tasks),
                "success_count": sum(1 for r in agent_results if r.success),
                "duration_ms": elapsed_ms,
            },
        ))

        return agent_results

    async def spawn_sequential(
        self,
        tasks: list[str],
        budget_per_agent: ExecutionBudget | None = None,
        spawn_fn: Callable[..., Any] | None = None,
    ) -> list[AgentResult]:
        """Spawn agents sequentially, one at a time.

        Each agent starts only after the previous one completes.
        Context from earlier agents can be passed to later ones.

        Args:
            tasks: List of task descriptions.
            budget_per_agent: Budget for each agent.
            spawn_fn: Optional async function to spawn an agent.

        Returns:
            List of AgentResult, one per task.
        """
        budget = budget_per_agent or SUBAGENT_BUDGET

        self._emit(CoordinationEvent(
            type=CoordinationEventType.TEAM_START,
            data={"task_count": len(tasks), "mode": "sequential"},
        ))

        start_time = time.monotonic()
        agent_results: list[AgentResult] = []

        for task in tasks:
            self._agent_counter += 1
            agent_id = f"agent-{self._agent_counter}"
            self._active_agents[agent_id] = task

            self._emit(CoordinationEvent(
                type=CoordinationEventType.AGENT_SPAWN,
                data={"agent_id": agent_id, "task": task},
            ))

            if spawn_fn is not None:
                try:
                    result = await self._run_agent(
                        agent_id, task, budget, spawn_fn
                    )
                except Exception as exc:
                    result = AgentResult(
                        success=False,
                        response="",
                        error=str(exc),
                    )
            else:
                result = AgentResult(
                    success=False,
                    response="",
                    error="No spawn function provided",
                )

            agent_results.append(result)
            self._results[agent_id] = result
            self._active_agents.pop(agent_id, None)

            self._emit(CoordinationEvent(
                type=CoordinationEventType.AGENT_COMPLETE,
                data={"agent_id": agent_id, "success": result.success},
            ))

        elapsed_ms = (time.monotonic() - start_time) * 1000

        self._emit(CoordinationEvent(
            type=CoordinationEventType.TEAM_COMPLETE,
            data={
                "task_count": len(tasks),
                "success_count": sum(1 for r in agent_results if r.success),
                "duration_ms": elapsed_ms,
            },
        ))

        return agent_results

    def collect_results(self, agent_ids: list[str]) -> list[AgentResult]:
        """Collect results from completed agents.

        Args:
            agent_ids: List of agent IDs to collect results for.

        Returns:
            List of AgentResult for agents that have completed.
        """
        results: list[AgentResult] = []
        for agent_id in agent_ids:
            result = self._results.get(agent_id)
            if result is not None:
                results.append(result)
        return results

    # =========================================================================
    # State Queries
    # =========================================================================

    @property
    def active_count(self) -> int:
        """Number of currently active agents."""
        return len(self._active_agents)

    @property
    def completed_count(self) -> int:
        """Number of completed agent runs."""
        return len(self._results)

    def get_active_agents(self) -> dict[str, str]:
        """Get mapping of active agent IDs to their tasks."""
        return dict(self._active_agents)

    # =========================================================================
    # Events
    # =========================================================================

    def on(self, listener: CoordinationEventListener) -> Callable[[], None]:
        """Subscribe to coordination events. Returns unsubscribe function."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def _emit(self, event: CoordinationEvent) -> None:
        """Emit an event to all listeners."""
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass

    # =========================================================================
    # Internal
    # =========================================================================

    async def _run_agent(
        self,
        agent_id: str,
        task: str,
        budget: ExecutionBudget,
        spawn_fn: Callable[..., Any],
    ) -> AgentResult:
        """Run a single agent."""
        self._emit(CoordinationEvent(
            type=CoordinationEventType.AGENT_WORKING,
            data={"agent_id": agent_id, "status": "running"},
        ))

        result = await spawn_fn(task, agent_id, budget)

        if isinstance(result, AgentResult):
            return result

        # Wrap raw result
        return AgentResult(
            success=True,
            response=str(result) if result else "",
        )
