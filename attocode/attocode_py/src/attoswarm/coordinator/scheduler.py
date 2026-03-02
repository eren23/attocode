"""Task dependency and assignment logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from attoswarm.protocol.models import RoleSpec, TaskSpec


@dataclass(slots=True)
class AgentSlot:
    agent_id: str
    role_id: str
    backend: str
    busy: bool


@dataclass(slots=True)
class Assignment:
    task_id: str
    agent_id: str
    role_id: str


def compute_ready_tasks(tasks: list[TaskSpec], task_state: dict[str, str]) -> list[TaskSpec]:
    ready: list[TaskSpec] = []
    for t in tasks:
        status = task_state.get(t.task_id, t.status)
        if status not in {"pending", "ready"}:
            continue
        if t.task_kind in {"merge", "judge", "critic"}:
            # Merge/judge/critic tasks are allowed once source tasks reached reviewing or done.
            deps_done = all(task_state.get(dep, "pending") in {"reviewing", "done"} for dep in t.deps)
        else:
            deps_done = all(task_state.get(dep, "pending") == "done" for dep in t.deps)
        if deps_done:
            ready.append(t)
            continue
        # Partial-dependency execution: all deps terminal, >= 50% done
        if t.deps and t.task_kind not in {"merge", "judge", "critic"}:
            all_terminal = all(
                task_state.get(dep, "pending") in {"done", "failed", "skipped"}
                for dep in t.deps
            )
            if all_terminal:
                done_count = sum(1 for d in t.deps if task_state.get(d) == "done")
                if done_count / len(t.deps) >= 0.5:
                    ready.append(t)
    ready.sort(key=lambda t: (-t.priority, len(t.deps), t.task_id))
    return ready


def assign_tasks(
    ready_tasks: Iterable[TaskSpec],
    free_agents: Iterable[AgentSlot],
    roles: list[RoleSpec],
) -> list[Assignment]:
    role_by_id = {r.role_id: r for r in roles}
    available = [a for a in free_agents if not a.busy]
    assignments: list[Assignment] = []
    for task in ready_tasks:
        picked = None
        for agent in available:
            role = role_by_id.get(agent.role_id)
            if role is None:
                continue
            if task.role_hint and task.role_hint != agent.role_id:
                continue
            if role.task_kinds and task.task_kind not in role.task_kinds:
                continue
            picked = agent
            break
        if picked is None:
            continue
        assignments.append(Assignment(task_id=task.task_id, agent_id=picked.agent_id, role_id=picked.role_id))
        available = [a for a in available if a.agent_id != picked.agent_id]
    return assignments
