"""Task manager with DAG-based dependency tracking.

Manages a directed acyclic graph of tasks with status tracking,
dependency resolution, and progress queries.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from attocode.types.agent import PlanTask, TaskStatus


@dataclass
class TaskNode:
    """Internal task node with full metadata."""

    task: PlanTask
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    completed_at: float | None = None
    result: str | None = None
    error: str | None = None
    agent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskManager:
    """Manages tasks in a DAG with dependency resolution.

    Tasks can have dependencies (blocked_by) and dependents (blocks).
    Only tasks with all dependencies completed can be executed.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskNode] = {}
        self._next_id = 1

    def create_task(
        self,
        description: str,
        dependencies: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new task. Returns task ID."""
        task_id = f"task-{self._next_id}"
        self._next_id += 1

        deps = dependencies or []
        # Check if blocked by incomplete dependencies
        status = TaskStatus.PENDING
        for dep_id in deps:
            dep = self._tasks.get(dep_id)
            if dep and dep.task.status != TaskStatus.COMPLETED:
                status = TaskStatus.BLOCKED
                break

        task = PlanTask(
            id=task_id,
            description=description,
            status=status,
            dependencies=deps,
        )
        node = TaskNode(task=task, metadata=metadata or {})
        self._tasks[task_id] = node
        return task_id

    def get_task(self, task_id: str) -> PlanTask | None:
        """Get a task by ID."""
        node = self._tasks.get(task_id)
        return node.task if node else None

    def get_node(self, task_id: str) -> TaskNode | None:
        """Get the full task node."""
        return self._tasks.get(task_id)

    def start_task(self, task_id: str, agent_id: str | None = None) -> bool:
        """Mark a task as in progress. Returns False if not ready."""
        node = self._tasks.get(task_id)
        if node is None:
            return False

        if node.task.status not in (TaskStatus.PENDING, TaskStatus.BLOCKED):
            return False

        # Check dependencies are complete
        if not self._dependencies_met(task_id):
            return False

        node.task.status = TaskStatus.IN_PROGRESS
        node.started_at = time.monotonic()
        node.agent_id = agent_id
        return True

    def complete_task(self, task_id: str, result: str | None = None) -> bool:
        """Mark a task as completed."""
        node = self._tasks.get(task_id)
        if node is None:
            return False

        node.task.status = TaskStatus.COMPLETED
        node.task.result = result
        node.result = result
        node.completed_at = time.monotonic()

        # Unblock dependents
        self._update_blocked_tasks()
        return True

    def fail_task(self, task_id: str, error: str | None = None) -> bool:
        """Mark a task as failed."""
        node = self._tasks.get(task_id)
        if node is None:
            return False

        node.task.status = TaskStatus.FAILED
        node.error = error
        node.completed_at = time.monotonic()
        return True

    def skip_task(self, task_id: str) -> bool:
        """Skip a task."""
        node = self._tasks.get(task_id)
        if node is None:
            return False

        node.task.status = TaskStatus.SKIPPED
        node.completed_at = time.monotonic()
        self._update_blocked_tasks()
        return True

    def get_ready_tasks(self) -> list[PlanTask]:
        """Get tasks that are ready to execute (dependencies met)."""
        ready = []
        for node in self._tasks.values():
            if node.task.status in (TaskStatus.PENDING, TaskStatus.BLOCKED):
                if self._dependencies_met(node.task.id):
                    ready.append(node.task)
        return ready

    def get_all_tasks(self) -> list[PlanTask]:
        """Get all tasks in creation order."""
        return [node.task for node in self._tasks.values()]

    def get_tasks_by_status(self, status: TaskStatus) -> list[PlanTask]:
        """Get tasks with a specific status."""
        return [
            node.task
            for node in self._tasks.values()
            if node.task.status == status
        ]

    @property
    def total_tasks(self) -> int:
        return len(self._tasks)

    @property
    def completed_count(self) -> int:
        return sum(
            1
            for n in self._tasks.values()
            if n.task.status == TaskStatus.COMPLETED
        )

    @property
    def pending_count(self) -> int:
        return sum(
            1
            for n in self._tasks.values()
            if n.task.status in (TaskStatus.PENDING, TaskStatus.BLOCKED)
        )

    @property
    def in_progress_count(self) -> int:
        return sum(
            1
            for n in self._tasks.values()
            if n.task.status == TaskStatus.IN_PROGRESS
        )

    @property
    def failed_count(self) -> int:
        return sum(
            1
            for n in self._tasks.values()
            if n.task.status == TaskStatus.FAILED
        )

    @property
    def progress(self) -> float:
        """Overall progress as a fraction 0.0 to 1.0."""
        if not self._tasks:
            return 1.0
        done = sum(
            1
            for n in self._tasks.values()
            if n.task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        )
        return done / len(self._tasks)

    @property
    def is_complete(self) -> bool:
        """Whether all tasks are done."""
        return all(
            n.task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
            for n in self._tasks.values()
        )

    def get_summary(self) -> str:
        """Get a human-readable summary."""
        total = self.total_tasks
        if total == 0:
            return "No tasks."
        return (
            f"Tasks: {self.completed_count}/{total} complete, "
            f"{self.in_progress_count} in progress, "
            f"{self.pending_count} pending, "
            f"{self.failed_count} failed"
        )

    def clear(self) -> None:
        """Clear all tasks."""
        self._tasks.clear()
        self._next_id = 1

    def _dependencies_met(self, task_id: str) -> bool:
        """Check if all dependencies of a task are completed."""
        node = self._tasks.get(task_id)
        if node is None:
            return False
        for dep_id in node.task.dependencies:
            dep = self._tasks.get(dep_id)
            if dep is None:
                continue  # Missing dependency treated as met
            if dep.task.status not in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
                return False
        return True

    def _update_blocked_tasks(self) -> None:
        """Update blocked tasks that may now be ready."""
        for node in self._tasks.values():
            if node.task.status == TaskStatus.BLOCKED:
                if self._dependencies_met(node.task.id):
                    node.task.status = TaskStatus.PENDING
