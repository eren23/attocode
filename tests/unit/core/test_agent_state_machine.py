"""Tests for agent state machine."""

from __future__ import annotations

from typing import Any

import pytest

from attocode.core.agent_state_machine import (
    VALID_TRANSITIONS,
    AgentLifecycleState,
    AgentStateMachine,
    InvalidTransitionError,
)


@pytest.fixture
def sm() -> AgentStateMachine:
    return AgentStateMachine()


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_starts_in_idle(self, sm: AgentStateMachine) -> None:
        assert sm.state == AgentLifecycleState.IDLE

    def test_history_is_empty(self, sm: AgentStateMachine) -> None:
        assert sm.history == []

    def test_is_terminal_initially(self, sm: AgentStateMachine) -> None:
        """IDLE is considered terminal (the agent is not running)."""
        assert sm.is_terminal is True

    def test_is_not_active_initially(self, sm: AgentStateMachine) -> None:
        assert sm.is_active is False


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------


class TestValidTransitions:
    """Exercise every edge declared in VALID_TRANSITIONS."""

    def test_idle_to_initializing(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        assert sm.state == AgentLifecycleState.INITIALIZING

    def test_initializing_to_running(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        assert sm.state == AgentLifecycleState.RUNNING

    def test_initializing_to_error(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.ERROR)
        assert sm.state == AgentLifecycleState.ERROR

    def test_running_to_paused(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.PAUSED)
        assert sm.state == AgentLifecycleState.PAUSED

    def test_running_to_completing(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.COMPLETING)
        assert sm.state == AgentLifecycleState.COMPLETING

    def test_running_to_error(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.ERROR)
        assert sm.state == AgentLifecycleState.ERROR

    def test_paused_to_running(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.PAUSED)
        sm.transition(AgentLifecycleState.RUNNING)
        assert sm.state == AgentLifecycleState.RUNNING

    def test_paused_to_completing(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.PAUSED)
        sm.transition(AgentLifecycleState.COMPLETING)
        assert sm.state == AgentLifecycleState.COMPLETING

    def test_paused_to_error(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.PAUSED)
        sm.transition(AgentLifecycleState.ERROR)
        assert sm.state == AgentLifecycleState.ERROR

    def test_completing_to_idle(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.COMPLETING)
        sm.transition(AgentLifecycleState.IDLE)
        assert sm.state == AgentLifecycleState.IDLE

    def test_completing_to_error(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.COMPLETING)
        sm.transition(AgentLifecycleState.ERROR)
        assert sm.state == AgentLifecycleState.ERROR

    def test_error_to_idle(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.ERROR)
        sm.transition(AgentLifecycleState.IDLE)
        assert sm.state == AgentLifecycleState.IDLE

    # Dispose from every non-disposed state
    @pytest.mark.parametrize(
        "setup_states",
        [
            [],  # IDLE
            [AgentLifecycleState.INITIALIZING],
            [AgentLifecycleState.INITIALIZING, AgentLifecycleState.RUNNING],
            [
                AgentLifecycleState.INITIALIZING,
                AgentLifecycleState.RUNNING,
                AgentLifecycleState.PAUSED,
            ],
            [
                AgentLifecycleState.INITIALIZING,
                AgentLifecycleState.RUNNING,
                AgentLifecycleState.COMPLETING,
            ],
            [AgentLifecycleState.INITIALIZING, AgentLifecycleState.ERROR],
        ],
        ids=[
            "idle->disposed",
            "initializing->disposed",
            "running->disposed",
            "paused->disposed",
            "completing->disposed",
            "error->disposed",
        ],
    )
    def test_dispose_from_any_state(
        self, sm: AgentStateMachine, setup_states: list[AgentLifecycleState]
    ) -> None:
        for s in setup_states:
            sm.transition(s)
        sm.transition(AgentLifecycleState.DISPOSED)
        assert sm.state == AgentLifecycleState.DISPOSED

    def test_full_happy_path(self, sm: AgentStateMachine) -> None:
        """IDLE -> INITIALIZING -> RUNNING -> COMPLETING -> IDLE."""
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.COMPLETING)
        sm.transition(AgentLifecycleState.IDLE)
        assert sm.state == AgentLifecycleState.IDLE
        assert len(sm.history) == 4


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    def test_idle_to_running_is_invalid(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError) as exc_info:
            sm.transition(AgentLifecycleState.RUNNING)
        assert exc_info.value.from_state == AgentLifecycleState.IDLE
        assert exc_info.value.to_state == AgentLifecycleState.RUNNING

    def test_idle_to_paused_is_invalid(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.PAUSED)

    def test_idle_to_completing_is_invalid(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.COMPLETING)

    def test_idle_to_error_is_invalid(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.ERROR)

    def test_initializing_to_paused_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.PAUSED)

    def test_initializing_to_completing_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.COMPLETING)

    def test_running_to_idle_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.IDLE)

    def test_running_to_initializing_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.INITIALIZING)

    def test_paused_to_idle_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.PAUSED)
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.IDLE)

    def test_completing_to_running_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.RUNNING)
        sm.transition(AgentLifecycleState.COMPLETING)
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.RUNNING)

    def test_error_to_running_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        sm.transition(AgentLifecycleState.ERROR)
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.RUNNING)

    def test_disposed_to_anything_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.DISPOSED)
        for state in AgentLifecycleState:
            with pytest.raises(InvalidTransitionError):
                sm.transition(state)

    def test_state_unchanged_on_invalid_transition(self, sm: AgentStateMachine) -> None:
        """After a failed transition the state must remain unchanged."""
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.RUNNING)
        assert sm.state == AgentLifecycleState.IDLE

    def test_history_unchanged_on_invalid_transition(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.RUNNING)
        assert sm.history == []

    def test_error_message_contains_states(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError, match="idle.*running"):
            sm.transition(AgentLifecycleState.RUNNING)


