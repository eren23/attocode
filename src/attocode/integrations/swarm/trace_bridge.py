"""SwarmTraceBridge — routes EventBus events into TraceCollector.

Subscribes to the attoswarm EventBus and forwards events to the
attocode TraceCollector so that swarm decisions, conflicts, budget
projections, and failures appear in the trace JSONL for post-hoc
analysis and inefficiency detection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.tracing.collector import TraceCollector
    from attoswarm.coordinator.event_bus import EventBus, SwarmEvent

logger = logging.getLogger(__name__)


class SwarmTraceBridge:
    """Bridges ``EventBus`` events to ``TraceCollector.record_swarm_*()``."""

    def __init__(self, event_bus: EventBus, collector: TraceCollector) -> None:
        self._collector = collector
        self._event_bus = event_bus
        event_bus.subscribe(self._on_event)

    def _on_event(self, event: SwarmEvent) -> None:
        try:
            self._route(event)
        except Exception as exc:
            logger.debug("SwarmTraceBridge error: %s", exc)

    def _route(self, event: SwarmEvent) -> None:
        from attocode.tracing.types import TraceEventKind

        etype = event.event_type
        data: dict[str, Any] = event.data or {}

        if etype == "decision" or (etype == "info" and "decision" in data):
            self._collector.record_swarm_decision(
                decision=data.get("decision", event.message),
                phase=data.get("phase", ""),
                reasoning=data.get("reasoning", ""),
            )
        elif etype == "conflict":
            self._collector.record_swarm_conflict(
                file_path=data.get("file_path", ""),
                symbol=data.get("symbol_name", ""),
                resolution=data.get("resolution", ""),
            )
        elif etype == "budget":
            projection = data.get("projection", data)
            self._collector.record_swarm_budget_projection(projection)
        elif etype == "fail":
            failure = data.get("failure", {})
            self._collector.record_swarm_failure(
                task_id=event.task_id,
                cause=failure.get("cause", event.message),
                evidence=failure.get("evidence", ""),
            )
            # Also emit SWARM_TASK_FAILED for cascade failure detector
            self._collector.record(
                TraceEventKind.SWARM_TASK_FAILED,
                task_id=event.task_id,
                agent_id=event.agent_id,
                skipped=data.get("skipped", []),
            )
        elif etype == "spawn":
            # Task starting — needed by cascade failure detector
            self._collector.record(
                TraceEventKind.SWARM_TASK_START,
                task_id=event.task_id,
                agent_id=event.agent_id,
                message=event.message,
            )
        elif etype == "complete" and event.task_id:
            # Task completed successfully
            self._collector.record(
                TraceEventKind.SWARM_TASK_COMPLETE,
                task_id=event.task_id,
                agent_id=event.agent_id,
                **data,
            )
        elif etype == "info" and "Batch" in event.message:
            # Wave/batch start — needed by excessive conflicts detector
            self._collector.record(
                TraceEventKind.SWARM_WAVE_START,
                message=event.message,
                **data,
            )

    def detach(self) -> None:
        """Unsubscribe from the event bus."""
        self._event_bus.unsubscribe(self._on_event)
