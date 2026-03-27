"""Tests for attoswarm.tui.stores.StateStore transforms."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from attoswarm.tui.stores import StateStore, _to_epoch


@pytest.fixture()
def tmp_run_dir(tmp_path: Path) -> Path:
    """Create a minimal run directory structure."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "agents").mkdir()
    return tmp_path


@pytest.fixture()
def store(tmp_run_dir: Path) -> StateStore:
    return StateStore(str(tmp_run_dir))


# ── _to_epoch ─────────────────────────────────────────────────────────


class TestToEpoch:
    def test_int(self) -> None:
        assert _to_epoch(1000) == 1000.0

    def test_float(self) -> None:
        assert _to_epoch(1000.5) == 1000.5

    def test_iso_string(self) -> None:
        result = _to_epoch("2026-01-01T00:00:00Z")
        assert result > 0

    def test_empty_string(self) -> None:
        assert _to_epoch("") == 0.0

    def test_none(self) -> None:
        assert _to_epoch(None) == 0.0

    def test_invalid_string(self) -> None:
        assert _to_epoch("not a date") == 0.0


# ── read_state ────────────────────────────────────────────────────────


class TestReadState:
    def test_no_file(self, store: StateStore) -> None:
        assert store.read_state() == {}

    def test_reads_valid_state(self, store: StateStore, tmp_run_dir: Path) -> None:
        state = {"phase": "executing", "state_seq": 5}
        (tmp_run_dir / "swarm.state.json").write_text(json.dumps(state))
        assert store.read_state() == state

    def test_caches_by_mtime(self, store: StateStore, tmp_run_dir: Path) -> None:
        state_path = tmp_run_dir / "swarm.state.json"
        state_path.write_text(json.dumps({"v": 1}))
        first = store.read_state()

        # Overwrite WITHOUT changing mtime -> cache hit
        state_path.write_text(json.dumps({"v": 2}))
        mtime = os.path.getmtime(str(state_path))
        os.utime(str(state_path), (mtime - 1, mtime - 1))
        # Force the same mtime as the cached one
        store._state_cache = (mtime - 1, first.get("state_seq", 0), first)
        second = store.read_state()
        assert second == {"v": 1}  # cached

    def test_invalidates_on_mtime_change(self, store: StateStore, tmp_run_dir: Path) -> None:
        state_path = tmp_run_dir / "swarm.state.json"
        state_path.write_text(json.dumps({"v": 1}))
        store.read_state()

        # Force mtime change
        time.sleep(0.05)
        state_path.write_text(json.dumps({"v": 2}))
        assert store.read_state() == {"v": 2}


# ── has_new_events ────────────────────────────────────────────────────


class TestHasNewEvents:
    def test_no_file(self, store: StateStore) -> None:
        assert store.has_new_events() is False

    def test_empty_file(self, store: StateStore, tmp_run_dir: Path) -> None:
        (tmp_run_dir / "swarm.events.jsonl").write_text("")
        # First call: size is 0 and _events_last_size is 0
        assert store.has_new_events() is False

    def test_new_data(self, store: StateStore, tmp_run_dir: Path) -> None:
        (tmp_run_dir / "swarm.events.jsonl").write_text('{"a":1}\n')
        assert store.has_new_events() is True

    def test_no_change_after_read(self, store: StateStore, tmp_run_dir: Path) -> None:
        path = tmp_run_dir / "swarm.events.jsonl"
        path.write_text('{"a":1}\n')
        store.read_events()
        assert store.has_new_events() is False


# ── read_events (incremental JSONL) ──────────────────────────────────


