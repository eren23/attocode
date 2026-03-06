"""Tests for DeadLetterQueue: add, drain, filter, eviction, serialization."""

from __future__ import annotations

import time

import pytest

from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue


class TestDeadLetterQueueAdd:
    """add() creates dead letters with correct fields."""

    def test_add_returns_dead_letter(self) -> None:
        dlq = DeadLetterQueue()
        dl = dlq.add(
            operation="tool_call",
            name="read_file",
            arguments={"path": "/tmp/x"},
            error="File not found",
        )
        assert dl.operation == "tool_call"
        assert dl.name == "read_file"
        assert dl.arguments == {"path": "/tmp/x"}
        assert dl.error == "File not found"
        assert dl.retry_count == 0
        assert dl.max_retries == 3

    def test_add_increments_id(self) -> None:
        dlq = DeadLetterQueue()
        dl1 = dlq.add("tool_call", "a", {}, "err1")
        dl2 = dlq.add("tool_call", "b", {}, "err2")
        assert dl1.id == "dl-0"
        assert dl2.id == "dl-1"

    def test_add_with_optional_fields(self) -> None:
        dlq = DeadLetterQueue()
        dl = dlq.add(
            operation="mcp_call",
            name="server_x",
            arguments={"q": "test"},
            error="timeout",
            max_retries=5,
            session_id="sess-1",
            iteration=10,
            metadata={"provider": "openai"},
        )
        assert dl.max_retries == 5
        assert dl.session_id == "sess-1"
        assert dl.iteration == 10
        assert dl.metadata == {"provider": "openai"}

    def test_size_increments(self) -> None:
        dlq = DeadLetterQueue()
        assert dlq.size == 0
        dlq.add("tool_call", "a", {}, "err")
        assert dlq.size == 1
        dlq.add("tool_call", "b", {}, "err")
        assert dlq.size == 2

    def test_add_timestamp_set(self) -> None:
        before = time.time()
        dlq = DeadLetterQueue()
        dl = dlq.add("tool_call", "a", {}, "err")
        after = time.time()
        assert before <= dl.timestamp <= after


