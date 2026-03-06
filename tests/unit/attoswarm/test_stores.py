"""Tests for attoswarm.tui.stores.StateStore transforms."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from attoswarm.tui.stores import StateStore


@pytest.fixture()
def tmp_run_dir(tmp_path: Path) -> Path:
    """Create a minimal run directory structure."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "agents").mkdir()
    return tmp_path


@pytest.fixture()
def store(tmp_run_dir: Path) -> StateStore:
    return StateStore(str(tmp_run_dir))


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