class TestReadEvents:
    def test_no_file(self, store: StateStore) -> None:
        assert store.read_events() == []

    def test_reads_all_lines(self, store: StateStore, tmp_run_dir: Path) -> None:
        lines = [json.dumps({"seq": i}) for i in range(5)]
        (tmp_run_dir / "swarm.events.jsonl").write_text("\n".join(lines) + "\n")
        result = store.read_events(limit=100)
        assert len(result) == 5
        assert result[0]["seq"] == 0

    def test_limit_returns_tail(self, store: StateStore, tmp_run_dir: Path) -> None:
        lines = [json.dumps({"seq": i}) for i in range(10)]
        (tmp_run_dir / "swarm.events.jsonl").write_text("\n".join(lines) + "\n")
        result = store.read_events(limit=3)
        assert len(result) == 3
        assert result[0]["seq"] == 7  # tail

    def test_incremental_read(self, store: StateStore, tmp_run_dir: Path) -> None:
        path = tmp_run_dir / "swarm.events.jsonl"
        path.write_text(json.dumps({"seq": 0}) + "\n")
        first = store.read_events(limit=100)
        assert len(first) == 1

        # Append more
        with path.open("a") as f:
            f.write(json.dumps({"seq": 1}) + "\n")
            f.write(json.dumps({"seq": 2}) + "\n")
        second = store.read_events(limit=100)
        assert len(second) == 3

    def test_truncated_file_resets(self, store: StateStore, tmp_run_dir: Path) -> None:
        path = tmp_run_dir / "swarm.events.jsonl"
        # Write large initial data
        lines = [json.dumps({"seq": i}) for i in range(10)]
        path.write_text("\n".join(lines) + "\n")
        store.read_events(limit=100)

        # Truncate to smaller content
        path.write_text(json.dumps({"seq": 99}) + "\n")
        result = store.read_events(limit=100)
        assert len(result) == 1
        assert result[0]["seq"] == 99

    def test_skips_invalid_json_lines(self, store: StateStore, tmp_run_dir: Path) -> None:
        content = '{"ok":1}\nnot json\n{"ok":2}\n'
        (tmp_run_dir / "swarm.events.jsonl").write_text(content)
        result = store.read_events(limit=100)
        assert len(result) == 2

    def test_caps_in_memory_cache(self, store: StateStore, tmp_run_dir: Path) -> None:
        store._MAX_CACHED_EVENTS = 10
        lines = [json.dumps({"seq": i}) for i in range(20)]
        (tmp_run_dir / "swarm.events.jsonl").write_text("\n".join(lines) + "\n")
        store.read_events(limit=100)
        assert len(store._events_cache) == 10  # capped


# ── read_agent_box ────────────────────────────────────────────────────


class TestReadAgentBox:
    def test_reads_inbox(self, store: StateStore, tmp_run_dir: Path) -> None:
        inbox = {"messages": [{"kind": "task_assign"}]}
        (tmp_run_dir / "agents" / "agent-w1.inbox.json").write_text(json.dumps(inbox))
        result = store.read_agent_box("w1", "inbox")
        assert result["messages"][0]["kind"] == "task_assign"

    def test_missing_returns_default(self, store: StateStore) -> None:
        assert store.read_agent_box("nope", "outbox") == {}


# ── build_agent_activity ──────────────────────────────────────────────


class TestBuildAgentActivity:
    def test_known_event_types(self, store: StateStore) -> None:
        events = [
            {"type": "spawn", "agent_id": "w1"},
            {"type": "task.completed", "agent_id": "w2"},
        ]
        result = store.build_agent_activity(events)
        assert result["w1"] == "Starting..."
        assert result["w2"] == "Completed"

    def test_files_changed(self, store: StateStore) -> None:
        events = [
            {
                "type": "task.files_changed",
                "payload": {"agent_id": "w1", "files": ["src/a.py", "src/b.py", "src/c.py"]},
            },
        ]
        result = store.build_agent_activity(events)
        assert "Editing a.py" in result["w1"]
        assert "+2" in result["w1"]

    def test_fallback_to_message(self, store: StateStore) -> None:
        events = [
            {"type": "unknown.type", "agent_id": "w1", "message": "custom msg"},
        ]
        result = store.build_agent_activity(events)
        assert result["w1"] == "custom msg"

    def test_nested_agent_id(self, store: StateStore) -> None:
        events = [
            {"type": "spawn", "payload": {"agent_id": "w1"}},
        ]
        result = store.build_agent_activity(events)
        assert result["w1"] == "Starting..."

    def test_empty_events(self, store: StateStore) -> None:
        assert store.build_agent_activity([]) == {}


