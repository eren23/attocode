"""Boomerang orchestrator mode.

Decomposes complex tasks into subtasks, assigns each to an
appropriate agent mode (Architect, Code, Debug, Ask), executes
with isolated context, and synthesizes results.

Bridges single-agent and full swarm execution models.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class SubtaskStatus(StrEnum):
    """Status of an orchestrated subtask."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class Subtask:
    """A subtask assigned by the orchestrator."""

    id: str
    description: str
    mode: str = "code"  # code, architect, debug, ask
    status: SubtaskStatus = SubtaskStatus.PENDING
    result_summary: str = ""
    error: str | None = None
    duration: float = 0.0
    depends_on: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OrchestratorPlan:
    """Plan created by the orchestrator for task decomposition."""

    task: str
    subtasks: list[Subtask] = field(default_factory=list)
    strategy: str = ""  # Brief description of the approach

    @property
    def pending(self) -> list[Subtask]:
        return [s for s in self.subtasks if s.status == SubtaskStatus.PENDING]

    @property
    def completed(self) -> list[Subtask]:
        return [s for s in self.subtasks if s.status == SubtaskStatus.COMPLETED]

    @property
    def failed(self) -> list[Subtask]:
        return [s for s in self.subtasks if s.status == SubtaskStatus.FAILED]

    @property
    def is_complete(self) -> bool:
        return all(
            s.status in (SubtaskStatus.COMPLETED, SubtaskStatus.SKIPPED)
            for s in self.subtasks
        )

    @property
    def progress(self) -> float:
        if not self.subtasks:
            return 0.0
        done = sum(
            1 for s in self.subtasks
            if s.status in (SubtaskStatus.COMPLETED, SubtaskStatus.SKIPPED)
        )
        return done / len(self.subtasks)

    def get_ready_subtasks(self) -> list[Subtask]:
        """Get subtasks whose dependencies are all satisfied."""
        completed_ids = {s.id for s in self.subtasks if s.status == SubtaskStatus.COMPLETED}
        return [
            s for s in self.subtasks
            if s.status == SubtaskStatus.PENDING
            and all(dep in completed_ids for dep in s.depends_on)
        ]


class Orchestrator:
    """Boomerang orchestrator for complex task decomposition.

    Analyzes complex tasks, breaks them into mode-specific
    subtasks, and coordinates execution with isolated context
    for each subtask.
    """

    def __init__(self) -> None:
        self._plan: OrchestratorPlan | None = None
        self._start_time: float = 0.0

    @property
    def plan(self) -> OrchestratorPlan | None:
        return self._plan

    def create_decomposition_prompt(self, task: str, available_modes: list[str] | None = None) -> str:
        """Create a prompt for the LLM to decompose a task."""
        modes = available_modes or ["code", "architect", "debug", "ask"]
        mode_list = "\n".join(f"- **{m}**: " + _mode_description(m) for m in modes)
        return "\n".join([
            "## Task Decomposition",
            f"Complex task: {task}",
            "",
            "## Available Modes",
            mode_list,
            "",
            "## Instructions",
            "Break this task into 2-6 focused subtasks.",
            "For each subtask, specify:",
            "1. A brief description",
            "2. Which mode should handle it",
            "3. Dependencies (which subtasks must complete first)",
            "",
            "Output as a numbered list with mode in brackets:",
            "1. [architect] Analyze the current authentication flow",
            "2. [code] Implement the new login endpoint (depends on: 1)",
            "3. [code] Add tests for the login endpoint (depends on: 2)",
        ])

    def create_plan(self, task: str, subtasks: list[Subtask]) -> OrchestratorPlan:
        """Create an orchestration plan from a list of subtasks."""
        self._start_time = time.monotonic()
        self._plan = OrchestratorPlan(task=task, subtasks=subtasks)
        return self._plan

    def create_subtask_prompt(self, subtask: Subtask, context_summaries: list[str] | None = None) -> str:
        """Create a prompt for executing a specific subtask."""
        parts = [
            f"## Subtask: {subtask.description}",
            f"Mode: {subtask.mode}",
        ]
        if context_summaries:
            parts.extend(["", "## Context from Previous Subtasks"])
            for summary in context_summaries:
                parts.append(f"- {summary}")
        parts.extend([
            "",
            "Complete this subtask and provide a brief summary of what you did.",
            "Focus only on this specific subtask.",
        ])
        return "\n".join(parts)

    def record_result(
        self,
        subtask_id: str,
        success: bool,
        summary: str = "",
        error: str | None = None,
    ) -> Subtask | None:
        """Record the result of a subtask execution."""
        if self._plan is None:
            return None

        for subtask in self._plan.subtasks:
            if subtask.id == subtask_id:
                subtask.status = SubtaskStatus.COMPLETED if success else SubtaskStatus.FAILED
                subtask.result_summary = summary
                subtask.error = error
                subtask.duration = time.monotonic() - self._start_time
                return subtask
        return None

    def create_synthesis_prompt(self) -> str:
        """Create a prompt to synthesize all subtask results."""
        if self._plan is None:
            return "No plan to synthesize."

        parts = [
            "## Synthesis",
            f"Original task: {self._plan.task}",
            "",
            "## Subtask Results",
        ]
        for subtask in self._plan.subtasks:
            status = "DONE" if subtask.status == SubtaskStatus.COMPLETED else subtask.status.value
            parts.append(f"- [{status}] {subtask.description}")
            if subtask.result_summary:
                parts.append(f"  Result: {subtask.result_summary}")
            if subtask.error:
                parts.append(f"  Error: {subtask.error}")

        parts.extend([
            "",
            "Synthesize the results into a coherent summary.",
            "Note any issues or incomplete work.",
        ])
        return "\n".join(parts)

    def get_status(self) -> dict[str, Any]:
        """Get current orchestration status."""
        if self._plan is None:
            return {"status": "no_plan"}
        return {
            "task": self._plan.task,
            "progress": self._plan.progress,
            "total_subtasks": len(self._plan.subtasks),
            "completed": len(self._plan.completed),
            "failed": len(self._plan.failed),
            "pending": len(self._plan.pending),
            "is_complete": self._plan.is_complete,
        }


def _mode_description(mode: str) -> str:
    """Human-readable description of an agent mode."""
    descriptions = {
        "code": "Full tool access — implement features, write code",
        "architect": "Read + plan only — system design, no code execution",
        "debug": "Full access + trajectory analysis — diagnose and fix bugs",
        "ask": "Read-only — explain code, answer questions",
    }
    return descriptions.get(mode, f"Mode: {mode}")
