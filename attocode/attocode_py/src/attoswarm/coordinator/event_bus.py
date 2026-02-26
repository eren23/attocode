"""Event bus for swarm orchestration events.

Provides a simple pub/sub event system.  Events are emitted by the
orchestrator and consumed by the TUI bridge and persistence layer.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SwarmEvent:
    """A single swarm orchestration event."""

    event_type: str         # "spawn" | "claim" | "write" | "conflict" | "complete" | "fail" | "skip" | "budget" | "info"
    timestamp: float = field(default_factory=time.time)
    task_id: str = ""
    agent_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class EventBus:
    """In-process pub/sub for swarm events.

    Subscribers receive every emitted event.  Events are also
    optionally persisted to a JSONL file.
    """

    def __init__(self, persist_path: str | None = None) -> None:
        self._subscribers: list[Callable[[SwarmEvent], Any]] = []
        self._persist_path = persist_path
        self._history: list[SwarmEvent] = []

    def emit(self, event: SwarmEvent) -> None:
        """Emit an event to all subscribers and persist."""
        self._history.append(event)

        for cb in self._subscribers:
            try:
                cb(event)
            except Exception as exc:
                logger.debug("EventBus subscriber error: %s", exc)

        if self._persist_path:
            try:
                p = Path(self._persist_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(event)) + "\n")
            except Exception as exc:
                logger.debug("EventBus persist error: %s", exc)

    def subscribe(self, callback: Callable[[SwarmEvent], Any]) -> None:
        """Register a subscriber."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[SwarmEvent], Any]) -> None:
        """Remove a subscriber."""
        self._subscribers = [cb for cb in self._subscribers if cb is not callback]

    @property
    def history(self) -> list[SwarmEvent]:
        return list(self._history)

    def recent(self, n: int = 20) -> list[SwarmEvent]:
        """Return the *n* most recent events."""
        return self._history[-n:]