# ── build_task_detail ─────────────────────────────────────────────────


class TestBuildTaskDetail:
    def test_from_task_file(self, store: StateStore, tmp_run_dir: Path) -> None:
        task = {
            "title": "Fix bug",
            "status": "done",
            "task_kind": "bugfix",
            "description": "Fix null pointer",
            "depends_on": ["t0"],
            "target_files": ["src/main.py"],
            "result_summary": "Fixed",
            "tokens_used": 5000,
        }
        (tmp_run_dir / "tasks" / "task-t1.json").write_text(json.dumps(task))
        result = store.build_task_detail("t1")
        assert result["title"] == "Fix bug"
        assert result["status"] == "done"
        assert result["deps"] == ["t0"]
        assert result["tokens_used"] == 5000

    def test_fallback_to_dag(self, store: StateStore, tmp_run_dir: Path) -> None:
        """When per-task file missing, reconstruct from state DAG."""
        state = {
            "dag": {
                "nodes": [{"task_id": "t1", "title": "Research", "status": "pending"}],
                "edges": [["t0", "t1"]],
            },
        }
        (tmp_run_dir / "swarm.state.json").write_text(json.dumps(state))
        result = store.build_task_detail("t1")
        assert result["title"] == "Research"
        assert result["deps"] == ["t0"]

    def test_missing_task_returns_empty(self, store: StateStore) -> None:
        assert store.build_task_detail("nonexistent") == {}

    def test_pending_gets_blocked_reason(self, store: StateStore, tmp_run_dir: Path) -> None:
        task = {"title": "Blocked", "status": "pending", "depends_on": ["dep1"]}
        (tmp_run_dir / "tasks" / "task-blocked.json").write_text(json.dumps(task))
        state = {
            "dag": {
                "nodes": [
                    {"task_id": "dep1", "status": "running"},
                    {"task_id": "blocked", "status": "pending"},
                ],
                "edges": [["dep1", "blocked"]],
            },
        }
        (tmp_run_dir / "swarm.state.json").write_text(json.dumps(state))
        result = store.build_task_detail("blocked", state)
        assert "running" in result.get("blocked_reason", "").lower()


# ── _diagnose_pending ─────────────────────────────────────────────────


class TestDiagnosePending:
    def test_no_deps(self, store: StateStore) -> None:
        state = {
            "dag": {"nodes": [{"task_id": "t1", "status": "pending"}], "edges": []},
        }
        result = store._diagnose_pending("t1", state)
        assert "should be ready" in result.lower()

    def test_pending_deps(self, store: StateStore) -> None:
        state = {
            "dag": {
                "nodes": [
                    {"task_id": "t0", "status": "pending"},
                    {"task_id": "t1", "status": "pending"},
                ],
                "edges": [["t0", "t1"]],
            },
        }
        result = store._diagnose_pending("t1", state)
        assert "t0" in result

    def test_failed_deps(self, store: StateStore) -> None:
        state = {
            "dag": {
                "nodes": [
                    {"task_id": "t0", "status": "failed"},
                    {"task_id": "t1", "status": "pending"},
                ],
                "edges": [["t0", "t1"]],
            },
        }
        result = store._diagnose_pending("t1", state)
        assert "failed" in result.lower()

    def test_swarm_ended_with_pending(self, store: StateStore) -> None:
        state = {
            "phase": "completed",
            "dag": {
                "nodes": [
                    {"task_id": "t0", "status": "pending"},
                    {"task_id": "t1", "status": "pending"},
                ],
                "edges": [["t0", "t1"]],
            },
        }
        result = store._diagnose_pending("t1", state)
        assert "ended" in result.lower()


# ── build_per_task_costs ──────────────────────────────────────────────


