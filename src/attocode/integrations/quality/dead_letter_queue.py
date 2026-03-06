"""Dead letter queue for tracking persistently failed operations.

Failed tool calls, MCP calls, and other operations are captured here
for post-mortem analysis and retry on session restart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DeadLetter:
    """A failed operation record."""

    id: str
    operation: str  # 'tool_call', 'mcp_call', 'llm_call', 'checkpoint'
    name: str  # tool name, mcp server, etc.
    arguments: dict[str, Any]
    error: str
    timestamp: float
    retry_count: int = 0
    max_retries: int = 3
    session_id: str = ""
    iteration: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def can_retry(self) -> bool:
        """Whether this dead letter can be retried."""
        return self.retry_count < self.max_retries

    @property
    def age_seconds(self) -> float:
        """Age of this dead letter in seconds."""
        return time.time() - self.timestamp


class DeadLetterQueue:
    """Queue for persistently tracking failed operations.

    Operations that fail after all retries are added here.
    On session restart, the queue can be drained and retried.
    """

    def __init__(self, max_size: int = 200) -> None:
        self._letters: list[DeadLetter] = []
        self._max_size = max_size
        self._next_id = 0

    def add(
        self,
        operation: str,
        name: str,
        arguments: dict[str, Any],
        error: str,
        *,
        max_retries: int = 3,
        session_id: str = "",
        iteration: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> DeadLetter:
        """Add a failed operation to the dead letter queue.

        Args:
            operation: Type of operation.
            name: Name of the tool/service.
            arguments: Arguments that were passed.
            error: Error message.
            max_retries: Max retry attempts.
            session_id: Current session ID.
            iteration: Current iteration number.
            metadata: Additional metadata.

        Returns:
            The created DeadLetter.
        """
        letter = DeadLetter(
            id=f"dl-{self._next_id}",
            operation=operation,
            name=name,
            arguments=arguments,
            error=error,
            timestamp=time.time(),
            max_retries=max_retries,
            session_id=session_id,
            iteration=iteration,
            metadata=metadata or {},
        )
        self._next_id += 1
        self._letters.append(letter)

        # Trim if over max size
        if len(self._letters) > self._max_size:
            self._letters = self._letters[-self._max_size:]

        return letter

    def drain_retryable(self) -> list[DeadLetter]:
        """Remove and return all retryable dead letters.

        Returns:
            List of dead letters that can be retried.
        """
        retryable = [dl for dl in self._letters if dl.can_retry]
        self._letters = [dl for dl in self._letters if not dl.can_retry]
        for dl in retryable:
            dl.retry_count += 1
        return retryable

    def get_all(self) -> list[DeadLetter]:
        """Get all dead letters (newest first)."""
        return list(reversed(self._letters))

    def get_by_operation(self, operation: str) -> list[DeadLetter]:
        """Get dead letters filtered by operation type."""
        return [dl for dl in reversed(self._letters) if dl.operation == operation]

    def get_by_name(self, name: str) -> list[DeadLetter]:
        """Get dead letters filtered by tool/service name."""
        return [dl for dl in reversed(self._letters) if dl.name == name]

    def remove(self, letter_id: str) -> bool:
        """Remove a specific dead letter by ID."""
        before = len(self._letters)
        self._letters = [dl for dl in self._letters if dl.id != letter_id]
        return len(self._letters) < before

    def clear(self) -> int:
        """Clear all dead letters. Returns count removed."""
        count = len(self._letters)
        self._letters.clear()
        return count

    @property
    def size(self) -> int:
        return len(self._letters)

    @property
    def retryable_count(self) -> int:
        return sum(1 for dl in self._letters if dl.can_retry)

    def format_summary(self, max_entries: int = 20) -> str:
        """Format a human-readable summary."""
        if not self._letters:
            return "Dead letter queue is empty."

        lines = [f"Dead letter queue ({len(self._letters)} entries):"]
        for dl in self._letters[-max_entries:]:
            retry_info = f"retry {dl.retry_count}/{dl.max_retries}" if dl.can_retry else "exhausted"
            lines.append(
                f"  [{dl.id}] {dl.operation}:{dl.name} — {dl.error[:80]} ({retry_info})"
            )
        return "\n".join(lines)

    def to_serializable(self) -> list[dict[str, Any]]:
        """Serialize for persistence."""
        return [
            {
                "id": dl.id,
                "operation": dl.operation,
                "name": dl.name,
                "arguments": dl.arguments,
                "error": dl.error,
                "timestamp": dl.timestamp,
                "retry_count": dl.retry_count,
                "max_retries": dl.max_retries,
                "session_id": dl.session_id,
                "iteration": dl.iteration,
                "metadata": dl.metadata,
            }
            for dl in self._letters
        ]

    def load_from_serializable(self, data: list[dict[str, Any]]) -> None:
        """Load from serialized data."""
        for item in data:
            letter = DeadLetter(
                id=item["id"],
                operation=item["operation"],
                name=item["name"],
                arguments=item.get("arguments", {}),
                error=item["error"],
                timestamp=item.get("timestamp", time.time()),
                retry_count=item.get("retry_count", 0),
                max_retries=item.get("max_retries", 3),
                session_id=item.get("session_id", ""),
                iteration=item.get("iteration", 0),
                metadata=item.get("metadata", {}),
            )
            self._letters.append(letter)
