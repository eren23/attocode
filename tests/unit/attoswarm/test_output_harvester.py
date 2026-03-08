"""Tests for attoswarm.coordinator.output_harvester.

P0 critical: the event processing pipeline (outbox read -> budget
accumulation -> task state transition) has zero coverage.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attoswarm.coordinator.output_harvester import (
    capture_partial_output,
    detect_file_changes,
    handle_completion_claim,
    harvest_outputs,
)
from attoswarm.protocol.io import read_json, write_json_atomic
from attoswarm.protocol.models import AgentOutbox


# ── Fixtures ──────────────────────────────────────────────────────────


@dataclass
class FakeAdapterEvent:
    """Mimics the minimal event interface expected by harvest_outputs."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    token_usage: dict[str, int] | None = None
    cost_usd: float | None = None
    timestamp: str = "2026-01-01T00:00:00Z"


@dataclass
class FakeHandle:
    """Mimics an agent process handle."""

    process: MagicMock = field(default_factory=lambda: MagicMock(returncode=None))
    spec: MagicMock = field(default_factory=lambda: MagicMock(cwd="/tmp/fake"))


class FakeAdapter:
    """Mimics an agent adapter with controllable output."""

    def __init__(self, events: list[FakeAdapterEvent] | None = None) -> None:
        self._events = events or []

    async def read_output(self, handle: Any, since_seq: int = 0) -> list[FakeAdapterEvent]:
        return self._events


class FakeBudget:
    """Minimal budget counter."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, str]] = []

    def add_usage(self, token_usage: Any, cost_usd: Any, text: str = "") -> None:
        self.calls.append((token_usage, cost_usd, text))


class FakeMergeQueue:
    """Minimal merge queue."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, list[str]]] = []

    def enqueue(self, task_id: str, artifacts: list[str] | None = None) -> None:
        self.enqueued.append((task_id, artifacts or []))


def _make_coordinator(
    tmp_path: Path,
    adapters: dict[str, FakeAdapter] | None = None,
    handles: dict[str, FakeHandle] | None = None,
) -> MagicMock:
    """Build a minimal mock coordinator for harvest_outputs."""
    coord = MagicMock()

    # Layout
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(exist_ok=True)
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir(exist_ok=True)
    coord.layout = {"agents": agents_dir, "locks": locks_dir}

    # Adapters and handles
    coord.adapters = adapters or {}
    coord.handles = handles or {}
    coord.outbox_cursors = {}
    coord.running_task_by_agent = {}
    coord.running_task_last_progress = {}
    coord.running_task_started_at = {}

    # Budget
    coord.budget = FakeBudget()

    # Merge queue
    coord.merge_queue = FakeMergeQueue()

    # Methods
    coord._append_event = MagicMock()
    coord._find_task = MagicMock(return_value=None)
    coord._transition_task = MagicMock()
    coord._persist_task = MagicMock()
    coord._role_type_by_agent = MagicMock(return_value="worker")
    coord._exit_reason = MagicMock(return_value="process_exit")

    return coord


# ── capture_partial_output ────────────────────────────────────────────