class TestBuildPerTaskCosts:
    def test_sorted_by_cost_desc(self, store: StateStore) -> None:
        state = {
            "dag": {
                "nodes": [
                    {"task_id": "t1", "cost_usd": 0.5, "tokens_used": 1000},
                    {"task_id": "t2", "cost_usd": 1.5, "tokens_used": 3000},
                    {"task_id": "t3", "cost_usd": 0.1, "tokens_used": 200},
                ],
            },
        }
        result = store.build_per_task_costs(state)
        assert len(result) == 3
        assert result[0]["task_id"] == "t2"
        assert result[-1]["task_id"] == "t3"

    def test_zero_cost_excluded(self, store: StateStore) -> None:
        state = {
            "dag": {"nodes": [{"task_id": "t1", "cost_usd": 0}]},
        }
        assert store.build_per_task_costs(state) == []

    def test_empty_dag(self, store: StateStore) -> None:
        assert store.build_per_task_costs({}) == []


# ── read_all_messages ─────────────────────────────────────────────────


class TestReadAllMessages:
    def test_reads_inbox_outbox(self, store: StateStore, tmp_run_dir: Path) -> None:
        inbox = {
            "messages": [
                {"kind": "task_assign", "task_id": "t1", "timestamp": 1000, "payload": {"msg": "go"}},
            ],
        }
        outbox = {
            "events": [
                {"type": "task_done", "task_id": "t1", "timestamp": 1001, "payload": {"result": "ok"}},
            ],
        }
        (tmp_run_dir / "agents" / "agent-w1.inbox.json").write_text(json.dumps(inbox))
        (tmp_run_dir / "agents" / "agent-w1.outbox.json").write_text(json.dumps(outbox))

        result = store.read_all_messages()
        assert len(result) == 2
        assert result[0]["direction"] == "coordinator\u2192agent"
        assert result[1]["direction"] == "agent\u2192coordinator"

    def test_sorted_by_timestamp(self, store: StateStore, tmp_run_dir: Path) -> None:
        inbox = {
            "messages": [
                {"kind": "task_assign", "task_id": "t1", "timestamp": 2000, "payload": {}},
            ],
        }
        outbox = {
            "events": [
                {"type": "task_done", "task_id": "t1", "timestamp": 1000, "payload": {}},
            ],
        }
        (tmp_run_dir / "agents" / "agent-w1.inbox.json").write_text(json.dumps(inbox))
        (tmp_run_dir / "agents" / "agent-w1.outbox.json").write_text(json.dumps(outbox))

        result = store.read_all_messages()
        assert result[0]["timestamp"] == 1000  # earlier first

    def test_no_agents_dir(self, tmp_path: Path) -> None:
        s = StateStore(str(tmp_path))
        assert s.read_all_messages() == []

    def test_caches_result(self, store: StateStore, tmp_run_dir: Path) -> None:
        inbox = {"messages": [{"kind": "test", "timestamp": 1000, "payload": {}}]}
        (tmp_run_dir / "agents" / "agent-w1.inbox.json").write_text(json.dumps(inbox))

        first = store.read_all_messages()
        # Modify file — cache should serve stale
        (tmp_run_dir / "agents" / "agent-w1.inbox.json").write_text(
            json.dumps({"messages": [{"kind": "updated", "timestamp": 2000, "payload": {}}]})
        )
        second = store.read_all_messages()
        assert first == second  # cached within TTL

    def test_fallback_to_events(self, store: StateStore, tmp_run_dir: Path) -> None:
        """When no inbox/outbox files exist, synthesize from events."""
        events = [
            json.dumps({"type": "agent.spawned", "agent_id": "w1", "task_id": "t1", "timestamp": 1000}),
            json.dumps({"type": "task.completed", "agent_id": "w1", "task_id": "t1", "timestamp": 2000}),
        ]
        (tmp_run_dir / "swarm.events.jsonl").write_text("\n".join(events) + "\n")

        result = store.read_all_messages()
        assert len(result) >= 2


# ── _parse_edges ──────────────────────────────────────────────────────


