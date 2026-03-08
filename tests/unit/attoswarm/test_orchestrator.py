"""Tests for attoswarm.coordinator.orchestrator.SwarmOrchestrator.

P1 high: orchestrator.py (760 LOC) is the main execution engine.
Covers: _handle_result, _split_by_conflicts, _restore_state,
        _persist_state, _persist_task, _persist_manifest, get_state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attoswarm.config.schema import SwarmYamlConfig
from attoswarm.coordinator.aot_graph import AoTGraph, AoTNode
from attoswarm.coordinator.orchestrator import SwarmOrchestrator
from attoswarm.coordinator.subagent_manager import TaskResult
from attoswarm.protocol.io import read_json
from attoswarm.protocol.models import TaskSpec


@pytest.fixture()
def orch(tmp_path: Path) -> SwarmOrchestrator:
    """Minimal orchestrator fixture."""
    cfg = SwarmYamlConfig()
    cfg.run.run_dir = str(tmp_path / "run")
    o = SwarmOrchestrator(cfg, "test goal")
    o._setup_directories()
    return o


def _add_task(
    orch: SwarmOrchestrator,
    task_id: str,
    *,
    deps: list[str] | None = None,
    target_files: list[str] | None = None,
    status: str = "pending",
) -> TaskSpec:
    """Add a task to the orchestrator's internal state + DAG."""
    task = TaskSpec(
        task_id=task_id,
        title=f"Task {task_id}",
        description=f"Do {task_id}",
        deps=deps or [],
        target_files=target_files or [],
    )
    orch._tasks[task_id] = task
    orch._aot_graph.add_task(AoTNode(
        task_id=task_id,
        depends_on=deps or [],
        target_files=target_files or [],
    ))
    node = orch._aot_graph.get_node(task_id)
    if node:
        node.status = status
    return task


# ── _handle_result ────────────────────────────────────────────────────


