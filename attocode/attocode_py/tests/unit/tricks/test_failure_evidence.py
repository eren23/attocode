"""Tests for failure evidence preservation (Trick S)."""

from __future__ import annotations

import time

from attocode.tricks.failure_evidence import (
    FailureTracker,
    FailureTrackerConfig,
    FailureInput,
    FailureCategory,
    categorize_error,
    generate_suggestion,
    Failure,
)


class TestRecordFailure:
    def test_returns_failure_object(self):
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="edit_file",
            error="FileNotFoundError: /tmp/missing.py",
        ))
        assert isinstance(failure, Failure)
        assert failure.action == "edit_file"
        assert "FileNotFoundError" in failure.error
        assert failure.id.startswith("fail-")
        assert failure.resolved is False

    def test_auto_categorizes(self):
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="read_file",
            error="FileNotFoundError: no such file /tmp/x.py",
        ))
        assert failure.category == FailureCategory.NOT_FOUND

    def test_explicit_category_overrides_auto(self):
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="bash",
            error="FileNotFoundError: no such file",
            category=FailureCategory.RUNTIME,
        ))
        assert failure.category == FailureCategory.RUNTIME

    def test_stores_args(self):
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="edit_file",
            error="failed",
            args={"path": "/src/main.py", "old_string": "foo"},
        ))
        assert failure.args is not None
        assert failure.args["path"] == "/src/main.py"

    def test_stores_iteration(self):
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="bash",
            error="timeout",
            iteration=5,
        ))
        assert failure.iteration == 5

    def test_exception_input(self):
        tracker = FailureTracker()
        exc = ValueError("bad value")
        failure = tracker.record_failure(FailureInput(
            action="tool_x",
            error=exc,
        ))
        assert "bad value" in failure.error

    def test_generates_suggestion(self):
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="bash",
            error="permission denied",
        ))
        assert failure.suggestion is not None
        assert len(failure.suggestion) > 0

    def test_enforces_max_failures(self):
        tracker = FailureTracker(FailureTrackerConfig(max_failures=3))
        for i in range(5):
            tracker.record_failure(FailureInput(
                action=f"tool_{i}",
                error=f"error {i}",
            ))
        # Only 3 most recent should remain
        assert len(tracker.get_recent_failures(100)) == 3


class TestCategorizeError:
    def test_permission(self):
        assert categorize_error("EACCES: permission denied") == FailureCategory.PERMISSION
        assert categorize_error("PermissionError: cannot write") == FailureCategory.PERMISSION

    def test_not_found(self):
        assert categorize_error("ENOENT: no such file") == FailureCategory.NOT_FOUND
        assert categorize_error("FileNotFoundError: missing") == FailureCategory.NOT_FOUND

    def test_syntax(self):
        assert categorize_error("SyntaxError: unexpected token") == FailureCategory.SYNTAX

    def test_type(self):
        assert categorize_error("TypeError: invalid type for arg") == FailureCategory.TYPE

    def test_network(self):
        assert categorize_error("ECONNREFUSED 127.0.0.1:8080") == FailureCategory.NETWORK
        assert categorize_error("ConnectionError: DNS lookup failed") == FailureCategory.NETWORK

    def test_timeout(self):
        assert categorize_error("TimeoutError: timed out after 30s") == FailureCategory.TIMEOUT
        assert categorize_error("ETIMEDOUT: connection timed out") == FailureCategory.TIMEOUT

    def test_validation(self):
        assert categorize_error("ValueError: required field missing") == FailureCategory.VALIDATION

    def test_resource(self):
        assert categorize_error("MemoryError: out of memory") == FailureCategory.RESOURCE

    def test_runtime(self):
        assert categorize_error("RuntimeError: assertion failed") == FailureCategory.RUNTIME

    def test_unknown(self):
        assert categorize_error("something completely unexpected happened") == FailureCategory.UNKNOWN


