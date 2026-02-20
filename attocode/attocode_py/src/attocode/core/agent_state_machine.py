"""Agent state machine - FSM for agent lifecycle states.

Provides formal state transitions with guards and event emissions
for the agent execution lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable


class AgentLifecycleState(StrEnum):
    """Lifecycle states for the agent."""

    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETING = "completing"
    ERROR = "error"
    DISPOSED = "disposed"


# Valid transitions: (from_state, to_state)
VALID_TRANSITIONS: set[tuple[AgentLifecycleState, AgentLifecycleState]] = {
    (AgentLifecycleState.IDLE, AgentLifecycleState.INITIALIZING),
    (AgentLifecycleState.INITIALIZING, AgentLifecycleState.RUNNING),
    (AgentLifecycleState.INITIALIZING, AgentLifecycleState.ERROR),
    (AgentLifecycleState.RUNNING, AgentLifecycleState.PAUSED),
    (AgentLifecycleState.RUNNING, AgentLifecycleState.COMPLETING),
    (AgentLifecycleState.RUNNING, AgentLifecycleState.ERROR),
    (AgentLifecycleState.PAUSED, AgentLifecycleState.RUNNING),
    (AgentLifecycleState.PAUSED, AgentLifecycleState.COMPLETING),
    (AgentLifecycleState.PAUSED, AgentLifecycleState.ERROR),
    (AgentLifecycleState.COMPLETING, AgentLifecycleState.IDLE),
    (AgentLifecycleState.COMPLETING, AgentLifecycleState.ERROR),
    (AgentLifecycleState.ERROR, AgentLifecycleState.IDLE),
    # Any state can dispose
    (AgentLifecycleState.IDLE, AgentLifecycleState.DISPOSED),
    (AgentLifecycleState.INITIALIZING, AgentLifecycleState.DISPOSED),
    (AgentLifecycleState.RUNNING, AgentLifecycleState.DISPOSED),
    (AgentLifecycleState.PAUSED, AgentLifecycleState.DISPOSED),
    (AgentLifecycleState.COMPLETING, AgentLifecycleState.DISPOSED),
    (AgentLifecycleState.ERROR, AgentLifecycleState.DISPOSED),
}


TransitionListener = Callable[[AgentLifecycleState, AgentLifecycleState, dict[str, Any]], None]


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, from_state: AgentLifecycleState, to_state: AgentLifecycleState) -> None:
        super().__init__(f"Invalid transition: {from_state} -> {to_state}")
        self.from_state = from_state
        self.to_state = to_state


@dataclass
class AgentStateMachine:
    """Manages agent lifecycle state transitions.

    Enforces valid transitions, emits events on state changes,
    and supports transition guards.
    """

    _state: AgentLifecycleState = field(default=AgentLifecycleState.IDLE)
    _listeners: list[TransitionListener] = field(default_factory=list, repr=False)
    _history: list[tuple[AgentLifecycleState, AgentLifecycleState]] = field(
        default_factory=list, repr=False,
    )

    @property
    def state(self) -> AgentLifecycleState:
        return self._state

    @property
    def is_active(self) -> bool:
        """Whether the agent is in an active state (running or paused)."""
        return self._state in (AgentLifecycleState.RUNNING, AgentLifecycleState.PAUSED)

    @property
    def is_terminal(self) -> bool:
        """Whether the agent is in a terminal state."""
        return self._state in (AgentLifecycleState.IDLE, AgentLifecycleState.DISPOSED)

    @property
    def history(self) -> list[tuple[AgentLifecycleState, AgentLifecycleState]]:
        return list(self._history)

    def can_transition(self, to_state: AgentLifecycleState) -> bool:
        """Check if a transition is valid without performing it."""
        return (self._state, to_state) in VALID_TRANSITIONS

    def transition(
        self,
        to_state: AgentLifecycleState,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Transition to a new state.

        Raises InvalidTransitionError if the transition is not allowed.
        """
        if not self.can_transition(to_state):
            raise InvalidTransitionError(self._state, to_state)

        from_state = self._state
        self._state = to_state
        self._history.append((from_state, to_state))

        meta = metadata or {}
        for listener in self._listeners:
            try:
                listener(from_state, to_state, meta)
            except Exception:
                pass  # Listeners should not break state transitions

    def on_transition(self, listener: TransitionListener) -> None:
        """Register a transition listener."""
        self._listeners.append(listener)

    def reset(self) -> None:
        """Reset to idle state, clearing history."""
        self._state = AgentLifecycleState.IDLE
        self._history.clear()

    # Convenience methods

    def initialize(self) -> None:
        """Transition to initializing state."""
        self.transition(AgentLifecycleState.INITIALIZING)

    def start(self) -> None:
        """Transition to running state."""
        self.transition(AgentLifecycleState.RUNNING)

    def pause(self) -> None:
        """Transition to paused state."""
        self.transition(AgentLifecycleState.PAUSED)

    def resume(self) -> None:
        """Resume from paused state."""
        self.transition(AgentLifecycleState.RUNNING)

    def complete(self) -> None:
        """Begin completion phase."""
        self.transition(AgentLifecycleState.COMPLETING)

    def finish(self) -> None:
        """Finish and return to idle."""
        self.transition(AgentLifecycleState.IDLE)

    def fail(self, error: str = "") -> None:
        """Transition to error state."""
        self.transition(AgentLifecycleState.ERROR, metadata={"error": error})

    def dispose(self) -> None:
        """Dispose of the state machine."""
        self.transition(AgentLifecycleState.DISPOSED)