class TestHandleResult:
    def test_success_marks_complete(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(
            task_id="t1",
            success=True,
            files_modified=["src/a.py"],
            result_summary="All done",
            tokens_used=1000,
            cost_usd=0.05,
        )
        completed = orch._handle_result(result)
        assert completed == 1
        node = orch._aot_graph.get_node("t1")
        assert node is not None
        assert node.status == "done"

    def test_success_updates_task_fields(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(
            task_id="t1",
            success=True,
            files_modified=["a.py"],
            result_summary="Done",
            tokens_used=500,
            cost_usd=0.01,
        )
        orch._handle_result(result)
        task = orch._tasks["t1"]
        assert task.files_modified == ["a.py"]
        assert task.result_summary == "Done"
        assert task.tokens_used == 500
        assert task.cost_usd == 0.01

    def test_failure_retries_within_limit(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(task_id="t1", success=False, error="timeout")
        completed = orch._handle_result(result)
        assert completed == 0
        node = orch._aot_graph.get_node("t1")
        assert node is not None
        assert node.status == "pending"  # reset for retry
        assert orch._task_attempts["t1"] == 1

    def test_failure_exhausts_retries(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        # Exhaust retries (default max_task_attempts=2)
        orch._task_attempts["t1"] = 1
        result = TaskResult(task_id="t1", success=False, error="still broken")
        completed = orch._handle_result(result)
        assert completed == 0
        node = orch._aot_graph.get_node("t1")
        assert node is not None
        assert node.status == "failed"

    def test_failure_records_attempt_history(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(
            task_id="t1",
            success=False,
            error="boom",
            duration_s=5.0,
            tokens_used=200,
        )
        orch._handle_result(result)
        history = orch._task_attempt_history.get("t1", [])
        assert len(history) == 1
        assert history[0]["attempt"] == 1
        assert history[0]["error"] == "boom"

    def test_failure_cascade_skips_dependents(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        _add_task(orch, "t2", deps=["t1"])
        orch._aot_graph.compute_levels()

        # Exhaust retries for t1
        orch._task_attempts["t1"] = 1
        result = TaskResult(task_id="t1", success=False, error="fatal")
        orch._handle_result(result)

        node_t2 = orch._aot_graph.get_node("t2")
        assert node_t2 is not None
        assert node_t2.status == "skipped"

    def test_success_accumulates_budget(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(task_id="t1", success=True, tokens_used=3000, cost_usd=0.1)
        orch._handle_result(result)
        assert orch._budget.used_tokens == 3000
        assert orch._budget.used_cost_usd == pytest.approx(0.1)


# ── _split_by_conflicts ──────────────────────────────────────────────


class TestSplitByConflicts:
    def test_no_conflicts(self, orch: SwarmOrchestrator) -> None:
        parallel, serialized = orch._split_by_conflicts(["t1", "t2", "t3"], [])
        assert parallel == ["t1", "t2", "t3"]
        assert serialized == []

    def test_with_conflicts(self, orch: SwarmOrchestrator) -> None:
        conflicts = [{"task_a": "t1", "task_b": "t2"}]
        parallel, serialized = orch._split_by_conflicts(
            ["t1", "t2", "t3"], conflicts
        )
        assert parallel == ["t3"]
        assert set(serialized) == {"t1", "t2"}

    def test_all_conflicting(self, orch: SwarmOrchestrator) -> None:
        conflicts = [{"task_a": "t1", "task_b": "t2"}]
        parallel, serialized = orch._split_by_conflicts(["t1", "t2"], conflicts)
        assert parallel == []
        assert set(serialized) == {"t1", "t2"}


# ── _restore_state ────────────────────────────────────────────────────


class TestRestoreState:
    def test_done_tasks_preserved(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1")
        _add_task(orch, "t2")

        # Write persisted state with t1 done, t2 failed
        state = {
            "dag": {
                "nodes": [
                    {"task_id": "t1", "status": "done"},
                    {"task_id": "t2", "status": "failed"},
                ],
            },
        }
        from attoswarm.protocol.io import write_json_atomic
        write_json_atomic(orch._layout["state"], state)

        orch._restore_state()
        assert orch._aot_graph.get_node("t1").status == "done"
        assert orch._aot_graph.get_node("t2").status == "pending"  # reset

    def test_running_reset_to_pending(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1")
        state = {"dag": {"nodes": [{"task_id": "t1", "status": "running"}]}}
        from attoswarm.protocol.io import write_json_atomic
        write_json_atomic(orch._layout["state"], state)

        orch._restore_state()
        assert orch._aot_graph.get_node("t1").status == "pending"

    def test_empty_state_file(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1")
        from attoswarm.protocol.io import write_json_atomic
        write_json_atomic(orch._layout["state"], {})

        # Should not raise
        orch._restore_state()
        assert orch._aot_graph.get_node("t1").status == "pending"


# ── _persist_state ────────────────────────────────────────────────────


class TestPersistState:
    def test_writes_state_file(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", deps=["t0"])
        orch._phase = "executing"
        orch._persist_state()

        state = read_json(orch._layout["state"], default={})
        assert state["phase"] == "executing"
        assert state["goal"] == "test goal"
        assert len(state["dag"]["nodes"]) == 1
        assert state["state_seq"] == 1

    def test_increments_state_seq(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1")
        orch._persist_state()
        orch._persist_state()
        state = read_json(orch._layout["state"], default={})
        assert state["state_seq"] == 2

    def test_dag_edges(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1")
        _add_task(orch, "t2", deps=["t1"])
        orch._persist_state()
        state = read_json(orch._layout["state"], default={})
        assert ["t1", "t2"] in state["dag"]["edges"]

    def test_enriched_dag_nodes(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", target_files=["src/a.py"])
        orch._tasks["t1"].result_summary = "Done"
        orch._tasks["t1"].cost_usd = 0.05
        orch._persist_state()

        state = read_json(orch._layout["state"], default={})
        node = state["dag"]["nodes"][0]
        assert node["task_id"] == "t1"
        assert node["result_summary"] == "Done"
        assert node["cost_usd"] == 0.05


# ── _persist_task ─────────────────────────────────────────────────────


class TestPersistTask:
    def test_writes_task_json(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", deps=["t0"], target_files=["src/a.py"])
        orch._tasks["t1"].result_summary = "Fixed bug"
        orch._persist_task("t1")

        path = orch._layout["tasks"] / "task-t1.json"
        data = read_json(path, default={})
        assert data["title"] == "Task t1"
        assert data["deps"] == ["t0"]
        assert data["target_files"] == ["src/a.py"]
        assert data["result_summary"] == "Fixed bug"

    def test_includes_attempt_info(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1")
        orch._task_attempts["t1"] = 2
        orch._task_attempt_history["t1"] = [
            {"attempt": 1, "error": "fail1"},
            {"attempt": 2, "error": "fail2"},
        ]
        orch._persist_task("t1")

        path = orch._layout["tasks"] / "task-t1.json"
        data = read_json(path, default={})
        assert data["attempt_count"] == 2
        assert len(data["attempt_history"]) == 2

    def test_missing_task_no_error(self, orch: SwarmOrchestrator) -> None:
        orch._persist_task("nonexistent")  # should not raise


# ── _persist_manifest ─────────────────────────────────────────────────


class TestPersistManifest:
    def test_writes_manifest(self, orch: SwarmOrchestrator) -> None:
        from attoswarm.protocol.models import SwarmManifest
        _add_task(orch, "t1")
        orch._manifest = SwarmManifest(
            run_id=orch._run_id,
            goal="test goal",
            tasks=list(orch._tasks.values()),
        )
        orch._persist_manifest()

        data = read_json(orch._layout["manifest"], default={})
        assert data["goal"] == "test goal"
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["task_id"] == "t1"

    def test_no_manifest_no_error(self, orch: SwarmOrchestrator) -> None:
        orch._manifest = None
        orch._persist_manifest()  # should not raise


# ── get_state ─────────────────────────────────────────────────────────


class TestGetState:
    def test_returns_snapshot(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        orch._phase = "executing"
        orch._start_time = 1.0
        state = orch.get_state()
        assert state["phase"] == "executing"
        assert state["goal"] == "test goal"
        assert "t1" in state["tasks"]
        assert state["tasks"]["t1"]["status"] == "running"

    def test_includes_budget(self, orch: SwarmOrchestrator) -> None:
        orch._start_time = 1.0
        orch._budget.add_usage({"total": 1000}, 0.05)
        state = orch.get_state()
        assert state["budget"]["tokens_used"] == 1000

    def test_includes_dag_summary(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="done")
        orch._start_time = 1.0
        state = orch.get_state()
        assert "dag_summary" in state
        assert state["dag_summary"]["done"] == 1


# ── _decompose_goal ──────────────────────────────────────────────────


class TestDecomposeGoal:
    @pytest.mark.asyncio
    async def test_single_task_fallback(self, orch: SwarmOrchestrator) -> None:
        tasks = await orch._decompose_goal()
        assert len(tasks) == 1
        assert tasks[0].title == "test goal"[:100]

    @pytest.mark.asyncio
    async def test_custom_decompose_fn(self, tmp_path: Path) -> None:
        async def mock_decompose(goal: str, **kwargs: Any) -> list[TaskSpec]:
            return [
                TaskSpec(task_id="t1", title="First", description="Do first"),
                TaskSpec(task_id="t2", title="Second", description="Do second"),
            ]

        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(tmp_path / "run")
        o = SwarmOrchestrator(cfg, "big goal", decompose_fn=mock_decompose)
        o._setup_directories()

        tasks = await o._decompose_goal()
        assert len(tasks) == 2
        assert tasks[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_decompose_fn_failure_falls_back(self, tmp_path: Path) -> None:
        async def failing_decompose(goal: str, **kwargs: Any) -> list[TaskSpec]:
            raise RuntimeError("LLM error")

        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(tmp_path / "run")
        o = SwarmOrchestrator(cfg, "goal", decompose_fn=failing_decompose)
        o._setup_directories()

        tasks = await o._decompose_goal()
        assert len(tasks) == 1  # single-task fallback

    @pytest.mark.asyncio
    async def test_tasks_file_takes_priority(self, orch: SwarmOrchestrator) -> None:
        tasks_file = orch._layout["root"] / "tasks.yaml"
        tasks_file.write_text(
            "tasks:\n"
            "  - id: t1\n"
            "    title: From file\n"
            "    description: Loaded from YAML\n",
            encoding="utf-8",
        )

        with patch(
            "attoswarm.coordinator.task_file_parser.load_tasks_file",
            return_value=[TaskSpec(task_id="t1", title="From file", description="Loaded")],
        ):
            tasks = await orch._decompose_goal()
            assert len(tasks) == 1
            assert tasks[0].title == "From file"
