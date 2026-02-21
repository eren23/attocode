"""Task management tools for agents.

Provides tools for creating, updating, listing, and querying tasks
within an agent's execution plan. Enables agents to manage their
own work breakdown.
"""

from __future__ import annotations

from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.agent import AgentPlan, PlanTask, TaskStatus
from attocode.types.messages import DangerLevel


def create_task_tools(plan: AgentPlan) -> list[Tool]:
    """Create task management tools bound to an agent plan."""

    async def task_create(args: dict[str, Any]) -> str:
        """Create a new task in the plan."""
        task_id = args.get("id", f"task-{len(plan.tasks) + 1}")
        description = args.get("description", "")
        dependencies = args.get("dependencies", [])

        if not description:
            return "Error: task description is required"

        task = PlanTask(
            id=task_id,
            description=description,
            status=TaskStatus.PENDING,
            dependencies=dependencies,
        )
        plan.tasks.append(task)
        return f"Created task {task_id}: {description}"

    async def task_update(args: dict[str, Any]) -> str:
        """Update a task's status or result."""
        task_id = args.get("id", "")
        status = args.get("status")
        result = args.get("result")

        for task in plan.tasks:
            if task.id == task_id:
                if status:
                    try:
                        task.status = TaskStatus(status)
                    except ValueError:
                        return f"Error: invalid status '{status}'"
                if result is not None:
                    task.result = result
                return f"Updated task {task_id}: status={task.status.value}"

        return f"Error: task {task_id} not found"

    async def task_get(args: dict[str, Any]) -> str:
        """Get details of a specific task."""
        task_id = args.get("id", "")

        for task in plan.tasks:
            if task.id == task_id:
                deps = ", ".join(task.dependencies) if task.dependencies else "none"
                return (
                    f"Task: {task.id}\n"
                    f"Description: {task.description}\n"
                    f"Status: {task.status.value}\n"
                    f"Dependencies: {deps}\n"
                    f"Result: {task.result or 'none'}"
                )

        return f"Error: task {task_id} not found"

    async def task_list(args: dict[str, Any]) -> str:
        """List all tasks with their status."""
        if not plan.tasks:
            return "No tasks in plan."

        lines = [f"Plan: {plan.goal}", f"Progress: {plan.progress:.0%}", ""]
        for task in plan.tasks:
            status_icon = {
                TaskStatus.PENDING: "[ ]",
                TaskStatus.IN_PROGRESS: "[~]",
                TaskStatus.COMPLETED: "[x]",
                TaskStatus.FAILED: "[!]",
                TaskStatus.BLOCKED: "[B]",
                TaskStatus.SKIPPED: "[-]",
            }.get(task.status, "[?]")
            lines.append(f"{status_icon} {task.id}: {task.description}")

        return "\n".join(lines)

    return [
        Tool(
            spec=ToolSpec(
                name="task_create",
                description="Create a new task in the current plan",
                parameters={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Task ID (auto-generated if omitted)"},
                        "description": {"type": "string", "description": "Task description"},
                        "dependencies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "IDs of tasks this depends on",
                        },
                    },
                    "required": ["description"],
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=task_create,
            tags=["planning"],
        ),
        Tool(
            spec=ToolSpec(
                name="task_update",
                description="Update a task's status or result",
                parameters={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Task ID to update"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "failed", "blocked", "skipped"],
                            "description": "New status",
                        },
                        "result": {"type": "string", "description": "Task result or notes"},
                    },
                    "required": ["id"],
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=task_update,
            tags=["planning"],
        ),
        Tool(
            spec=ToolSpec(
                name="task_get",
                description="Get details of a specific task",
                parameters={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Task ID to get"},
                    },
                    "required": ["id"],
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=task_get,
            tags=["planning"],
        ),
        Tool(
            spec=ToolSpec(
                name="task_list",
                description="List all tasks in the current plan with status",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=task_list,
            tags=["planning"],
        ),
    ]