class TestParseEdges:
    def test_list_format(self) -> None:
        """Edges produced by state_writer: [[a, b], ...]."""
        edges = [["task-1", "task-2"], ["task-2", "task-3"]]
        result = StateStore._parse_edges(edges)
        assert result == {"task-2": ["task-1"], "task-3": ["task-2"]}

    def test_tuple_format(self) -> None:
        edges = [("a", "b"), ("b", "c")]
        result = StateStore._parse_edges(edges)
        assert result == {"b": ["a"], "c": ["b"]}

    def test_dict_format_source_target(self) -> None:
        edges = [{"source": "a", "target": "b"}]
        result = StateStore._parse_edges(edges)
        assert result == {"b": ["a"]}

    def test_dict_format_from_to(self) -> None:
        edges = [{"from": "a", "to": "b"}]
        result = StateStore._parse_edges(edges)
        assert result == {"b": ["a"]}

    def test_mixed_formats(self) -> None:
        edges = [["a", "b"], {"source": "b", "target": "c"}]
        result = StateStore._parse_edges(edges)
        assert result == {"b": ["a"], "c": ["b"]}

    def test_empty(self) -> None:
        assert StateStore._parse_edges([]) == {}

    def test_invalid_entries_skipped(self) -> None:
        edges: list[Any] = [42, "bad", None, ["a", "b"]]
        result = StateStore._parse_edges(edges)
        assert result == {"b": ["a"]}

    def test_multiple_deps(self) -> None:
        edges = [["a", "c"], ["b", "c"]]
        result = StateStore._parse_edges(edges)
        assert result == {"c": ["a", "b"]}


# ── _compute_level ────────────────────────────────────────────────────


class TestComputeLevel:
    def test_no_deps(self) -> None:
        levels: dict[str, int] = {}
        result = StateStore._compute_level("a", {}, levels)
        assert result == 0
        assert levels == {"a": 0}

    def test_linear_chain(self) -> None:
        deps = {"b": ["a"], "c": ["b"]}
        levels: dict[str, int] = {}
        StateStore._compute_level("c", deps, levels)
        assert levels == {"a": 0, "b": 1, "c": 2}

    def test_diamond(self) -> None:
        # d depends on b and c; both depend on a
        deps = {"b": ["a"], "c": ["a"], "d": ["b", "c"]}
        levels: dict[str, int] = {}
        StateStore._compute_level("d", deps, levels)
        assert levels["a"] == 0
        assert levels["b"] == 1
        assert levels["c"] == 1
        assert levels["d"] == 2

    def test_cycle_guard(self) -> None:
        """Cyclic deps should not cause RecursionError."""
        deps = {"a": ["b"], "b": ["a"]}
        levels: dict[str, int] = {}
        # Should not raise
        result = StateStore._compute_level("a", deps, levels)
        assert isinstance(result, int)

    def test_cached_levels(self) -> None:
        """Already-computed levels should be returned immediately."""
        levels = {"x": 5}
        result = StateStore._compute_level("x", {}, levels)
        assert result == 5


# ── build_agent_list ──────────────────────────────────────────────────


