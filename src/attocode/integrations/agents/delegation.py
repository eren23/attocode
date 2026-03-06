"""Delegation protocol for task assignment between agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DelegationStatus(StrEnum):
    """Status of a delegated task."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class DelegationRequest:
    """A request to delegate work to another agent."""

    task_id: str
    description: str
    delegator: str  # Agent ID of the delegator
    delegate: str | None = None  # Target agent ID (None = auto-select)
    agent_type: str | None = None  # Preferred agent type
    tools: list[str] | None = None  # Tool subset
    context: str = ""  # Additional context
    max_iterations: int = 30
    priority: int = 2  # 1=high, 2=normal, 3=low
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DelegationResult:
    """Result of a delegated task."""

    task_id: str
    status: DelegationStatus
    delegate: str  # Agent ID that handled it
    response: str = ""
    error: str | None = None
    tokens_used: int = 0
    duration_ms: float = 0.0
    artifacts: dict[str, Any] = field(default_factory=dict)


class DelegationProtocol:
    """Manages task delegation between agents.

    Tracks delegation requests and results, enforces
    constraints, and provides status queries.
    """

    def __init__(self) -> None:
        self._requests: dict[str, DelegationRequest] = {}
        self._results: dict[str, DelegationResult] = {}
        self._active: dict[str, str] = {}  # task_id -> delegate agent_id

    def submit(self, request: DelegationRequest) -> str:
        """Submit a delegation request. Returns task_id."""
        self._requests[request.task_id] = request
        return request.task_id

    def accept(self, task_id: str, delegate: str) -> bool:
        """Accept a delegation request."""
        req = self._requests.get(task_id)
        if req is None:
            return False
        self._active[task_id] = delegate
        return True

    def complete(self, result: DelegationResult) -> None:
        """Mark a delegation as completed."""
        self._results[result.task_id] = result
        self._active.pop(result.task_id, None)

    def get_request(self, task_id: str) -> DelegationRequest | None:
        """Get a delegation request."""
        return self._requests.get(task_id)

    def get_result(self, task_id: str) -> DelegationResult | None:
        """Get a delegation result."""
        return self._results.get(task_id)

    def get_pending(self) -> list[DelegationRequest]:
        """Get all pending (unaccepted) requests."""
        return [
            req
            for req in self._requests.values()
            if req.task_id not in self._active
            and req.task_id not in self._results
        ]

    def get_active(self) -> list[tuple[DelegationRequest, str]]:
        """Get all active delegations with their delegates."""
        result = []
        for task_id, delegate in self._active.items():
            req = self._requests.get(task_id)
            if req:
                result.append((req, delegate))
        return result

    def get_agent_delegations(self, agent_id: str) -> list[DelegationRequest]:
        """Get all delegations assigned to an agent."""
        return [
            self._requests[tid]
            for tid, delegate in self._active.items()
            if delegate == agent_id and tid in self._requests
        ]

    def cancel(self, task_id: str) -> bool:
        """Cancel a delegation."""
        if task_id in self._requests:
            self._active.pop(task_id, None)
            self._results[task_id] = DelegationResult(
                task_id=task_id,
                status=DelegationStatus.REJECTED,
                delegate="",
                error="Cancelled",
            )
            return True
        return False

    def clear(self) -> None:
        """Clear all delegation state."""
        self._requests.clear()
        self._results.clear()
        self._active.clear()