class TestCapturePartialOutput:
    def test_extracts_last_events(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        outbox_path = tmp_path / "agents" / "agent-w1.outbox.json"
        outbox_data = {
            "events": [
                {"type": "progress", "payload": {"line": "step 1"}},
                {"type": "progress", "payload": {"line": "step 2"}},
                {"type": "progress", "payload": {"line": "step 3"}},
                {"type": "progress", "payload": {"line": "step 4"}},
            ],
        }
        write_json_atomic(outbox_path, outbox_data)

        result = capture_partial_output(coord, "w1")
        assert "step 2" in result
        assert "step 3" in result
        assert "step 4" in result

    def test_empty_outbox(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        outbox_path = tmp_path / "agents" / "agent-w1.outbox.json"
        write_json_atomic(outbox_path, {"events": []})
        assert capture_partial_output(coord, "w1") == ""

    def test_missing_outbox_file(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        assert capture_partial_output(coord, "w1") == ""

    def test_uses_message_fallback(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        outbox_path = tmp_path / "agents" / "agent-w1.outbox.json"
        outbox_data = {
            "events": [
                {"type": "info", "payload": {"message": "doing work"}},
            ],
        }
        write_json_atomic(outbox_path, outbox_data)
        result = capture_partial_output(coord, "w1")
        assert "doing work" in result

    def test_uses_type_fallback(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        outbox_path = tmp_path / "agents" / "agent-w1.outbox.json"
        outbox_data = {
            "events": [
                {"type": "heartbeat", "payload": {}},
            ],
        }
        write_json_atomic(outbox_path, outbox_data)
        result = capture_partial_output(coord, "w1")
        assert "heartbeat" in result

    def test_truncates_long_lines(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        outbox_path = tmp_path / "agents" / "agent-w1.outbox.json"
        outbox_data = {
            "events": [
                {"type": "progress", "payload": {"line": "x" * 200}},
            ],
        }
        write_json_atomic(outbox_path, outbox_data)
        result = capture_partial_output(coord, "w1")
        assert len(result) <= 100


# ── harvest_outputs ───────────────────────────────────────────────────


class TestHarvestOutputs:
    @pytest.mark.asyncio
    async def test_no_events_no_change(self, tmp_path: Path) -> None:
        adapter = FakeAdapter(events=[])
        handle = FakeHandle()
        coord = _make_coordinator(
            tmp_path,
            adapters={"w1": adapter},
            handles={"w1": handle},
        )

        await harvest_outputs(coord)
        # No events -> no outbox cursor update
        assert coord.outbox_cursors.get("w1") is None

    @pytest.mark.asyncio
    async def test_progress_events_accumulate_budget(self, tmp_path: Path) -> None:
        events = [
            FakeAdapterEvent(
                type="progress",
                payload={"line": "processing file A"},
                token_usage={"total": 500},
                cost_usd=0.01,
            ),
            FakeAdapterEvent(
                type="progress",
                payload={"line": "processing file B"},
                token_usage={"total": 300},
                cost_usd=0.005,
            ),
        ]
        adapter = FakeAdapter(events=events)
        handle = FakeHandle()
        coord = _make_coordinator(
            tmp_path,
            adapters={"w1": adapter},
            handles={"w1": handle},
        )
        coord.running_task_by_agent = {"w1": "task-1"}

        await harvest_outputs(coord)

        # Budget should be called twice
        budget = coord.budget
        assert len(budget.calls) == 2
        assert budget.calls[0][0] == {"total": 500}
        assert budget.calls[1][0] == {"total": 300}

    @pytest.mark.asyncio
    async def test_outbox_cursor_advances(self, tmp_path: Path) -> None:
        events = [
            FakeAdapterEvent(type="progress", payload={"line": "step"}),
        ]
        adapter = FakeAdapter(events=events)
        handle = FakeHandle()
        coord = _make_coordinator(
            tmp_path,
            adapters={"w1": adapter},
            handles={"w1": handle},
        )

        await harvest_outputs(coord)
        assert coord.outbox_cursors["w1"] == 1

    @pytest.mark.asyncio
    async def test_outbox_file_persisted(self, tmp_path: Path) -> None:
        events = [
            FakeAdapterEvent(type="progress", payload={"line": "data"}),
        ]
        adapter = FakeAdapter(events=events)
        handle = FakeHandle()
        coord = _make_coordinator(
            tmp_path,
            adapters={"w1": adapter},
            handles={"w1": handle},
        )

        await harvest_outputs(coord)

        outbox_path = tmp_path / "agents" / "agent-w1.outbox.json"
        outbox = read_json(outbox_path, default={})
        assert outbox["next_seq"] == 2
        assert len(outbox["events"]) == 1
        assert outbox["events"][0]["type"] == "progress"

    @pytest.mark.asyncio
    async def test_task_done_triggers_completion(self, tmp_path: Path) -> None:
        events = [
            FakeAdapterEvent(type="task_done", payload={"result": "ok"}),
        ]
        adapter = FakeAdapter(events=events)
        handle = FakeHandle()
        coord = _make_coordinator(
            tmp_path,
            adapters={"w1": adapter},
            handles={"w1": handle},
        )
        coord.running_task_by_agent = {"w1": "task-1"}

        # Mock handle_completion_claim since it needs internal coordinator state
        with patch(
            "attoswarm.coordinator.output_harvester.handle_completion_claim",
            new_callable=AsyncMock,
        ) as mock_hcc:
            await harvest_outputs(coord)
            mock_hcc.assert_called_once_with(coord, "w1", "task-1")

    @pytest.mark.asyncio
    async def test_task_failed_triggers_failure_handler(self, tmp_path: Path) -> None:
        events = [
            FakeAdapterEvent(type="task_failed", payload={"error": "boom"}),
        ]
        adapter = FakeAdapter(events=events)
        handle = FakeHandle()
        coord = _make_coordinator(
            tmp_path,
            adapters={"w1": adapter},
            handles={"w1": handle},
        )
        coord.running_task_by_agent = {"w1": "task-1"}

        with patch(
            "attoswarm.coordinator.failure_handler.handle_task_failed",
            new_callable=AsyncMock,
        ) as mock_htf:
            await harvest_outputs(coord)
            mock_htf.assert_called_once_with(
                coord, "w1", "task-1", reason="worker_reported_failure"
            )

    @pytest.mark.asyncio
    async def test_progress_updates_last_progress_time(self, tmp_path: Path) -> None:
        events = [
            FakeAdapterEvent(type="progress", payload={"line": "still working"}),
        ]
        adapter = FakeAdapter(events=events)
        handle = FakeHandle()
        coord = _make_coordinator(
            tmp_path,
            adapters={"w1": adapter},
            handles={"w1": handle},
        )
        coord.running_task_by_agent = {"w1": "task-1"}
        coord.running_task_last_progress = {}

        await harvest_outputs(coord)
        assert "task-1" in coord.running_task_last_progress

    @pytest.mark.asyncio
    async def test_dead_process_marks_failure(self, tmp_path: Path) -> None:
        """Agent process exited without a terminal event -> mark failed."""
        adapter = FakeAdapter(events=[])
        handle = FakeHandle()
        handle.process.returncode = 1  # process exited

        coord = _make_coordinator(
            tmp_path,
            adapters={"w1": adapter},
            handles={"w1": handle},
        )
        coord.running_task_by_agent = {"w1": "task-1"}

        with patch(
            "attoswarm.coordinator.failure_handler.mark_running_task_failed",
            new_callable=AsyncMock,
        ) as mock_mrtf:
            await harvest_outputs(coord)
            mock_mrtf.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_agents(self, tmp_path: Path) -> None:
        """Multiple agents are iterated independently."""
        events_w1 = [FakeAdapterEvent(type="progress", payload={"line": "w1 work"})]
        events_w2 = [FakeAdapterEvent(type="progress", payload={"line": "w2 work"})]
        coord = _make_coordinator(
            tmp_path,
            adapters={"w1": FakeAdapter(events_w1), "w2": FakeAdapter(events_w2)},
            handles={"w1": FakeHandle(), "w2": FakeHandle()},
        )
        coord.running_task_by_agent = {"w1": "t1", "w2": "t2"}

        await harvest_outputs(coord)
        assert coord.outbox_cursors["w1"] == 1
        assert coord.outbox_cursors["w2"] == 1
        assert len(coord.budget.calls) == 2


# ── handle_completion_claim ───────────────────────────────────────────


class TestHandleCompletionClaim:
    @pytest.mark.asyncio
    async def test_skip_review_kind(self, tmp_path: Path) -> None:
        """Tasks with skip-review kinds go directly to done."""
        coord = _make_coordinator(tmp_path)
        coord.running_task_by_agent = {"w1": "task-1"}
        coord.running_task_last_progress = {"task-1": time.monotonic()}
        coord.running_task_started_at = {"task-1": time.monotonic()}

        task = MagicMock()
        task.task_kind = "research"
        task.artifacts = []
        coord._find_task.return_value = task

        with patch("attoswarm.coordinator.output_harvester.detect_file_changes"):
            with patch("attoswarm.coordinator.loop.SKIP_REVIEW_KINDS", {"research"}):
                await handle_completion_claim(coord, "w1", "task-1")

        coord._transition_task.assert_called_with("task-1", "done", "worker", "terminal_claim")
        coord._persist_task.assert_called_with(task, status="done")
        # Should not enqueue to merge queue
        assert len(coord.merge_queue.enqueued) == 0

    @pytest.mark.asyncio
    async def test_regular_task_goes_to_reviewing(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        coord.running_task_by_agent = {"w1": "task-1"}
        coord.running_task_last_progress = {"task-1": time.monotonic()}
        coord.running_task_started_at = {"task-1": time.monotonic()}

        task = MagicMock()
        task.task_kind = "implement"
        task.artifacts = ["src/main.py"]
        coord._find_task.return_value = task

        with patch("attoswarm.coordinator.output_harvester.detect_file_changes"):
            with patch("attoswarm.coordinator.loop.SKIP_REVIEW_KINDS", set()):
                await handle_completion_claim(coord, "w1", "task-1")

        coord._transition_task.assert_called_with(
            "task-1", "reviewing", "worker", "completion_claim"
        )
        assert len(coord.merge_queue.enqueued) == 1
        assert coord.merge_queue.enqueued[0][0] == "task-1"

    @pytest.mark.asyncio
    async def test_cleans_up_tracking_state(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        coord.running_task_by_agent = {"w1": "task-1"}
        coord.running_task_last_progress = {"task-1": 100.0}
        coord.running_task_started_at = {"task-1": 50.0}
        coord._find_task.return_value = None

        with patch("attoswarm.coordinator.output_harvester.detect_file_changes"):
            await handle_completion_claim(coord, "w1", "task-1")

        assert "w1" not in coord.running_task_by_agent
        assert "task-1" not in coord.running_task_last_progress
        assert "task-1" not in coord.running_task_started_at


# ── detect_file_changes ───────────────────────────────────────────────


class TestDetectFileChanges:
    def test_no_handle(self, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        coord.handles = {}
        # Should not raise
        detect_file_changes(coord, "w1", "task-1")

    @patch("attoswarm.coordinator.output_harvester.subprocess.run")
    def test_emits_event_on_changes(self, mock_run: MagicMock, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        handle = FakeHandle()
        handle.spec.cwd = "/tmp/repo"
        coord.handles = {"w1": handle}

        # Mock git diff
        diff_result = MagicMock()
        diff_result.stdout = "src/main.py\nsrc/utils.py\n"
        # Mock git ls-files
        ls_result = MagicMock()
        ls_result.stdout = "src/new.py\n"
        mock_run.side_effect = [diff_result, ls_result]

        detect_file_changes(coord, "w1", "task-1")

        coord._append_event.assert_called_once()
        call_args = coord._append_event.call_args
        assert call_args[0][0] == "task.files_changed"
        files = call_args[0][1]["files"]
        assert "src/main.py" in files
        assert "src/utils.py" in files
        assert "+ src/new.py" in files

    @patch("attoswarm.coordinator.output_harvester.subprocess.run")
    def test_no_changes_no_event(self, mock_run: MagicMock, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        handle = FakeHandle()
        handle.spec.cwd = "/tmp/repo"
        coord.handles = {"w1": handle}

        empty = MagicMock()
        empty.stdout = ""
        mock_run.return_value = empty

        detect_file_changes(coord, "w1", "task-1")
        coord._append_event.assert_not_called()

    @patch("attoswarm.coordinator.output_harvester.subprocess.run")
    def test_git_error_silenced(self, mock_run: MagicMock, tmp_path: Path) -> None:
        coord = _make_coordinator(tmp_path)
        handle = FakeHandle()
        handle.spec.cwd = "/tmp/repo"
        coord.handles = {"w1": handle}

        mock_run.side_effect = subprocess.TimeoutExpired("git", 5)
        # Should not raise
        detect_file_changes(coord, "w1", "task-1")