class TestBuildAgentList:
    def test_basic(self, store: StateStore) -> None:
        state = {
            "active_agents": [
                {
                    "agent_id": "w1",
                    "status": "running",
                    "task_id": "t1",
                    "backend": "sonnet",
                    "tokens_used": 5000,
                    "started_at_epoch": time.time() - 90,
                },
            ]
        }
        result = store.build_agent_list(state)
        assert len(result) == 1
        assert result[0]["agent_id"] == "w1"
        assert result[0]["status"] == "running"
        assert result[0]["model"] == "sonnet"
        assert result[0]["tokens_used"] == 5000
        assert "m" in result[0]["elapsed"]

    def test_empty_agents(self, store: StateStore) -> None:
        assert store.build_agent_list({}) == []

    def test_missing_epoch(self, store: StateStore) -> None:
        state = {"active_agents": [{"agent_id": "w1"}]}
        result = store.build_agent_list(state)
        assert result[0]["elapsed"] == ""

    def test_enrich_trace_false_skips_file_reads(
        self, store: StateStore, tmp_run_dir: Path
    ) -> None:
        """enrich_trace=False should skip per-agent trace file reads."""
        # Write a trace file that would be read if enrich_trace=True
        agents_dir = tmp_run_dir / "agents"
        trace_data = json.dumps({"type": "tool_call", "tool": "read_file"}) + "\n"
        (agents_dir / "agent-t1.trace.jsonl").write_text(trace_data)

        state = {
            "active_agents": [
                {"agent_id": "w1", "task_id": "t1", "status": "running"},
            ]
        }

        # With enrich_trace=True, trace data is populated
        enriched = store.build_agent_list(state, enrich_trace=True)
        assert enriched[0]["agent_id"] == "w1"

        # With enrich_trace=False, trace fields get defaults (no file I/O)
        lean = store.build_agent_list(state, enrich_trace=False)
        assert lean[0]["agent_id"] == "w1"
        assert lean[0]["tool_calls"] == []
        assert lean[0]["error_count"] == 0
        assert lean[0]["files_written"] == []
        assert lean[0]["total_cost"] == 0.0

    def test_enrich_trace_true_reads_trace_files(
        self, store: StateStore, tmp_run_dir: Path
    ) -> None:
        """enrich_trace=True (default) reads trace JSONL for each agent."""
        agents_dir = tmp_run_dir / "agents"
        lines = [
            json.dumps({"type": "tool_use", "tool": "write_file", "args": {"path": "a.py"}}),
            json.dumps({"type": "error", "message": "oops"}),
        ]
        (agents_dir / "agent-t1.trace.jsonl").write_text("\n".join(lines) + "\n")

        state = {
            "active_agents": [
                {"agent_id": "w1", "task_id": "t1", "status": "running"},
            ]
        }
        result = store.build_agent_list(state, enrich_trace=True)
        # Trace data should be populated (exact values depend on trace parser)
        assert result[0]["agent_id"] == "w1"
        # At minimum the trace was attempted (non-default error_count or tool_calls)
        trace_accessed = (
            result[0]["error_count"] > 0
            or len(result[0]["tool_calls"]) > 0
            or len(result[0]["files_written"]) > 0
        )
        assert trace_accessed


# ── build_task_list ───────────────────────────────────────────────────


class TestBuildTaskList:
    def test_with_list_edges(self, store: StateStore, tmp_run_dir: Path) -> None:
        # Write a task file
        task_data = {"title": "Impl auth", "task_kind": "code", "role_hint": "backend"}
        (tmp_run_dir / "tasks" / "task-t1.json").write_text(json.dumps(task_data))

        state = {
            "dag": {
                "nodes": [
                    {"task_id": "t1", "status": "running", "title": "Impl auth"},
                    {"task_id": "t2", "status": "pending", "title": "Write tests"},
                ],
                "edges": [["t1", "t2"]],
            }
        }
        result = store.build_task_list(state)
        assert len(result) == 2
        # t2 should depend on t1
        t2 = next(r for r in result if r["task_id"] == "t2")
        assert t2["depends_on"] == ["t1"]
        # t1 has no deps
        t1 = next(r for r in result if r["task_id"] == "t1")
        assert t1["depends_on"] == []

    def test_empty_dag(self, store: StateStore) -> None:
        assert store.build_task_list({}) == []


# ── build_dag_nodes ───────────────────────────────────────────────────


class TestBuildDagNodes:
    def test_levels_computed_from_list_edges(self, store: StateStore) -> None:
        state = {
            "dag": {
                "nodes": [
                    {"task_id": "a", "status": "done"},
                    {"task_id": "b", "status": "running"},
                    {"task_id": "c", "status": "pending"},
                ],
                "edges": [["a", "b"], ["b", "c"]],
            }
        }
        result = store.build_dag_nodes(state)
        by_id = {r["task_id"]: r for r in result}
        assert by_id["a"]["level"] == 0
        assert by_id["b"]["level"] == 1
        assert by_id["c"]["level"] == 2

    def test_empty(self, store: StateStore) -> None:
        assert store.build_dag_nodes({}) == []


# ── build_event_list ──────────────────────────────────────────────────


