"""Injection budget manager for contextual injections.

Manages a fixed token budget (~1,500 tokens) for injecting contextual
information into the system prompt. Injections are prioritized by slot
(0 = highest priority, 4 = lowest) and trimmed to fit the budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from attocode.integrations.utilities.token_estimate import estimate_tokens


@dataclass(slots=True)
class Injection:
    """A contextual injection for the system prompt."""

    key: str
    content: str
    priority: int  # 0 = highest, 4 = lowest
    tokens: int = 0
    source: str = ""  # e.g. 'recitation', 'failure_evidence', 'phase_tracker'
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.tokens == 0:
            self.tokens = estimate_tokens(self.content)


@dataclass
class InjectionBudgetManager:
    """Manages a fixed token budget for contextual injections.

    Injections are organized by priority slots (0-4).
    When the budget is exceeded, lower-priority injections are trimmed first.
    """

    max_tokens: int = 1500
    _injections: dict[str, Injection] = field(default_factory=dict, repr=False)

    def set(
        self,
        key: str,
        content: str,
        priority: int = 2,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Set or update an injection.

        Args:
            key: Unique key for this injection.
            content: The text content to inject.
            priority: Priority slot (0=highest, 4=lowest).
            source: Source identifier.
            metadata: Additional metadata.

        Returns:
            True if the injection was added/updated.
        """
        priority = max(0, min(4, priority))
        injection = Injection(
            key=key,
            content=content,
            priority=priority,
            source=source,
            metadata=metadata or {},
        )
        self._injections[key] = injection
        self._trim_to_budget()
        return key in self._injections

    def remove(self, key: str) -> bool:
        """Remove an injection by key."""
        return self._injections.pop(key, None) is not None

    def get(self, key: str) -> Injection | None:
        """Get an injection by key."""
        return self._injections.get(key)

    def clear(self) -> None:
        """Remove all injections."""
        self._injections.clear()

    @property
    def total_tokens(self) -> int:
        """Total token count of all active injections."""
        return sum(inj.tokens for inj in self._injections.values())

    @property
    def remaining_tokens(self) -> int:
        """Remaining budget tokens."""
        return max(0, self.max_tokens - self.total_tokens)

    @property
    def count(self) -> int:
        """Number of active injections."""
        return len(self._injections)

    def build_injection_text(self) -> str:
        """Build the combined injection text sorted by priority.

        Returns:
            Combined text of all injections, highest priority first.
        """
        if not self._injections:
            return ""

        sorted_injections = sorted(
            self._injections.values(),
            key=lambda inj: inj.priority,
        )
        return "\n\n".join(inj.content for inj in sorted_injections)

    def get_injections_by_priority(self) -> dict[int, list[Injection]]:
        """Get injections grouped by priority slot."""
        groups: dict[int, list[Injection]] = {}
        for inj in self._injections.values():
            groups.setdefault(inj.priority, []).append(inj)
        return groups

    def format_summary(self) -> str:
        """Format a summary of the injection budget state."""
        used = self.total_tokens
        lines = [
            f"Injection budget: {used}/{self.max_tokens} tokens "
            f"({self.count} injections)",
        ]
        for inj in sorted(self._injections.values(), key=lambda i: i.priority):
            lines.append(
                f"  [{inj.priority}] {inj.key}: {inj.tokens} tokens"
                + (f" ({inj.source})" if inj.source else "")
            )
        return "\n".join(lines)

    def _trim_to_budget(self) -> None:
        """Trim lowest-priority injections to fit within budget."""
        while self.total_tokens > self.max_tokens and self._injections:
            # Find the lowest priority (highest number) injection
            worst = max(
                self._injections.values(),
                key=lambda inj: (inj.priority, inj.tokens),
            )
            del self._injections[worst.key]
