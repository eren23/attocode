"""Shared context engine for building worker system prompts.

Composes SharedContextState into complete worker prompts by assembling
shared prefix, task context, failure guidance, and goal recitation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from attocode.shared.shared_context_state import SharedContextState


@dataclass(slots=True)
class SharedContextEngineConfig:
    """Configuration for shared context engine."""

    max_failure_context: int = 10
    include_insights: bool = True
    include_references: bool = True


@dataclass(slots=True)
class WorkerTask:
    """Task specification for a worker."""

    id: str
    description: str
    goal: str
    dependencies: list[str] = field(default_factory=list)
    context: str = ""


@dataclass
class SharedContextEngine:
    """Orchestration layer composing shared state into worker prompts.

    Builds complete worker system prompts by assembling:
    - Shared prefix for KV-cache alignment
    - Task-specific context
    - Failure guidance from cross-worker learning
    - Goal recitation for persistence
    """

    shared_state: SharedContextState = field(default_factory=SharedContextState)
    config: SharedContextEngineConfig = field(default_factory=SharedContextEngineConfig)

    def build_worker_system_prompt(self, task: WorkerTask) -> str:
        """Create full system prompt for a worker."""
        parts: list[str] = []

        # Shared prefix for cache alignment
        prefix = self.get_shared_prefix()
        if prefix:
            parts.append(prefix)

        # Task context
        parts.append(self._build_task_context(task))

        # Failure guidance
        guidance = self.get_failure_guidance()
        if guidance:
            parts.append(guidance)

        # Goal recitation
        parts.append(self.get_goal_recitation(task))

        return "\n\n".join(parts)

    def get_shared_prefix(self) -> str:
        """Static prefix for cache alignment."""
        prefix = self.shared_state.kv_cache_prefix
        if prefix:
            return f"<shared-context>\n{prefix}\n</shared-context>"
        return ""

    def report_failure(self, worker_id: str, failure: str, error: str = "") -> None:
        """Delegate to SharedContextState."""
        self.shared_state.record_failure(worker_id, failure, error)

    def get_failure_guidance(self) -> str:
        """Format failure context and cross-worker insights."""
        context = self.shared_state.get_failure_context(
            max_failures=self.config.max_failure_context
        )

        if not context:
            return ""

        parts = ["<failure-guidance>", context]

        if self.config.include_insights:
            insights = self.shared_state.get_failure_insights()
            if insights:
                parts.append("\n**Key Insights:**")
                for insight in insights:
                    parts.append(f"- {insight}")

        parts.append("</failure-guidance>")
        return "\n".join(parts)

    def get_goal_recitation(self, task: WorkerTask) -> str:
        """Build goal block for a worker."""
        parts = [
            "<goal>",
            f"Task: {task.description}",
            f"Goal: {task.goal}",
        ]

        if task.dependencies:
            parts.append(f"Dependencies: {', '.join(task.dependencies)}")

        if task.context:
            parts.append(f"Context: {task.context}")

        parts.append("</goal>")
        return "\n".join(parts)

    def get_relevant_references(self, query: str) -> list[Any]:
        """Search pooled references."""
        if not self.config.include_references:
            return []
        return self.shared_state.search_references(query)

    def _build_task_context(self, task: WorkerTask) -> str:
        """Build task-specific context section."""
        return (
            f"<task id=\"{task.id}\">\n"
            f"Description: {task.description}\n"
            f"Goal: {task.goal}\n"
            "</task>"
        )