class TestBuildEventList:
    def test_type_mapping(self, store: StateStore) -> None:
        events = [
            {"type": "agent.spawned", "payload": {"agent_id": "w1", "message": "hi"}, "timestamp": 1000},
            {"type": "task.completed", "payload": {"task_id": "t1"}, "timestamp": "2026-01-01T00:00:00Z"},
        ]
        result = store.build_event_list(events)
        assert result[0]["type"] == "spawn"
        assert result[1]["type"] == "complete"

    def test_iso_timestamp_conversion(self, store: StateStore) -> None:
        events = [{"type": "info", "payload": {}, "timestamp": "2026-01-01T00:00:00Z"}]
        result = store.build_event_list(events)
        assert result[0]["timestamp"] > 0

    def test_empty(self, store: StateStore) -> None:
        assert store.build_event_list([]) == []


# ── read_file_activity ────────────────────────────────────────────────


class TestReadFileActivity:
    def test_reads_from_events_jsonl(self, store: StateStore, tmp_run_dir: Path) -> None:
        events = [
            {
                "type": "task.files_changed",
                "payload": {"agent_id": "w1", "task_id": "t1", "files": ["src/a.py", "src/b.py"]},
                "timestamp": "2026-01-01T00:00:00Z",
            },
            {
                "type": "task.claimed",
                "payload": {"agent_id": "w1"},
                "timestamp": "2026-01-01T00:00:01Z",
            },
            {
                "type": "task.files_changed",
                "payload": {"agent_id": "w2", "task_id": "t2", "files": ["src/a.py"]},
                "timestamp": "2026-01-01T00:00:02Z",
            },
        ]
        lines = [json.dumps(e) for e in events]
        (tmp_run_dir / "swarm.events.jsonl").write_text("\n".join(lines))

        result = store.read_file_activity()
        assert "src/a.py" in result
        assert len(result["src/a.py"]) == 2  # touched by w1 and w2
        assert "src/b.py" in result
        assert len(result["src/b.py"]) == 1

    def test_no_events_file(self, store: StateStore) -> None:
        assert store.read_file_activity() == {}


# ── build_agent_detail ────────────────────────────────────────────────


class TestBuildAgentDetail:
    def test_extracts_files_from_events(self, store: StateStore, tmp_run_dir: Path) -> None:
        events = [
            {
                "type": "task.files_changed",
                "payload": {"agent_id": "w1", "task_id": "t1", "files": ["src/main.py"]},
                "timestamp": "2026-01-01T00:00:00Z",
            },
        ]
        (tmp_run_dir / "swarm.events.jsonl").write_text(json.dumps(events[0]))

        state = {
            "active_agents": [
                {"agent_id": "w1", "status": "running", "task_id": "t1", "backend": "opus", "tokens_used": 100}
            ]
        }
        result = store.build_agent_detail("w1", state)
        assert result["kind"] == "agent"
        assert result["files_modified"] == ["src/main.py"]

    def test_unknown_agent(self, store: StateStore) -> None:
        assert store.build_agent_detail("nope", {"active_agents": []}) == {}


# ── Task cache ────────────────────────────────────────────────────────


class TestTaskCache:
    def test_cache_hit(self, store: StateStore, tmp_run_dir: Path) -> None:
        task_data = {"title": "cached"}
        (tmp_run_dir / "tasks" / "task-c1.json").write_text(json.dumps(task_data))

        first = store._read_task_cached("c1")
        assert first["title"] == "cached"

        # Overwrite file — cache should still return old value
        (tmp_run_dir / "tasks" / "task-c1.json").write_text(json.dumps({"title": "updated"}))
        second = store._read_task_cached("c1")
        assert second["title"] == "cached"  # still cached

    def test_cache_expiry(self, store: StateStore, tmp_run_dir: Path) -> None:
        task_data = {"title": "v1"}
        (tmp_run_dir / "tasks" / "task-e1.json").write_text(json.dumps(task_data))

        store._cache_ttl = 0  # expire immediately
        first = store._read_task_cached("e1")
        assert first["title"] == "v1"

        (tmp_run_dir / "tasks" / "task-e1.json").write_text(json.dumps({"title": "v2"}))
        second = store._read_task_cached("e1")
        assert second["title"] == "v2"  # cache expired, re-read
