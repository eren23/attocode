"""Parallel background agents with git worktree isolation.

Spawns multiple agents in isolated git worktrees for
independent parallel task execution. Results are merged
back to the main branch.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ParallelTaskStatus(StrEnum):
    """Status of a parallel task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MERGE_CONFLICT = "merge_conflict"


@dataclass(slots=True)
class ParallelTask:
    """A task to be executed in parallel."""

    id: str
    description: str
    status: ParallelTaskStatus = ParallelTaskStatus.PENDING
    worktree_path: str = ""
    branch_name: str = ""
    result_summary: str = ""
    files_modified: list[str] = field(default_factory=list)
    error: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration(self) -> float:
        if self.end_time > 0 and self.start_time > 0:
            return self.end_time - self.start_time
        return 0.0


@dataclass(slots=True)
class ParallelResult:
    """Result of parallel execution."""

    tasks: list[ParallelTask]
    total_duration: float = 0.0
    merge_conflicts: list[str] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(t.status == ParallelTaskStatus.COMPLETED for t in self.tasks)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == ParallelTaskStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == ParallelTaskStatus.FAILED)

    def format_summary(self) -> str:
        """Format a human-readable summary."""
        lines = [f"Parallel execution: {self.completed_count}/{len(self.tasks)} completed"]
        for task in self.tasks:
            status = "OK" if task.status == ParallelTaskStatus.COMPLETED else task.status.value
            dur = f" ({task.duration:.1f}s)" if task.duration > 0 else ""
            lines.append(f"  [{status}] {task.description}{dur}")
            if task.error:
                lines.append(f"         Error: {task.error}")
        if self.merge_conflicts:
            lines.append(f"\nMerge conflicts in: {', '.join(self.merge_conflicts)}")
        return "\n".join(lines)


@dataclass(slots=True)
class ParallelConfig:
    """Configuration for parallel agent execution."""

    max_agents: int = 4
    worktrees_root: str = ".attocode/worktrees"
    auto_merge: bool = True
    fresh_context: bool = True
    branch_prefix: str = "parallel"


class ParallelAgentManager:
    """Manages parallel agent execution with git worktree isolation.

    Each agent gets its own git worktree (isolated branch and files)
    and fresh context for peak quality. Results are merged back
    to the main branch.
    """

    def __init__(self, config: ParallelConfig | None = None) -> None:
        self._config = config or ParallelConfig()
        self._tasks: list[ParallelTask] = []
        self._start_time: float = 0.0

    @property
    def config(self) -> ParallelConfig:
        return self._config

    @property
    def tasks(self) -> list[ParallelTask]:
        return list(self._tasks)

    def parse_tasks(self, input_text: str) -> list[ParallelTask]:
        """Parse task descriptions from pipe-separated input.

        Input format: "task1 | task2 | task3"
        """
        descriptions = [t.strip() for t in input_text.split("|") if t.strip()]
        if len(descriptions) > self._config.max_agents:
            descriptions = descriptions[: self._config.max_agents]
            logger.warning(
                "Capped parallel tasks at %d (max_agents)",
                self._config.max_agents,
            )

        self._tasks = [
            ParallelTask(
                id=f"p{i}",
                description=desc,
                branch_name=f"{self._config.branch_prefix}/p{i}",
            )
            for i, desc in enumerate(descriptions)
        ]
        self._start_time = time.monotonic()
        return list(self._tasks)

    def get_task(self, task_id: str) -> ParallelTask | None:
        """Get a task by ID."""
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None

    def start_task(self, task_id: str, worktree_path: str = "") -> bool:
        """Mark a task as running."""
        task = self.get_task(task_id)
        if task is None:
            return False
        task.status = ParallelTaskStatus.RUNNING
        task.start_time = time.monotonic()
        task.worktree_path = worktree_path
        return True

    def complete_task(
        self,
        task_id: str,
        *,
        success: bool = True,
        summary: str = "",
        files_modified: list[str] | None = None,
        error: str | None = None,
    ) -> bool:
        """Record task completion."""
        task = self.get_task(task_id)
        if task is None:
            return False
        task.status = ParallelTaskStatus.COMPLETED if success else ParallelTaskStatus.FAILED
        task.end_time = time.monotonic()
        task.result_summary = summary
        task.files_modified = files_modified or []
        task.error = error
        return True

    def get_result(self) -> ParallelResult:
        """Get the overall parallel execution result."""
        duration = time.monotonic() - self._start_time if self._start_time else 0.0

        # Detect potential merge conflicts (files modified by multiple tasks)
        file_owners: dict[str, list[str]] = {}
        for task in self._tasks:
            for f in task.files_modified:
                file_owners.setdefault(f, []).append(task.id)

        conflicts = [f for f, owners in file_owners.items() if len(owners) > 1]

        return ParallelResult(
            tasks=list(self._tasks),
            total_duration=duration,
            merge_conflicts=conflicts,
        )

    def get_status(self) -> dict[str, Any]:
        """Get current execution status."""
        return {
            "total": len(self._tasks),
            "running": sum(1 for t in self._tasks if t.status == ParallelTaskStatus.RUNNING),
            "completed": sum(1 for t in self._tasks if t.status == ParallelTaskStatus.COMPLETED),
            "failed": sum(1 for t in self._tasks if t.status == ParallelTaskStatus.FAILED),
            "pending": sum(1 for t in self._tasks if t.status == ParallelTaskStatus.PENDING),
        }