class TestGetUnresolvedFailures:
    def test_returns_only_unresolved(self):
        tracker = FailureTracker()
        f1 = tracker.record_failure(FailureInput(action="a", error="e1"))
        f2 = tracker.record_failure(FailureInput(action="b", error="e2"))
        tracker.resolve_failure(f1.id)
        unresolved = tracker.get_unresolved_failures()
        assert len(unresolved) == 1
        assert unresolved[0].id == f2.id

    def test_returns_empty_when_all_resolved(self):
        tracker = FailureTracker()
        f1 = tracker.record_failure(FailureInput(action="a", error="e1"))
        tracker.resolve_failure(f1.id)
        assert tracker.get_unresolved_failures() == []


class TestResolveFailure:
    def test_marks_failure_resolved(self):
        tracker = FailureTracker()
        f = tracker.record_failure(FailureInput(action="a", error="e"))
        assert tracker.resolve_failure(f.id) is True
        assert f.resolved is True

    def test_returns_false_for_unknown_id(self):
        tracker = FailureTracker()
        assert tracker.resolve_failure("nonexistent") is False


class TestGetFailuresByCategory:
    def test_filters_by_category(self):
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(
            action="bash", error="permission denied",
        ))
        tracker.record_failure(FailureInput(
            action="read_file", error="FileNotFoundError: missing",
        ))
        tracker.record_failure(FailureInput(
            action="edit_file", error="EACCES: not allowed",
        ))
        perms = tracker.get_failures_by_category(FailureCategory.PERMISSION)
        assert len(perms) == 2

    def test_returns_empty_for_unused_category(self):
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="a", error="timeout"))
        result = tracker.get_failures_by_category(FailureCategory.SYNTAX)
        assert result == []


class TestGetFailuresByAction:
    def test_filters_by_action(self):
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="bash", error="error 1"))
        tracker.record_failure(FailureInput(action="read_file", error="error 2"))
        tracker.record_failure(FailureInput(action="bash", error="error 3"))
        bash_failures = tracker.get_failures_by_action("bash")
        assert len(bash_failures) == 2

    def test_returns_empty_for_unknown_action(self):
        tracker = FailureTracker()
        assert tracker.get_failures_by_action("unknown_tool") == []


class TestHasRecentFailure:
    def test_detects_recent_failure(self):
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="bash", error="error"))
        assert tracker.has_recent_failure("bash", within_ms=5000) is True

    def test_no_recent_failure_for_other_action(self):
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="bash", error="error"))
        assert tracker.has_recent_failure("read_file", within_ms=5000) is False

    def test_expired_failure_not_detected(self):
        tracker = FailureTracker()
        f = tracker.record_failure(FailureInput(action="bash", error="error"))
        # Backdate the timestamp
        f.timestamp = time.time() - 120
        assert tracker.has_recent_failure("bash", within_ms=5000) is False


class TestRepeatDetection:
    def test_tracks_repeat_count(self):
        tracker = FailureTracker(FailureTrackerConfig(detect_repeats=True))
        f1 = tracker.record_failure(FailureInput(action="bash", error="command not found"))
        assert f1.repeat_count == 1
        f2 = tracker.record_failure(FailureInput(action="bash", error="command not found"))
        assert f2.repeat_count == 2
        f3 = tracker.record_failure(FailureInput(action="bash", error="command not found"))
        assert f3.repeat_count == 3

    def test_different_actions_not_counted_as_repeats(self):
        tracker = FailureTracker(FailureTrackerConfig(detect_repeats=True))
        tracker.record_failure(FailureInput(action="bash", error="command not found"))
        f2 = tracker.record_failure(FailureInput(action="read_file", error="command not found"))
        assert f2.repeat_count == 1

    def test_emits_repeat_warning_at_threshold(self):
        events: list[tuple[str, dict]] = []
        tracker = FailureTracker(FailureTrackerConfig(
            detect_repeats=True,
            repeat_warning_threshold=3,
        ))
        tracker.on(lambda event, data: events.append((event, data)))
        for _ in range(3):
            tracker.record_failure(FailureInput(action="bash", error="same error"))
        repeated_events = [e for e in events if e[0] == "failure.repeated"]
        assert len(repeated_events) == 1
        assert repeated_events[0][1]["count"] == 3


