"""Context engineering manager.

Orchestrates context management techniques including goal recitation,
failure evidence injection, context-aware serialization, injection
budget management, and priority-based context assembly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from attocode.types.messages import Message, Role


class ContextPriority(StrEnum):
    """Priority levels for context injection."""

    CRITICAL = "critical"  # Always included (system prompt, goal)
    HIGH = "high"  # Included unless very tight (rules, recent failures)
    MEDIUM = "medium"  # Included if space allows (learnings, work log)
    LOW = "low"  # Only if plenty of space (historical context)


@dataclass(slots=True)
class ContextBlock:
    """A block of context to be injected into the conversation."""

    content: str
    priority: ContextPriority
    label: str = ""
    estimated_tokens: int = 0
    source: str = ""  # e.g. "rules", "failures", "learnings"

    def __post_init__(self) -> None:
        if self.estimated_tokens == 0 and self.content:
            self.estimated_tokens = len(self.content) // 4


@dataclass(slots=True)
class InjectionBudget:
    """Budget for context injection."""

    max_tokens: int = 10_000
    used_tokens: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    @property
    def usage_fraction(self) -> float:
        return self.used_tokens / self.max_tokens if self.max_tokens > 0 else 0.0

    def can_fit(self, tokens: int) -> bool:
        return self.remaining >= tokens

    def consume(self, tokens: int) -> bool:
        """Try to consume tokens. Returns True if successful."""
        if not self.can_fit(tokens):
            return False
        self.used_tokens += tokens
        return True


@dataclass(slots=True)
class FailureRecord:
    """Record of a failed attempt."""

    tool_name: str
    error: str
    iteration: int
    context: str = ""


@dataclass(slots=True)
class AssemblyResult:
    """Result of priority-based context assembly."""

    blocks_included: list[ContextBlock]
    blocks_dropped: list[ContextBlock]
    total_tokens: int
    content: str


@dataclass
class ContextEngineeringManager:
    """Manages context engineering techniques.

    Provides:
    - Goal recitation: periodic reinforcement of objectives
    - Failure evidence: tracking and injecting past failure context
    - Context-aware message injection
    - Injection budget management
    - Priority-based context assembly
    """

    goals: list[str] = field(default_factory=list)
    _failures: list[FailureRecord] = field(default_factory=list, repr=False)
    _recitation_interval: int = 5
    _last_recitation: int = field(default=0, repr=False)
    _context_blocks: list[ContextBlock] = field(default_factory=list, repr=False)
    _injection_budget: InjectionBudget = field(
        default_factory=lambda: InjectionBudget(max_tokens=10_000), repr=False,
    )
    _diversity_enabled: bool = False

    def set_goals(self, goals: list[str]) -> None:
        """Set the current goals."""
        self.goals = list(goals)

    def add_goal(self, goal: str) -> None:
        """Add a goal."""
        self.goals.append(goal)

    def set_injection_budget(self, max_tokens: int) -> None:
        """Set the injection budget for context blocks."""
        self._injection_budget = InjectionBudget(max_tokens=max_tokens)

    def register_context_block(self, block: ContextBlock) -> None:
        """Register a context block for priority-based assembly."""
        self._context_blocks.append(block)

    def clear_context_blocks(self) -> None:
        """Clear all registered context blocks."""
        self._context_blocks.clear()
        self._injection_budget.used_tokens = 0

    def assemble_context(self, *, max_tokens: int | None = None) -> AssemblyResult:
        """Assemble context blocks by priority within budget.

        Includes blocks in priority order (CRITICAL first, LOW last)
        until the injection budget is exhausted.
        """
        budget = max_tokens or self._injection_budget.max_tokens
        remaining = budget
        included: list[ContextBlock] = []
        dropped: list[ContextBlock] = []

        # Sort by priority (critical first)
        priority_order = {
            ContextPriority.CRITICAL: 0,
            ContextPriority.HIGH: 1,
            ContextPriority.MEDIUM: 2,
            ContextPriority.LOW: 3,
        }
        sorted_blocks = sorted(
            self._context_blocks,
            key=lambda b: priority_order.get(b.priority, 99),
        )

        for block in sorted_blocks:
            if block.estimated_tokens <= remaining:
                included.append(block)
                remaining -= block.estimated_tokens
            else:
                # Critical blocks are always included (may exceed budget)
                if block.priority == ContextPriority.CRITICAL:
                    included.append(block)
                    remaining -= block.estimated_tokens
                else:
                    dropped.append(block)

        # Build combined content
        content_parts = []
        for block in included:
            if block.label:
                content_parts.append(f"## {block.label}\n{block.content}")
            else:
                content_parts.append(block.content)

        total_tokens = sum(b.estimated_tokens for b in included)

        return AssemblyResult(
            blocks_included=included,
            blocks_dropped=dropped,
            total_tokens=total_tokens,
            content="\n\n".join(content_parts),
        )

    def record_failure(
        self,
        tool_name: str,
        error: str,
        iteration: int,
        context: str = "",
    ) -> None:
        """Record a tool failure for future evidence injection."""
        self._failures.append(FailureRecord(
            tool_name=tool_name,
            error=error,
            iteration=iteration,
            context=context,
        ))

    def inject_recitation(
        self,
        messages: list[Message | Any],
        current_iteration: int,
    ) -> list[Message | Any]:
        """Inject goal recitation if interval has elapsed."""
        if not self.goals:
            return messages

        if current_iteration - self._last_recitation < self._recitation_interval:
            return messages

        self._last_recitation = current_iteration

        recitation = "Current goals:\n" + "\n".join(
            f"- {g}" for g in self.goals
        )

        result = list(messages)
        last_user_idx = None
        for i in range(len(result) - 1, -1, -1):
            if hasattr(result[i], "role") and result[i].role == Role.USER:
                last_user_idx = i
                break

        if last_user_idx is not None:
            result.insert(last_user_idx, Message(
                role=Role.SYSTEM,
                content=recitation,
            ))

        return result

    def get_failure_context(self, max_failures: int = 3) -> str | None:
        """Get formatted failure evidence for injection."""
        if not self._failures:
            return None

        recent = self._failures[-max_failures:]
        lines = ["Previous failures to avoid repeating:"]
        for f in recent:
            lines.append(f"- {f.tool_name}: {f.error}")
            if f.context:
                lines.append(f"  Context: {f.context}")

        return "\n".join(lines)

    def inject_failure_context(
        self,
        messages: list[Message | Any],
    ) -> list[Message | Any]:
        """Inject failure evidence before the last user message."""
        context = self.get_failure_context()
        if not context:
            return messages

        result = list(messages)
        last_user_idx = None
        for i in range(len(result) - 1, -1, -1):
            if hasattr(result[i], "role") and result[i].role == Role.USER:
                last_user_idx = i
                break

        if last_user_idx is not None:
            result.insert(last_user_idx, Message(
                role=Role.SYSTEM,
                content=context,
            ))

        return result

    def serialize(
        self,
        content: str,
        *,
        diversity_enabled: bool | None = None,
    ) -> str:
        """Serialize content with optional diversity for cache-busting.

        When diversity is enabled, routes through DiverseSerializer
        to vary formatting and prevent excessive KV cache hits that
        could lead to stale completions.
        """
        use_diversity = diversity_enabled if diversity_enabled is not None else self._diversity_enabled
        if not use_diversity:
            return content

        try:
            from attocode.tricks.serialization_diversity import DiverseSerializer
            serializer = DiverseSerializer()
            return serializer.serialize(content)
        except Exception:
            return content

    @property
    def failure_count(self) -> int:
        return len(self._failures)

    @property
    def recent_failures(self) -> list[FailureRecord]:
        return list(self._failures[-5:])

    @property
    def injection_budget(self) -> InjectionBudget:
        return self._injection_budget

    def reset(self) -> None:
        """Reset all state."""
        self.goals.clear()
        self._failures.clear()
        self._last_recitation = 0
        self._context_blocks.clear()
        self._injection_budget.used_tokens = 0
