"""Tests for goal recitation (Trick Q)."""

from __future__ import annotations

from attocode.tricks.recitation import (
    RecitationManager,
    RecitationConfig,
    RecitationState,
    PlanTask,
    PlanState,
    TodoItem,
)


class TestShouldInject:
    def test_always_injects_at_iteration_1(self):
        mgr = RecitationManager(RecitationConfig(frequency=5))
        assert mgr.should_inject(1) is True

    def test_always_injects_at_iteration_0(self):
        mgr = RecitationManager(RecitationConfig(frequency=5))
        assert mgr.should_inject(0) is True

    def test_does_not_inject_before_frequency(self):
        mgr = RecitationManager(RecitationConfig(frequency=5))
        # Simulate that last injection was at iteration 1
        mgr._last_injection_iteration = 1
        assert mgr.should_inject(3) is False
        assert mgr.should_inject(5) is False

    def test_injects_at_exact_frequency(self):
        mgr = RecitationManager(RecitationConfig(frequency=5))
        mgr._last_injection_iteration = 1
        assert mgr.should_inject(6) is True

    def test_injects_past_frequency(self):
        mgr = RecitationManager(RecitationConfig(frequency=5))
        mgr._last_injection_iteration = 1
        assert mgr.should_inject(10) is True

    def test_frequency_1_injects_every_iteration(self):
        mgr = RecitationManager(RecitationConfig(frequency=1))
        mgr._last_injection_iteration = 5
        assert mgr.should_inject(6) is True
        mgr._last_injection_iteration = 6
        assert mgr.should_inject(7) is True


class TestBuildRecitation:
    def test_returns_none_with_empty_state(self):
        mgr = RecitationManager()
        state = RecitationState()
        assert mgr.build_recitation(state) is None

    def test_includes_goal(self):
        mgr = RecitationManager(RecitationConfig(sources=["goal"]))
        state = RecitationState(goal="Fix the login bug")
        result = mgr.build_recitation(state)
        assert result is not None
        assert "Goal: Fix the login bug" in result

    def test_includes_plan_progress(self):
        mgr = RecitationManager(RecitationConfig(sources=["plan"]))
        tasks = [
            PlanTask(id="1", description="Read code", status="completed"),
            PlanTask(id="2", description="Write tests", status="pending"),
            PlanTask(id="3", description="Deploy", status="pending"),
        ]
        state = RecitationState(plan=PlanState(tasks=tasks))
        result = mgr.build_recitation(state)
        assert result is not None
        assert "1/3 tasks complete" in result
        assert "Next: Write tests" in result

    def test_includes_todos(self):
        mgr = RecitationManager(RecitationConfig(sources=["todo"]))
        state = RecitationState(todos=[
            TodoItem(content="Review PR", status="pending"),
            TodoItem(content="Update docs", status="pending"),
            TodoItem(content="Done task", status="completed"),
        ])
        result = mgr.build_recitation(state)
        assert result is not None
        assert "2 remaining" in result
        assert "Review PR" in result

    def test_includes_memories(self):
        mgr = RecitationManager(RecitationConfig(sources=["memory"]))
        state = RecitationState(memories=["User prefers Python", "CI runs on GH Actions"])
        result = mgr.build_recitation(state)
        assert result is not None
        assert "Remember: User prefers Python" in result

    def test_includes_recent_errors(self):
        mgr = RecitationManager(RecitationConfig(sources=["goal"]))
        state = RecitationState(
            goal="Build feature",
            recent_errors=["FileNotFoundError: /src/main.py"],
        )
        result = mgr.build_recitation(state)
        assert result is not None
        assert "Recent error: FileNotFoundError" in result

    def test_includes_custom_fields(self):
        mgr = RecitationManager(RecitationConfig(sources=["goal"]))
        state = RecitationState(
            goal="Task",
            custom={"Priority": "High", "Branch": "feat/login"},
        )
        result = mgr.build_recitation(state)
        assert result is not None
        assert "Priority: High" in result
        assert "Branch: feat/login" in result

    def test_truncates_to_max_tokens(self):
        mgr = RecitationManager(RecitationConfig(sources=["goal"], max_tokens=10))
        state = RecitationState(goal="A" * 500)
        result = mgr.build_recitation(state)
        assert result is not None
        assert result.endswith("...")
        assert len(result) <= 10 * 3.5 + 10  # max_chars + overhead

    def test_respects_source_config(self):
        """Only configured sources are included."""
        mgr = RecitationManager(RecitationConfig(sources=["goal"]))
        state = RecitationState(
            goal="My goal",
            plan=PlanState(tasks=[PlanTask(description="task1")]),
            todos=[TodoItem(content="todo1")],
        )
        result = mgr.build_recitation(state)
        assert result is not None
        assert "Goal: My goal" in result
        assert "Plan:" not in result
        assert "Todos:" not in result


