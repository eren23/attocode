"""Goal recitation for maintaining focus (Trick Q).

Periodically injects goal/progress summaries into the message
stream to prevent the agent from losing track of objectives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from attocode.integrations.utilities.token_estimate import estimate_tokens


@dataclass
class PlanTask:
    """A task in a plan."""

    id: str = ""
    description: str = ""
    status: str = "pending"  # pending, in_progress, completed, failed


@dataclass
class PlanState:
    """State of a plan."""

    description: str = ""
    tasks: list[PlanTask] = field(default_factory=list)
    current_task_index: int = 0


@dataclass
class TodoItem:
    """A todo item."""

    content: str = ""
    status: str = "pending"


@dataclass
class RecitationState:
    """Current state for building recitations."""

    iteration: int = 0
    goal: str | None = None
    plan: PlanState | None = None
    todos: list[TodoItem] | None = None
    memories: list[str] | None = None
    active_files: list[str] | None = None
    recent_errors: list[str] | None = None
    custom: dict[str, str] | None = None


@dataclass
class RecitationConfig:
    """Configuration for recitation injection."""

    frequency: int = 5  # Inject every N iterations
    sources: list[str] = field(default_factory=lambda: ["plan", "todo", "goal"])
    max_tokens: int = 500
    track_history: bool = True


@dataclass
class RecitationEntry:
    """A recorded recitation injection."""

    iteration: int
    content: str
    sources: list[str] = field(default_factory=list)


RecitationEventListener = Callable[[str, dict[str, Any]], None]


class RecitationManager:
    """Manages periodic goal/progress recitation.

    Injects system messages at configurable intervals to
    keep the agent focused on its objectives.
    """

    def __init__(self, config: RecitationConfig | None = None) -> None:
        self._config = config or RecitationConfig()
        self._last_injection_iteration = 0
        self._history: list[RecitationEntry] = []
        self._listeners: list[RecitationEventListener] = []

    def should_inject(self, iteration: int) -> bool:
        """Check if recitation should be injected at this iteration."""
        if iteration <= 1:
            return True
        return (iteration - self._last_injection_iteration) >= self._config.frequency

    def build_recitation(self, state: RecitationState) -> str | None:
        """Build recitation content from current state.

        Returns None if there's nothing meaningful to recite.
        """
        sections: list[str] = []

        # Goal
        if "goal" in self._config.sources and state.goal:
            sections.append(f"Goal: {state.goal}")

        # Plan progress
        if "plan" in self._config.sources and state.plan:
            plan = state.plan
            total = len(plan.tasks)
            completed = sum(1 for t in plan.tasks if t.status == "completed")
            sections.append(f"Plan: {completed}/{total} tasks complete")

            # Show next pending tasks (up to 2)
            pending = [t for t in plan.tasks if t.status == "pending"]
            for task in pending[:2]:
                sections.append(f"  Next: {task.description}")

        # Todos
        if "todo" in self._config.sources and state.todos:
            pending_todos = [t for t in state.todos if t.status == "pending"]
            if pending_todos:
                sections.append(f"Todos: {len(pending_todos)} remaining")
                for todo in pending_todos[:3]:
                    sections.append(f"  - {todo.content}")

        # Memories
        if "memory" in self._config.sources and state.memories:
            for mem in state.memories[:3]:
                sections.append(f"Remember: {mem}")

        # Recent errors
        if state.recent_errors:
            for err in state.recent_errors[-2:]:
                sections.append(f"Recent error: {err}")

        # Custom
        if state.custom:
            for k, v in state.custom.items():
                sections.append(f"{k}: {v}")

        if not sections:
            return None

        content = "\n".join(sections)

        # Truncate to max tokens
        max_chars = int(self._config.max_tokens * 3.5)
        if len(content) > max_chars:
            content = content[:max_chars] + "..."

        return content

    def inject_if_needed(
        self,
        messages: list[dict[str, Any]],
        state: RecitationState,
    ) -> list[dict[str, Any]]:
        """Inject recitation into messages if needed.

        Returns a new list with the recitation message inserted
        before the last user message.
        """
        if not self.should_inject(state.iteration):
            self._emit("recitation.skipped", {"iteration": state.iteration})
            return messages

        content = self.build_recitation(state)
        if content is None:
            return messages

        # Wrap in status header
        full_content = f"[Current Status - Iteration {state.iteration}]\n{content}"

        recitation_msg: dict[str, Any] = {
            "role": "system",
            "content": full_content,
        }

        # Insert before last user message
        result = list(messages)
        insert_idx = len(result)
        for i in range(len(result) - 1, -1, -1):
            if result[i].get("role") == "user":
                insert_idx = i
                break
        result.insert(insert_idx, recitation_msg)

        self._last_injection_iteration = state.iteration
        self._emit("recitation.injected", {"iteration": state.iteration})

        # Track history
        if self._config.track_history:
            self._history.append(RecitationEntry(
                iteration=state.iteration,
                content=content,
                sources=list(self._config.sources),
            ))

        return result

    def force_inject(
        self,
        messages: list[dict[str, Any]],
        state: RecitationState,
    ) -> list[dict[str, Any]]:
        """Force recitation injection regardless of frequency."""
        saved = self._config.frequency
        self._config.frequency = 0
        result = self.inject_if_needed(messages, state)
        self._config.frequency = saved
        return result

    def get_history(self) -> list[RecitationEntry]:
        """Get recitation history."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clear recitation history."""
        self._history.clear()

    def update_config(self, **kwargs: Any) -> None:
        """Update configuration."""
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)

    def on(self, listener: RecitationEventListener) -> Callable[[], None]:
        """Subscribe to recitation events."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass


def build_quick_recitation(state: RecitationState) -> str:
    """Build a compact one-line recitation."""
    parts: list[str] = []

    if state.goal:
        parts.append(f"Goal: {state.goal}")

    if state.plan:
        completed = sum(1 for t in state.plan.tasks if t.status == "completed")
        total = len(state.plan.tasks)
        parts.append(f"Progress: {completed}/{total}")

    if state.todos:
        pending = sum(1 for t in state.todos if t.status == "pending")
        parts.append(f"Todos: {pending} remaining")

    return " | ".join(parts)


def calculate_optimal_frequency(context_tokens: int) -> int:
    """Calculate optimal recitation frequency based on context size."""
    if context_tokens < 10_000:
        return 10
    elif context_tokens < 30_000:
        return 7
    elif context_tokens < 60_000:
        return 5
    else:
        return 3
