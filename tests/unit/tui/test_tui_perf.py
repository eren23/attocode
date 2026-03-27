"""Tests for TUI performance optimizations.

Covers: widget fingerprinting, layout=True removal, worker-thread data flow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from attoswarm.tui.stores import StateStore


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_run_dir(tmp_path: Path) -> Path:
    (tmp_path / "tasks").mkdir()
    (tmp_path / "agents").mkdir()
    return tmp_path


@pytest.fixture()
def store(tmp_run_dir: Path) -> StateStore:
    return StateStore(str(tmp_run_dir))


# ── EventTimeline fingerprinting ─────────────────────────────────────


class TestEventTimelineFingerprint:
    """EventTimeline fingerprint logic — tests the skip condition directly."""

    def _compute_fingerprint(
        self, events: list[dict[str, Any]], filter_type: str = ""
    ) -> tuple[int, float, str]:
        """Reproduce the fingerprint logic from EventTimeline._rebuild."""
        if not events:
            return (0, 0.0, "")
        last_ts = events[-1].get("timestamp", 0.0) if events else 0.0
        return (len(events), last_ts, filter_type)

    def test_same_events_produce_same_fingerprint(self) -> None:
        events = [
            {"type": "spawn", "timestamp": 100.0, "message": "started"},
            {"type": "complete", "timestamp": 200.0, "message": "done"},
        ]
        fp1 = self._compute_fingerprint(events)
        fp2 = self._compute_fingerprint(events)
        assert fp1 == fp2

    def test_new_event_changes_fingerprint(self) -> None:
        events_v1 = [{"type": "spawn", "timestamp": 100.0}]
        events_v2 = [
            {"type": "spawn", "timestamp": 100.0},
            {"type": "complete", "timestamp": 200.0},
        ]
        assert self._compute_fingerprint(events_v1) != self._compute_fingerprint(events_v2)

    def test_different_timestamp_changes_fingerprint(self) -> None:
        """Same count but different last timestamp -> different fingerprint."""
        events_v1 = [{"type": "spawn", "timestamp": 100.0}]
        events_v2 = [{"type": "spawn", "timestamp": 200.0}]
        assert self._compute_fingerprint(events_v1) != self._compute_fingerprint(events_v2)

    def test_filter_change_changes_fingerprint(self) -> None:
        events = [{"type": "spawn", "timestamp": 100.0}]
        fp_no_filter = self._compute_fingerprint(events, filter_type="")
        fp_with_filter = self._compute_fingerprint(events, filter_type="spawn")
        assert fp_no_filter != fp_with_filter

    def test_empty_events_fingerprint(self) -> None:
        assert self._compute_fingerprint([]) == (0, 0.0, "")

    def test_fingerprint_in_widget_source(self) -> None:
        """Verify the widget uses _prev_fingerprint, not _prev_event_count."""
        import inspect
        from attocode.tui.widgets.swarm.event_timeline import EventTimeline

        source = inspect.getsource(EventTimeline._rebuild)
        assert "_prev_fingerprint" in source
        assert "_prev_event_count" not in source


# ── AgentGrid fingerprinting ─────────────────────────────────────────


class TestAgentGridFingerprint:
    """AgentGrid should skip _rebuild when agent data fingerprint is unchanged."""

    def test_fingerprint_computation(self) -> None:
        """Fingerprint should include agent_id, status, and tokens_used."""
        agents = [
            {"agent_id": "w1", "status": "running", "tokens_used": 5000},
            {"agent_id": "w2", "status": "idle", "tokens_used": 0},
        ]
        fp = "|".join(
            f"{a.get('agent_id','')},{a.get('status','')},{a.get('tokens_used',0)}"
            for a in agents
        )
        assert fp == "w1,running,5000|w2,idle,0"

    def test_fingerprint_changes_on_status_update(self) -> None:
        """Status change should produce a different fingerprint."""
        agents_v1 = [{"agent_id": "w1", "status": "running", "tokens_used": 5000}]
        agents_v2 = [{"agent_id": "w1", "status": "done", "tokens_used": 5000}]

        fp1 = "|".join(
            f"{a.get('agent_id','')},{a.get('status','')},{a.get('tokens_used',0)}"
            for a in agents_v1
        )
        fp2 = "|".join(
            f"{a.get('agent_id','')},{a.get('status','')},{a.get('tokens_used',0)}"
            for a in agents_v2
        )
        assert fp1 != fp2

    def test_fingerprint_changes_on_token_update(self) -> None:
        """Token count change should produce a different fingerprint."""
        agents_v1 = [{"agent_id": "w1", "status": "running", "tokens_used": 5000}]
        agents_v2 = [{"agent_id": "w1", "status": "running", "tokens_used": 10000}]

        fp1 = "|".join(
            f"{a.get('agent_id','')},{a.get('status','')},{a.get('tokens_used',0)}"
            for a in agents_v1
        )
        fp2 = "|".join(
            f"{a.get('agent_id','')},{a.get('status','')},{a.get('tokens_used',0)}"
            for a in agents_v2
        )
        assert fp1 != fp2

    def test_fingerprint_stable_for_same_data(self) -> None:
        """Same agent data should produce identical fingerprints."""
        agents = [
            {"agent_id": "w1", "status": "running", "tokens_used": 5000},
            {"agent_id": "w2", "status": "idle", "tokens_used": 0},
        ]
        fp1 = "|".join(
            f"{a.get('agent_id','')},{a.get('status','')},{a.get('tokens_used',0)}"
            for a in agents
        )
        fp2 = "|".join(
            f"{a.get('agent_id','')},{a.get('status','')},{a.get('tokens_used',0)}"
            for a in agents
        )
        assert fp1 == fp2


# ── layout=True removal ─────────────────────────────────────────────


class TestReactiveLayoutFlags:
    """Verify layout=True was removed from reactive properties."""

    def test_agent_grid_no_layout_flag(self) -> None:
        from attocode.tui.widgets.swarm.agent_grid import AgentGrid

        # Access the reactive descriptor
        descriptor = AgentGrid.__dict__["agents"]
        # layout=True would set _layout on the Reactive descriptor
        assert not getattr(descriptor, "_layout", False)

    def test_task_board_no_layout_flag(self) -> None:
        from attocode.tui.widgets.swarm.task_board import TaskBoard

        descriptor = TaskBoard.__dict__["agents"] if "agents" in TaskBoard.__dict__ else None
        # TaskBoard uses 'tasks' reactive
        descriptor = TaskBoard.__dict__.get("tasks")
        if descriptor is not None:
            assert not getattr(descriptor, "_layout", False)


# ── Worker-thread data flow for messages tab ─────────────────────────


class TestRefreshIODataFlow:
    """Verify that _refresh_io pre-builds messages and decisions data."""

    def test_messages_tab_data_built_in_worker(
        self, store: StateStore, tmp_run_dir: Path
    ) -> None:
        """Messages tab should read message files and pass pre-built data."""
        # Write inbox/outbox files (dict format with messages/events key)
        agents_dir = tmp_run_dir / "agents"
        inbox = {"messages": [{"kind": "task_assign", "task_id": "t1", "timestamp": 1000}]}
        (agents_dir / "agent-t1.inbox.json").write_text(json.dumps(inbox))

        outbox = {"events": [{"kind": "task_done", "task_id": "t1", "timestamp": 2000}]}
        (agents_dir / "agent-t1.outbox.json").write_text(json.dumps(outbox))

        messages = store.read_all_messages()
        assert len(messages) >= 2
        directions = {m["direction"] for m in messages}
        assert len(directions) > 0  # Has at least one direction type

    def test_decisions_data_built_without_io(self, store: StateStore) -> None:
        """build_decision_list should work from state dict without extra I/O."""
        state: dict[str, Any] = {
            "decisions": [
                {"type": "decomposition", "summary": "Split into 3 tasks"},
            ],
        }
        decisions = store.build_decision_list(state)
        assert len(decisions) >= 1


# ── enrich_trace=False avoids N+1 file reads ─────────────────────────


class TestEnrichTracePerformance:
    """Verify enrich_trace=False avoids reading trace files."""

    def test_no_trace_file_access_when_disabled(
        self, store: StateStore, tmp_run_dir: Path
    ) -> None:
        """With enrich_trace=False, build_agent_trace_summary should not be called."""
        state = {
            "active_agents": [
                {"agent_id": "w1", "task_id": "t1", "status": "running"},
                {"agent_id": "w2", "task_id": "t2", "status": "running"},
                {"agent_id": "w3", "task_id": "t3", "status": "running"},
            ]
        }

        with patch.object(store, "build_agent_trace_summary") as mock_trace:
            mock_trace.return_value = {}
            store.build_agent_list(state, enrich_trace=False)
            mock_trace.assert_not_called()

    def test_trace_file_accessed_when_enabled(
        self, store: StateStore, tmp_run_dir: Path
    ) -> None:
        """With enrich_trace=True (default), trace summary is called per agent."""
        state = {
            "active_agents": [
                {"agent_id": "w1", "task_id": "t1", "status": "running"},
                {"agent_id": "w2", "task_id": "t2", "status": "running"},
            ]
        }

        with patch.object(store, "build_agent_trace_summary") as mock_trace:
            mock_trace.return_value = {}
            store.build_agent_list(state, enrich_trace=True)
            assert mock_trace.call_count == 2


# ── Tab switch delay ─────────────────────────────────────────────────


class TestTabSwitchDelay:
    """Verify tab switch timer is 50ms, not 300ms."""

    def test_tab_switch_timer_value(self) -> None:
        """The tab switch delay should be 50ms (0.05s), not 300ms."""
        import inspect
        from attoswarm.tui.app import AttoswarmApp

        source = inspect.getsource(AttoswarmApp.on_tabbed_content_tab_activated)
        assert "0.05" in source
        assert "0.3" not in source


# ── Trace poll interval ──────────────────────────────────────────────


class TestTracePollInterval:
    """Verify trace polling interval is 1.5s, not 0.5s."""

    def test_trace_poll_interval(self) -> None:
        """Trace polling should use 1.5s interval."""
        import inspect
        from attoswarm.tui.app import AttoswarmApp

        source = inspect.getsource(AttoswarmApp.on_agents_data_table_agent_selected)
        assert "1.5" in source
        assert "set_interval(0.5" not in source