class TestInjectIfNeeded:
    def test_appends_message_when_needed(self):
        mgr = RecitationManager(RecitationConfig(frequency=1))
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        state = RecitationState(iteration=1, goal="Fix bug")
        result = mgr.inject_if_needed(messages, state)
        assert len(result) == 3
        # Recitation inserted before last user message
        assert result[1]["role"] == "system"
        assert "[Current Status - Iteration 1]" in result[1]["content"]
        assert "Fix bug" in result[1]["content"]

    def test_does_not_inject_when_not_needed(self):
        mgr = RecitationManager(RecitationConfig(frequency=10))
        mgr._last_injection_iteration = 2
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=5, goal="Fix bug")
        result = mgr.inject_if_needed(messages, state)
        assert len(result) == 1  # unchanged

    def test_inserts_before_last_user_message(self):
        mgr = RecitationManager(RecitationConfig(frequency=1))
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "do something"},
        ]
        state = RecitationState(iteration=1, goal="Goal")
        result = mgr.inject_if_needed(messages, state)
        assert result[2]["role"] == "system"  # recitation
        assert result[3]["role"] == "user"    # last user msg stays last

    def test_updates_last_injection_iteration(self):
        mgr = RecitationManager(RecitationConfig(frequency=1))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=7, goal="Task")
        mgr.inject_if_needed(messages, state)
        assert mgr._last_injection_iteration == 7

    def test_does_not_modify_original_messages(self):
        mgr = RecitationManager(RecitationConfig(frequency=1))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1, goal="Task")
        result = mgr.inject_if_needed(messages, state)
        assert len(messages) == 1  # original unchanged
        assert len(result) == 2

    def test_returns_original_when_nothing_to_recite(self):
        mgr = RecitationManager(RecitationConfig(frequency=1))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1)  # no goal, no plan, etc.
        result = mgr.inject_if_needed(messages, state)
        assert len(result) == 1  # nothing to inject


class TestForceInject:
    def test_always_injects_regardless_of_frequency(self):
        mgr = RecitationManager(RecitationConfig(frequency=100))
        mgr._last_injection_iteration = 99
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=100, goal="Goal")
        result = mgr.force_inject(messages, state)
        assert len(result) == 2

    def test_restores_original_frequency(self):
        mgr = RecitationManager(RecitationConfig(frequency=42))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1, goal="Goal")
        mgr.force_inject(messages, state)
        assert mgr._config.frequency == 42


class TestHistory:
    def test_tracks_injection_history(self):
        mgr = RecitationManager(RecitationConfig(frequency=1, track_history=True))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1, goal="Fix bug")
        mgr.inject_if_needed(messages, state)
        history = mgr.get_history()
        assert len(history) == 1
        assert history[0].iteration == 1
        assert "Fix bug" in history[0].content

    def test_multiple_injections_build_history(self):
        mgr = RecitationManager(RecitationConfig(frequency=1, track_history=True))
        messages = [{"role": "user", "content": "Hello"}]
        for i in range(1, 4):
            state = RecitationState(iteration=i, goal=f"Goal {i}")
            mgr.inject_if_needed(messages, state)
        assert len(mgr.get_history()) == 3

    def test_history_disabled(self):
        mgr = RecitationManager(RecitationConfig(frequency=1, track_history=False))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1, goal="Goal")
        mgr.inject_if_needed(messages, state)
        assert len(mgr.get_history()) == 0

    def test_clear_history(self):
        mgr = RecitationManager(RecitationConfig(frequency=1, track_history=True))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1, goal="Goal")
        mgr.inject_if_needed(messages, state)
        assert len(mgr.get_history()) == 1
        mgr.clear_history()
        assert len(mgr.get_history()) == 0


class TestEventListener:
    def test_emits_injected_event(self):
        events: list[tuple[str, dict]] = []
        mgr = RecitationManager(RecitationConfig(frequency=1))
        mgr.on(lambda event, data: events.append((event, data)))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1, goal="Goal")
        mgr.inject_if_needed(messages, state)
        injected_events = [e for e in events if e[0] == "recitation.injected"]
        assert len(injected_events) == 1
        assert injected_events[0][1]["iteration"] == 1

    def test_emits_skipped_event(self):
        events: list[tuple[str, dict]] = []
        mgr = RecitationManager(RecitationConfig(frequency=10))
        mgr._last_injection_iteration = 5
        mgr.on(lambda event, data: events.append((event, data)))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=6, goal="Goal")
        mgr.inject_if_needed(messages, state)
        skipped_events = [e for e in events if e[0] == "recitation.skipped"]
        assert len(skipped_events) == 1

    def test_unsubscribe(self):
        events: list[tuple[str, dict]] = []
        mgr = RecitationManager(RecitationConfig(frequency=1))
        unsub = mgr.on(lambda event, data: events.append((event, data)))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1, goal="Goal")
        mgr.inject_if_needed(messages, state)
        assert len(events) > 0
        unsub()
        events.clear()
        state2 = RecitationState(iteration=2, goal="Goal")
        mgr.inject_if_needed(messages, state2)
        assert len(events) == 0

    def test_listener_exception_does_not_crash(self):
        def bad_listener(event: str, data: dict) -> None:
            raise RuntimeError("boom")

        mgr = RecitationManager(RecitationConfig(frequency=1))
        mgr.on(bad_listener)
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1, goal="Goal")
        # Should not raise
        result = mgr.inject_if_needed(messages, state)
        assert len(result) == 2
