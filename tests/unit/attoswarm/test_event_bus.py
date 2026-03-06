"""Tests for the SwarmEvent bus."""

from __future__ import annotations

from attoswarm.coordinator.event_bus import EventBus, SwarmEvent


class TestEventBus:
    def test_emit_and_history(self) -> None:
        bus = EventBus()
        bus.emit(SwarmEvent(event_type="test", message="hello"))
        assert len(bus.history) == 1
        assert bus.history[0].event_type == "test"
        assert bus.history[0].message == "hello"

    def test_subscribe_receives_events(self) -> None:
        bus = EventBus()
        received: list[SwarmEvent] = []
        bus.subscribe(received.append)
        bus.emit(SwarmEvent(event_type="spawn", agent_id="a1"))
        assert len(received) == 1
        assert received[0].agent_id == "a1"

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[SwarmEvent] = []
        # Store a stable reference — bound methods create new objects each time
        cb = received.append
        bus.subscribe(cb)
        bus.unsubscribe(cb)
        bus.emit(SwarmEvent(event_type="test"))
        assert len(received) == 0

    def test_recent(self) -> None:
        bus = EventBus()
        for i in range(10):
            bus.emit(SwarmEvent(event_type=f"e{i}"))
        recent = bus.recent(3)
        assert len(recent) == 3
        assert recent[0].event_type == "e7"

    def test_timestamp_auto_set(self) -> None:
        bus = EventBus()
        bus.emit(SwarmEvent(event_type="test"))
        assert bus.history[0].timestamp > 0

    def test_subscriber_error_does_not_propagate(self) -> None:
        bus = EventBus()

        def bad_callback(event: SwarmEvent) -> None:
            raise RuntimeError("boom")

        bus.subscribe(bad_callback)
        # Should not raise
        bus.emit(SwarmEvent(event_type="test"))
        assert len(bus.history) == 1
