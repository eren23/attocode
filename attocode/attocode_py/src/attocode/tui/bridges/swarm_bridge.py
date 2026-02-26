"""Swarm Bridge — connects SwarmOrchestrator events to Textual TUI.

Subscribes to the orchestrator's EventBus and posts Textual Messages
that TUI widgets can handle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.message import Message

if TYPE_CHECKING:
    from textual.app import App

    from attoswarm.coordinator.event_bus import EventBus, SwarmEvent


class SwarmDashboardUpdate(Message):
    """Carries a swarm state snapshot to the TUI."""

    def __init__(self, state: dict[str, Any]) -> None:
        super().__init__()
        self.state = state


class SwarmEventMessage(Message):
    """Carries a single SwarmEvent to the TUI."""

    def __init__(self, event: dict[str, Any]) -> None:
        super().__init__()
        self.event = event


class SwarmBridge:
    """Bridges orchestrator ``EventBus`` events to Textual ``Message`` objects.

    Usage::

        bridge = SwarmBridge(app)
        bridge.connect(orchestrator.event_bus)
    """

    def __init__(self, app: "App") -> None:
        self._app = app
        self._event_bus: EventBus | None = None

    def connect(self, event_bus: "EventBus") -> None:
        """Subscribe to the event bus."""
        self._event_bus = event_bus
        event_bus.subscribe(self._on_event)

    def disconnect(self) -> None:
        """Unsubscribe."""
        if self._event_bus:
            self._event_bus.unsubscribe(self._on_event)
            self._event_bus = None

    def _on_event(self, event: "SwarmEvent") -> None:
        """Convert EventBus events to Textual messages."""
        try:
            self._app.post_message(SwarmEventMessage({
                "type": event.event_type,
                "timestamp": event.timestamp,
                "task_id": event.task_id,
                "agent_id": event.agent_id,
                "message": event.message,
                "data": event.data,
            }))
        except Exception:
            pass  # App may not be running