class TestGetFailureContext:
    def test_formats_unresolved_failures(self):
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(
            action="edit_file",
            error="FileNotFoundError: /src/app.py",
        ))
        ctx = tracker.get_failure_context()
        assert "[Previous Failures" in ctx
        assert "edit_file" in ctx
        assert "FileNotFoundError" in ctx

    def test_returns_empty_when_no_failures(self):
        tracker = FailureTracker()
        assert tracker.get_failure_context() == ""

    def test_returns_empty_when_all_resolved(self):
        tracker = FailureTracker()
        f = tracker.record_failure(FailureInput(action="a", error="e"))
        tracker.resolve_failure(f.id)
        assert tracker.get_failure_context() == ""

    def test_includes_resolved_when_requested(self):
        tracker = FailureTracker()
        f = tracker.record_failure(FailureInput(action="a", error="error_text"))
        tracker.resolve_failure(f.id)
        ctx = tracker.get_failure_context(include_resolved=True)
        assert "error_text" in ctx
        assert "resolved" in ctx

    def test_limits_to_max_failures(self):
        tracker = FailureTracker()
        for i in range(10):
            tracker.record_failure(FailureInput(action=f"tool_{i}", error=f"err {i}"))
        ctx = tracker.get_failure_context(max_failures=3)
        # Should only have 3 failure entries (plus the header)
        lines = [line for line in ctx.split("\n") if line.startswith("- [")]
        assert len(lines) == 3

    def test_includes_suggestions(self):
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(
            action="read_file",
            error="FileNotFoundError: /missing.py",
        ))
        ctx = tracker.get_failure_context()
        assert "Suggestion:" in ctx


class TestGenerateSuggestion:
    def test_permission_suggestion(self):
        f = Failure(
            id="f1", timestamp=0.0, action="bash",
            error="permission denied",
            category=FailureCategory.PERMISSION,
        )
        s = generate_suggestion(f)
        assert "permission" in s.lower()

    def test_not_found_suggestion(self):
        f = Failure(
            id="f2", timestamp=0.0, action="read_file",
            error="not found",
            category=FailureCategory.NOT_FOUND,
        )
        s = generate_suggestion(f)
        assert "path" in s.lower() or "glob" in s.lower() or "find" in s.lower()

    def test_unknown_category_suggestion(self):
        f = Failure(
            id="f3", timestamp=0.0, action="tool",
            error="something weird",
            category=FailureCategory.UNKNOWN,
        )
        s = generate_suggestion(f)
        assert len(s) > 0  # always returns something


class TestEventListener:
    def test_emits_recorded_event(self):
        events: list[tuple[str, dict]] = []
        tracker = FailureTracker()
        tracker.on(lambda event, data: events.append((event, data)))
        tracker.record_failure(FailureInput(action="bash", error="error"))
        recorded = [e for e in events if e[0] == "failure.recorded"]
        assert len(recorded) == 1

    def test_emits_resolved_event(self):
        events: list[tuple[str, dict]] = []
        tracker = FailureTracker()
        tracker.on(lambda event, data: events.append((event, data)))
        f = tracker.record_failure(FailureInput(action="a", error="e"))
        tracker.resolve_failure(f.id)
        resolved = [e for e in events if e[0] == "failure.resolved"]
        assert len(resolved) == 1

    def test_emits_evicted_event(self):
        events: list[tuple[str, dict]] = []
        tracker = FailureTracker(FailureTrackerConfig(max_failures=2))
        tracker.on(lambda event, data: events.append((event, data)))
        for i in range(3):
            tracker.record_failure(FailureInput(action=f"tool_{i}", error=f"err {i}"))
        evicted = [e for e in events if e[0] == "failure.evicted"]
        assert len(evicted) == 1

    def test_unsubscribe(self):
        events: list[tuple[str, dict]] = []
        tracker = FailureTracker()
        unsub = tracker.on(lambda event, data: events.append((event, data)))
        tracker.record_failure(FailureInput(action="a", error="e"))
        assert len(events) > 0
        unsub()
        events.clear()
        tracker.record_failure(FailureInput(action="b", error="e2"))
        assert len(events) == 0