class TestDrainRetryable:
    """drain_retryable returns retryable items and increments retry_count."""

    def test_drain_returns_retryable(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err1", max_retries=2)
        dlq.add("tool_call", "b", {}, "err2", max_retries=0)  # not retryable
        retryable = dlq.drain_retryable()
        assert len(retryable) == 1
        assert retryable[0].name == "a"

    def test_drain_increments_retry_count(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err", max_retries=3)
        drained = dlq.drain_retryable()
        assert drained[0].retry_count == 1

    def test_drain_removes_from_queue(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err", max_retries=2)
        assert dlq.size == 1
        dlq.drain_retryable()
        assert dlq.size == 0

    def test_drain_keeps_exhausted(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err", max_retries=0)
        dlq.drain_retryable()
        assert dlq.size == 1

    def test_drain_multiple_rounds(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err", max_retries=2)
        first = dlq.drain_retryable()
        assert first[0].retry_count == 1
        # Re-add the drained item to simulate re-enqueuing
        dlq._letters.extend(first)
        second = dlq.drain_retryable()
        assert second[0].retry_count == 2
        # Now exhausted (retry_count=2 == max_retries=2)
        dlq._letters.extend(second)
        third = dlq.drain_retryable()
        assert len(third) == 0

    def test_retryable_count(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err", max_retries=2)
        dlq.add("tool_call", "b", {}, "err", max_retries=0)
        assert dlq.retryable_count == 1


class TestGetByOperationAndName:
    """Filtering by operation type and name."""

    def test_get_by_operation(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "read_file", {}, "err1")
        dlq.add("mcp_call", "server_x", {}, "err2")
        dlq.add("tool_call", "write_file", {}, "err3")
        results = dlq.get_by_operation("tool_call")
        assert len(results) == 2
        assert all(r.operation == "tool_call" for r in results)

    def test_get_by_operation_empty(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err")
        assert dlq.get_by_operation("llm_call") == []

    def test_get_by_name(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "read_file", {}, "err1")
        dlq.add("tool_call", "read_file", {}, "err2")
        dlq.add("tool_call", "write_file", {}, "err3")
        results = dlq.get_by_name("read_file")
        assert len(results) == 2
        assert all(r.name == "read_file" for r in results)

    def test_get_by_name_empty(self) -> None:
        dlq = DeadLetterQueue()
        assert dlq.get_by_name("ghost") == []

    def test_get_all_returns_newest_first(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err1")
        dlq.add("tool_call", "b", {}, "err2")
        all_letters = dlq.get_all()
        assert all_letters[0].name == "b"
        assert all_letters[1].name == "a"


class TestRemove:
    """remove deletes a specific dead letter by ID."""

    def test_remove_existing(self) -> None:
        dlq = DeadLetterQueue()
        dl = dlq.add("tool_call", "a", {}, "err")
        assert dlq.remove(dl.id) is True
        assert dlq.size == 0

    def test_remove_nonexistent(self) -> None:
        dlq = DeadLetterQueue()
        assert dlq.remove("dl-999") is False

    def test_remove_only_target(self) -> None:
        dlq = DeadLetterQueue()
        dl1 = dlq.add("tool_call", "a", {}, "err1")
        dl2 = dlq.add("tool_call", "b", {}, "err2")
        dlq.remove(dl1.id)
        assert dlq.size == 1
        assert dlq.get_all()[0].id == dl2.id


class TestClear:
    """clear() empties the queue and returns count."""

    def test_clear_returns_count(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err1")
        dlq.add("tool_call", "b", {}, "err2")
        count = dlq.clear()
        assert count == 2
        assert dlq.size == 0

    def test_clear_empty_queue(self) -> None:
        dlq = DeadLetterQueue()
        assert dlq.clear() == 0


class TestMaxSizeEviction:
    """max_size evicts oldest entries when exceeded."""

    def test_evicts_oldest_when_over_max(self) -> None:
        dlq = DeadLetterQueue(max_size=3)
        for i in range(5):
            dlq.add("tool_call", f"tool-{i}", {}, f"err-{i}")
        assert dlq.size == 3
        all_letters = dlq.get_all()
        names = [dl.name for dl in all_letters]
        assert "tool-0" not in names
        assert "tool-1" not in names
        assert "tool-4" in names

    def test_max_size_one(self) -> None:
        dlq = DeadLetterQueue(max_size=1)
        dlq.add("tool_call", "a", {}, "err1")
        dlq.add("tool_call", "b", {}, "err2")
        assert dlq.size == 1
        assert dlq.get_all()[0].name == "b"


class TestCanRetryProperty:
    """can_retry on DeadLetter checks retry_count < max_retries."""

    def test_can_retry_true(self) -> None:
        dlq = DeadLetterQueue()
        dl = dlq.add("tool_call", "a", {}, "err", max_retries=3)
        assert dl.can_retry is True

    def test_can_retry_false_when_exhausted(self) -> None:
        dlq = DeadLetterQueue()
        dl = dlq.add("tool_call", "a", {}, "err", max_retries=0)
        assert dl.can_retry is False

    def test_can_retry_after_increments(self) -> None:
        dlq = DeadLetterQueue()
        dl = dlq.add("tool_call", "a", {}, "err", max_retries=1)
        assert dl.can_retry is True
        dl.retry_count = 1
        assert dl.can_retry is False


class TestFormatSummary:
    """format_summary produces readable output."""

    def test_empty_queue(self) -> None:
        dlq = DeadLetterQueue()
        assert "empty" in dlq.format_summary().lower()

    def test_with_entries(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "read_file", {}, "File not found")
        summary = dlq.format_summary()
        assert "1 entries" in summary
        assert "read_file" in summary
        assert "File not found" in summary

    def test_max_entries_limits_output(self) -> None:
        dlq = DeadLetterQueue()
        for i in range(10):
            dlq.add("tool_call", f"tool-{i}", {}, f"err-{i}")
        summary = dlq.format_summary(max_entries=3)
        # Header line plus up to 3 entry lines
        lines = summary.strip().split("\n")
        assert len(lines) <= 4  # 1 header + 3 entries

    def test_retryable_and_exhausted_labels(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "a", {}, "err", max_retries=3)
        dlq.add("tool_call", "b", {}, "err", max_retries=0)
        summary = dlq.format_summary()
        assert "retry" in summary
        assert "exhausted" in summary


class TestSerializationRoundTrip:
    """to_serializable / load_from_serializable preserve data."""

    def test_round_trip(self) -> None:
        dlq = DeadLetterQueue()
        dlq.add(
            operation="tool_call",
            name="read_file",
            arguments={"path": "/tmp/x"},
            error="not found",
            max_retries=5,
            session_id="s1",
            iteration=3,
            metadata={"key": "value"},
        )
        dlq.add(
            operation="mcp_call",
            name="server_y",
            arguments={},
            error="timeout",
            max_retries=2,
        )

        serialized = dlq.to_serializable()
        assert len(serialized) == 2

        # Load into a fresh queue
        dlq2 = DeadLetterQueue()
        dlq2.load_from_serializable(serialized)
        assert dlq2.size == 2

        all_letters = dlq2.get_all()
        # get_all returns newest first
        second = all_letters[0]
        first = all_letters[1]

        assert first.operation == "tool_call"
        assert first.name == "read_file"
        assert first.arguments == {"path": "/tmp/x"}
        assert first.error == "not found"
        assert first.max_retries == 5
        assert first.session_id == "s1"
        assert first.iteration == 3
        assert first.metadata == {"key": "value"}

        assert second.operation == "mcp_call"
        assert second.name == "server_y"

    def test_to_serializable_empty(self) -> None:
        dlq = DeadLetterQueue()
        assert dlq.to_serializable() == []

    def test_load_preserves_retry_count(self) -> None:
        dlq = DeadLetterQueue()
        dl = dlq.add("tool_call", "a", {}, "err", max_retries=3)
        dl.retry_count = 2
        serialized = dlq.to_serializable()
        dlq2 = DeadLetterQueue()
        dlq2.load_from_serializable(serialized)
        loaded = dlq2.get_all()[0]
        assert loaded.retry_count == 2
        assert loaded.can_retry is True

    def test_load_appends_to_existing(self) -> None:
        """load_from_serializable appends, does not replace."""
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "existing", {}, "err")
        data = [
            {
                "id": "dl-ext-1",
                "operation": "llm_call",
                "name": "gpt4",
                "arguments": {},
                "error": "rate limit",
                "timestamp": time.time(),
                "retry_count": 0,
                "max_retries": 3,
                "session_id": "",
                "iteration": 0,
                "metadata": {},
            }
        ]
        dlq.load_from_serializable(data)
        assert dlq.size == 2

    def test_load_handles_missing_optional_fields(self) -> None:
        """Fields missing from serialized data use sensible defaults."""
        dlq = DeadLetterQueue()
        data = [
            {
                "id": "dl-min",
                "operation": "tool_call",
                "name": "bash",
                "error": "killed",
                # arguments, timestamp, retry_count, etc. are missing
            }
        ]
        dlq.load_from_serializable(data)
        dl = dlq.get_all()[0]
        assert dl.id == "dl-min"
        assert dl.arguments == {}
        assert dl.retry_count == 0
        assert dl.max_retries == 3
        assert dl.session_id == ""
        assert dl.iteration == 0
        assert dl.metadata == {}