# ---------------------------------------------------------------------------
# can_transition
# ---------------------------------------------------------------------------


class TestCanTransition:
    def test_valid_returns_true(self, sm: AgentStateMachine) -> None:
        assert sm.can_transition(AgentLifecycleState.INITIALIZING) is True

    def test_invalid_returns_false(self, sm: AgentStateMachine) -> None:
        assert sm.can_transition(AgentLifecycleState.RUNNING) is False

    def test_does_not_mutate_state(self, sm: AgentStateMachine) -> None:
        sm.can_transition(AgentLifecycleState.INITIALIZING)
        assert sm.state == AgentLifecycleState.IDLE
        assert sm.history == []

    def test_all_declared_transitions_pass_can_transition(self) -> None:
        """Every pair in VALID_TRANSITIONS must pass can_transition when in from_state."""
        for from_state, to_state in VALID_TRANSITIONS:
            sm = AgentStateMachine()
            sm._state = from_state  # force state for exhaustive check
            assert sm.can_transition(to_state), f"Expected {from_state}->{to_state} to be valid"


# ---------------------------------------------------------------------------
# Convenience methods
# ---------------------------------------------------------------------------


class TestConvenienceMethods:
    def test_initialize(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        assert sm.state == AgentLifecycleState.INITIALIZING

    def test_start(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        assert sm.state == AgentLifecycleState.RUNNING

    def test_pause(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.pause()
        assert sm.state == AgentLifecycleState.PAUSED

    def test_resume(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.pause()
        sm.resume()
        assert sm.state == AgentLifecycleState.RUNNING

    def test_complete(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.complete()
        assert sm.state == AgentLifecycleState.COMPLETING

    def test_finish(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.complete()
        sm.finish()
        assert sm.state == AgentLifecycleState.IDLE

    def test_fail_from_running(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.fail("something broke")
        assert sm.state == AgentLifecycleState.ERROR

    def test_fail_from_initializing(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail("init failure")
        assert sm.state == AgentLifecycleState.ERROR

    def test_fail_from_paused(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.pause()
        sm.fail("paused failure")
        assert sm.state == AgentLifecycleState.ERROR

    def test_fail_from_completing(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.complete()
        sm.fail("completion failure")
        assert sm.state == AgentLifecycleState.ERROR

    def test_dispose(self, sm: AgentStateMachine) -> None:
        sm.dispose()
        assert sm.state == AgentLifecycleState.DISPOSED

    def test_initialize_from_wrong_state_raises(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        with pytest.raises(InvalidTransitionError):
            sm.initialize()

    def test_pause_from_idle_raises(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.pause()

    def test_resume_from_idle_raises(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.resume()

    def test_complete_from_idle_raises(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.complete()

    def test_finish_from_idle_raises(self, sm: AgentStateMachine) -> None:
        """finish() calls transition(IDLE); IDLE->IDLE is not a valid transition."""
        with pytest.raises(InvalidTransitionError):
            sm.finish()

    def test_fail_from_idle_raises(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.fail("should not work")


# ---------------------------------------------------------------------------
# Transition listeners
# ---------------------------------------------------------------------------


class TestTransitionListeners:
    def test_listener_called_on_transition(self, sm: AgentStateMachine) -> None:
        calls: list[tuple[AgentLifecycleState, AgentLifecycleState, dict[str, Any]]] = []
        sm.on_transition(lambda f, t, m: calls.append((f, t, m)))
        sm.transition(AgentLifecycleState.INITIALIZING)
        assert len(calls) == 1
        assert calls[0] == (AgentLifecycleState.IDLE, AgentLifecycleState.INITIALIZING, {})

    def test_listener_receives_metadata(self, sm: AgentStateMachine) -> None:
        calls: list[dict[str, Any]] = []
        sm.on_transition(lambda f, t, m: calls.append(m))
        sm.transition(AgentLifecycleState.INITIALIZING, metadata={"key": "value"})
        assert calls[0] == {"key": "value"}

    def test_fail_passes_error_metadata(self, sm: AgentStateMachine) -> None:
        calls: list[dict[str, Any]] = []
        sm.on_transition(lambda f, t, m: calls.append(m))
        sm.initialize()
        sm.fail("boom")
        # Second listener call is from fail()
        assert calls[1] == {"error": "boom"}

    def test_multiple_listeners(self, sm: AgentStateMachine) -> None:
        call_a: list[AgentLifecycleState] = []
        call_b: list[AgentLifecycleState] = []
        sm.on_transition(lambda f, t, m: call_a.append(t))
        sm.on_transition(lambda f, t, m: call_b.append(t))
        sm.transition(AgentLifecycleState.INITIALIZING)
        assert call_a == [AgentLifecycleState.INITIALIZING]
        assert call_b == [AgentLifecycleState.INITIALIZING]

    def test_listener_exception_does_not_break_transition(
        self, sm: AgentStateMachine
    ) -> None:
        """Listeners that raise should be silently swallowed."""
        ok_calls: list[AgentLifecycleState] = []

        def bad_listener(
            _f: AgentLifecycleState, _t: AgentLifecycleState, _m: dict[str, Any]
        ) -> None:
            raise RuntimeError("listener exploded")

        sm.on_transition(bad_listener)
        sm.on_transition(lambda f, t, m: ok_calls.append(t))

        sm.transition(AgentLifecycleState.INITIALIZING)
        # State transition still happens
        assert sm.state == AgentLifecycleState.INITIALIZING
        # Second listener still called despite first raising
        assert ok_calls == [AgentLifecycleState.INITIALIZING]

    def test_listener_not_called_on_invalid_transition(
        self, sm: AgentStateMachine
    ) -> None:
        calls: list[Any] = []
        sm.on_transition(lambda f, t, m: calls.append((f, t)))
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.RUNNING)
        assert calls == []

    def test_no_metadata_gives_empty_dict(self, sm: AgentStateMachine) -> None:
        metas: list[dict[str, Any]] = []
        sm.on_transition(lambda f, t, m: metas.append(m))
        sm.transition(AgentLifecycleState.INITIALIZING)
        assert metas[0] == {}

    def test_listener_called_for_each_transition(self, sm: AgentStateMachine) -> None:
        calls: list[tuple[AgentLifecycleState, AgentLifecycleState]] = []
        sm.on_transition(lambda f, t, m: calls.append((f, t)))
        sm.initialize()
        sm.start()
        sm.complete()
        sm.finish()
        assert len(calls) == 4
        assert calls[0] == (AgentLifecycleState.IDLE, AgentLifecycleState.INITIALIZING)
        assert calls[1] == (AgentLifecycleState.INITIALIZING, AgentLifecycleState.RUNNING)
        assert calls[2] == (AgentLifecycleState.RUNNING, AgentLifecycleState.COMPLETING)
        assert calls[3] == (AgentLifecycleState.COMPLETING, AgentLifecycleState.IDLE)


# ---------------------------------------------------------------------------
# History tracking
# ---------------------------------------------------------------------------


class TestHistory:
    def test_records_single_transition(self, sm: AgentStateMachine) -> None:
        sm.transition(AgentLifecycleState.INITIALIZING)
        assert sm.history == [
            (AgentLifecycleState.IDLE, AgentLifecycleState.INITIALIZING),
        ]

    def test_records_full_lifecycle(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.complete()
        sm.finish()
        expected = [
            (AgentLifecycleState.IDLE, AgentLifecycleState.INITIALIZING),
            (AgentLifecycleState.INITIALIZING, AgentLifecycleState.RUNNING),
            (AgentLifecycleState.RUNNING, AgentLifecycleState.COMPLETING),
            (AgentLifecycleState.COMPLETING, AgentLifecycleState.IDLE),
        ]
        assert sm.history == expected

    def test_history_is_a_copy(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        h1 = sm.history
        h1.clear()
        # Internal history must not have been cleared
        assert len(sm.history) == 1

    def test_invalid_transition_does_not_record(self, sm: AgentStateMachine) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.transition(AgentLifecycleState.RUNNING)
        assert sm.history == []

    def test_history_includes_error_transitions(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail("err")
        sm.finish()  # ERROR -> IDLE
        assert len(sm.history) == 3
        assert sm.history[1] == (
            AgentLifecycleState.INITIALIZING,
            AgentLifecycleState.ERROR,
        )
        assert sm.history[2] == (AgentLifecycleState.ERROR, AgentLifecycleState.IDLE)


# ---------------------------------------------------------------------------
# is_active property
# ---------------------------------------------------------------------------


class TestIsActive:
    def test_idle_not_active(self, sm: AgentStateMachine) -> None:
        assert sm.is_active is False

    def test_initializing_not_active(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        assert sm.is_active is False

    def test_running_is_active(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        assert sm.is_active is True

    def test_paused_is_active(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.pause()
        assert sm.is_active is True

    def test_completing_not_active(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.complete()
        assert sm.is_active is False

    def test_error_not_active(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail()
        assert sm.is_active is False

    def test_disposed_not_active(self, sm: AgentStateMachine) -> None:
        sm.dispose()
        assert sm.is_active is False


# ---------------------------------------------------------------------------
# is_terminal property
# ---------------------------------------------------------------------------


class TestIsTerminal:
    def test_idle_is_terminal(self, sm: AgentStateMachine) -> None:
        assert sm.is_terminal is True

    def test_disposed_is_terminal(self, sm: AgentStateMachine) -> None:
        sm.dispose()
        assert sm.is_terminal is True

    def test_initializing_not_terminal(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        assert sm.is_terminal is False

    def test_running_not_terminal(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        assert sm.is_terminal is False

    def test_paused_not_terminal(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.pause()
        assert sm.is_terminal is False

    def test_completing_not_terminal(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.complete()
        assert sm.is_terminal is False

    def test_error_not_terminal(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail()
        assert sm.is_terminal is False


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_returns_to_idle(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.reset()
        assert sm.state == AgentLifecycleState.IDLE

    def test_reset_clears_history(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.reset()
        assert sm.history == []

    def test_reset_from_error(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail("err")
        sm.reset()
        assert sm.state == AgentLifecycleState.IDLE
        assert sm.history == []

    def test_reset_from_disposed(self, sm: AgentStateMachine) -> None:
        sm.dispose()
        sm.reset()
        assert sm.state == AgentLifecycleState.IDLE

    def test_reset_preserves_listeners(self, sm: AgentStateMachine) -> None:
        calls: list[AgentLifecycleState] = []
        sm.on_transition(lambda f, t, m: calls.append(t))
        sm.initialize()
        sm.reset()
        # After reset, listener should still fire on new transitions
        sm.initialize()
        assert calls == [AgentLifecycleState.INITIALIZING, AgentLifecycleState.INITIALIZING]

    def test_reset_allows_fresh_lifecycle(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.complete()
        sm.finish()
        sm.reset()
        # Should be able to run the full lifecycle again
        sm.initialize()
        sm.start()
        sm.complete()
        sm.finish()
        assert sm.state == AgentLifecycleState.IDLE
        assert len(sm.history) == 4


# ---------------------------------------------------------------------------
# Error state transitions
# ---------------------------------------------------------------------------


class TestErrorTransitions:
    """Any active/transient state can fail(), and error can recover to idle."""

    def test_fail_from_initializing(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail("init error")
        assert sm.state == AgentLifecycleState.ERROR

    def test_fail_from_running(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.fail("runtime error")
        assert sm.state == AgentLifecycleState.ERROR

    def test_fail_from_paused(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.pause()
        sm.fail("paused error")
        assert sm.state == AgentLifecycleState.ERROR

    def test_fail_from_completing(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.start()
        sm.complete()
        sm.fail("completion error")
        assert sm.state == AgentLifecycleState.ERROR

    def test_error_recovery_to_idle(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail("err")
        sm.finish()
        assert sm.state == AgentLifecycleState.IDLE

    def test_error_to_disposed(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail("err")
        sm.dispose()
        assert sm.state == AgentLifecycleState.DISPOSED

    def test_error_to_error_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail("err")
        with pytest.raises(InvalidTransitionError):
            sm.fail("double error")

    def test_error_to_running_is_invalid(self, sm: AgentStateMachine) -> None:
        sm.initialize()
        sm.fail("err")
        with pytest.raises(InvalidTransitionError):
            sm.start()

    def test_fail_metadata_is_passed(self, sm: AgentStateMachine) -> None:
        metas: list[dict[str, Any]] = []
        sm.on_transition(lambda f, t, m: metas.append(m))
        sm.initialize()
        sm.fail("uh oh")
        # First call is initialize (empty meta), second is fail
        assert metas[1] == {"error": "uh oh"}

    def test_fail_with_empty_error_string(self, sm: AgentStateMachine) -> None:
        metas: list[dict[str, Any]] = []
        sm.on_transition(lambda f, t, m: metas.append(m))
        sm.initialize()
        sm.fail()
        assert metas[1] == {"error": ""}


# ---------------------------------------------------------------------------
# InvalidTransitionError details
# ---------------------------------------------------------------------------


class TestInvalidTransitionError:
    def test_attributes(self) -> None:
        err = InvalidTransitionError(AgentLifecycleState.IDLE, AgentLifecycleState.RUNNING)
        assert err.from_state == AgentLifecycleState.IDLE
        assert err.to_state == AgentLifecycleState.RUNNING

    def test_message_format(self) -> None:
        err = InvalidTransitionError(
            AgentLifecycleState.PAUSED, AgentLifecycleState.INITIALIZING
        )
        assert "paused" in str(err)
        assert "initializing" in str(err)

    def test_is_exception(self) -> None:
        err = InvalidTransitionError(AgentLifecycleState.IDLE, AgentLifecycleState.RUNNING)
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# AgentLifecycleState enum
# ---------------------------------------------------------------------------


class TestAgentLifecycleState:
    def test_all_states_exist(self) -> None:
        expected = {"idle", "initializing", "running", "paused", "completing", "error", "disposed"}
        actual = {s.value for s in AgentLifecycleState}
        assert actual == expected

    def test_str_enum_values(self) -> None:
        assert str(AgentLifecycleState.IDLE) == "idle"
        assert str(AgentLifecycleState.RUNNING) == "running"

    def test_is_str_subclass(self) -> None:
        assert isinstance(AgentLifecycleState.IDLE, str)


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS completeness check
# ---------------------------------------------------------------------------


class TestValidTransitionsTable:
    def test_no_self_transitions(self) -> None:
        """No state should transition to itself."""
        for from_state, to_state in VALID_TRANSITIONS:
            assert from_state != to_state, f"Self-transition found: {from_state}"

    def test_disposed_has_no_outgoing(self) -> None:
        """DISPOSED is a terminal sink -- nothing goes out."""
        outgoing = [t for f, t in VALID_TRANSITIONS if f == AgentLifecycleState.DISPOSED]
        assert outgoing == []

    def test_every_non_disposed_can_reach_disposed(self) -> None:
        """Every non-DISPOSED state should have a transition to DISPOSED."""
        for state in AgentLifecycleState:
            if state == AgentLifecycleState.DISPOSED:
                continue
            assert (state, AgentLifecycleState.DISPOSED) in VALID_TRANSITIONS, (
                f"{state} cannot reach DISPOSED"
            )
