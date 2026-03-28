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
from attoswarm.coordinator.orchestrator import PlanningFailure, SwarmOrchestrator
from attoswarm.coordinator.subagent_manager import TaskResult
from attoswarm.protocol.io import read_json
from attoswarm.protocol.models import LauncherInfo, LineageSpec, TaskSpec


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
    @pytest.mark.asyncio
    async def test_success_marks_complete(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(
            task_id="t1",
            success=True,
            files_modified=["src/a.py"],
            result_summary="All done",
            tokens_used=1000,
            cost_usd=0.05,
        )
        completed = await orch._handle_result(result)
        assert completed == 1
        node = orch._aot_graph.get_node("t1")
        assert node is not None
        assert node.status == "done"

    @pytest.mark.asyncio
    async def test_success_updates_task_fields(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(
            task_id="t1",
            success=True,
            files_modified=["a.py"],
            result_summary="Done",
            tokens_used=500,
            cost_usd=0.01,
        )
        await orch._handle_result(result)
        task = orch._tasks["t1"]
        assert task.files_modified == ["a.py"]
        assert task.result_summary == "Done"
        assert task.tokens_used == 500
        assert task.cost_usd == 0.01

    @pytest.mark.asyncio
    async def test_failure_retries_within_limit(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(task_id="t1", success=False, error="timeout")
        completed = await orch._handle_result(result)
        assert completed == 0
        node = orch._aot_graph.get_node("t1")
        assert node is not None
        assert node.status == "pending"  # reset for retry
        assert orch._task_attempts["t1"] == 1

    @pytest.mark.asyncio
    async def test_failure_exhausts_retries(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        # Exhaust retries (default max_task_attempts=2)
        orch._task_attempts["t1"] = 1
        result = TaskResult(task_id="t1", success=False, error="still broken")
        completed = await orch._handle_result(result)
        assert completed == 0
        node = orch._aot_graph.get_node("t1")
        assert node is not None
        assert node.status == "failed"

    @pytest.mark.asyncio
    async def test_failure_records_attempt_history(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(
            task_id="t1",
            success=False,
            error="boom",
            duration_s=5.0,
            tokens_used=200,
        )
        await orch._handle_result(result)
        history = orch._task_attempt_history.get("t1", [])
        assert len(history) == 1
        assert history[0]["attempt"] == 1
        assert history[0]["error"] == "boom"

    @pytest.mark.asyncio
    async def test_failure_cascade_skips_dependents(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        _add_task(orch, "t2", deps=["t1"])
        orch._aot_graph.compute_levels()

        # Exhaust retries for t1
        orch._task_attempts["t1"] = 1
        result = TaskResult(task_id="t1", success=False, error="fatal")
        await orch._handle_result(result)

        node_t2 = orch._aot_graph.get_node("t2")
        assert node_t2 is not None
        assert node_t2.status == "skipped"

    @pytest.mark.asyncio
    async def test_success_accumulates_budget(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "t1", status="running")
        result = TaskResult(task_id="t1", success=True, tokens_used=3000, cost_usd=0.1)
        await orch._handle_result(result)
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

    def test_includes_lineage_and_launcher(self, orch: SwarmOrchestrator) -> None:
        orch._lineage = LineageSpec(parent_run_id="parent-1", continuation_mode="child")
        orch._launcher = LauncherInfo(started_via="attocode", command_family="attocode swarm")
        orch._persist_state()

        state = read_json(orch._layout["state"], default={})
        assert state["lineage"]["parent_run_id"] == "parent-1"
        assert state["launcher"]["started_via"] == "attocode"

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

    def test_includes_working_dir(self, orch: SwarmOrchestrator) -> None:
        orch._persist_state()
        state = read_json(orch._layout["state"], default={})
        assert state["working_dir"] == orch._root_dir


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

    def test_includes_lineage_and_launcher(self, orch: SwarmOrchestrator) -> None:
        from attoswarm.protocol.models import SwarmManifest

        orch._lineage = LineageSpec(parent_run_id="parent-1", continuation_mode="child")
        orch._launcher = LauncherInfo(started_via="attocode", command_family="attocode swarm")
        _add_task(orch, "t1")
        orch._manifest = SwarmManifest(
            run_id=orch._run_id,
            goal="test goal",
            tasks=list(orch._tasks.values()),
            lineage=orch._lineage,
            launcher=orch._launcher,
        )
        orch._persist_manifest()

        data = read_json(orch._layout["manifest"], default={})
        assert data["lineage"]["parent_run_id"] == "parent-1"
        assert data["launcher"]["started_via"] == "attocode"

    def test_persists_resume_fields(self, orch: SwarmOrchestrator) -> None:
        from attoswarm.protocol.models import SwarmManifest

        task = _add_task(orch, "t1", target_files=["src/a.py"], status="done")
        task.read_files = ["src/shared.py"]
        task.symbol_scope = ["build_graph"]
        task.files_modified = ["src/a.py"]
        task.timeout_seconds = 123
        task.result_summary = "Done"
        orch._manifest = SwarmManifest(
            run_id=orch._run_id,
            goal="test goal",
            tasks=list(orch._tasks.values()),
        )
        orch._persist_manifest()

        data = read_json(orch._layout["manifest"], default={})
        row = data["tasks"][0]
        assert row["status"] == "done"
        assert row["read_files"] == ["src/shared.py"]
        assert row["symbol_scope"] == ["build_graph"]
        assert row["timeout_seconds"] == 123


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


class TestResumeIdentity:
    def test_resume_uses_existing_run_id(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "swarm.manifest.json").write_text(
            json.dumps({"run_id": "existing-123", "goal": "resume me"}),
            encoding="utf-8",
        )

        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(run_dir)
        orch = SwarmOrchestrator(cfg, "resume me", resume=True)

        assert orch.run_id == "existing-123"


class TestResumeRestore:
    def test_load_existing_manifest_restores_task_details(self, tmp_path: Path) -> None:
        from attoswarm.protocol.io import write_json_atomic

        run_dir = tmp_path / "run"
        tasks_dir = run_dir / "tasks"
        tasks_dir.mkdir(parents=True)
        write_json_atomic(
            run_dir / "swarm.manifest.json",
            {
                "run_id": "resume-123",
                "goal": "resume goal",
                "tasks": [
                    {
                        "task_id": "t1",
                        "title": "One",
                        "description": "desc",
                        "deps": [],
                        "target_files": ["src/a.py"],
                        "read_files": ["src/shared.py"],
                        "symbol_scope": ["parse"],
                        "timeout_seconds": 90,
                        "status": "done",
                    }
                ],
            },
        )
        write_json_atomic(
            run_dir / "tasks" / "task-t1.json",
            {
                "task_id": "t1",
                "attempt_count": 2,
                "attempt_history": [{"attempt": 1, "error": "boom"}],
            },
        )
        write_json_atomic(
            run_dir / "swarm.state.json",
            {
                "budget": {"tokens_used": 12, "cost_used_usd": 0.5},
                "state_seq": 7,
                "decisions": [{"kind": "resume"}],
                "errors": [{"message": "old"}],
                "task_transition_log": [{"task_id": "t1"}],
            },
        )

        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(run_dir)
        orch = SwarmOrchestrator(cfg, "resume goal", resume=True)

        assert orch._load_existing_manifest() is True
        assert orch._tasks["t1"].read_files == ["src/shared.py"]
        assert orch._tasks["t1"].symbol_scope == ["parse"]
        assert orch._tasks["t1"].timeout_seconds == 90
        assert orch._task_attempts["t1"] == 2
        assert orch._task_attempt_history["t1"][0]["error"] == "boom"
        assert orch._budget.used_tokens == 12
        assert orch._budget.used_cost_usd == pytest.approx(0.5)
        assert orch._state_seq == 7

    @pytest.mark.asyncio
    async def test_run_resume_uses_saved_manifest_without_decomposition(self, tmp_path: Path, monkeypatch) -> None:
        from attoswarm.protocol.io import write_json_atomic

        run_dir = tmp_path / "run"
        tasks_dir = run_dir / "tasks"
        tasks_dir.mkdir(parents=True)
        write_json_atomic(
            run_dir / "swarm.manifest.json",
            {
                "run_id": "resume-123",
                "goal": "resume goal",
                "tasks": [
                    {
                        "task_id": "t1",
                        "title": "Already done",
                        "description": "done",
                        "deps": [],
                        "target_files": ["src/a.py"],
                    },
                    {
                        "task_id": "t2",
                        "title": "Pending",
                        "description": "pending",
                        "deps": [],
                        "target_files": ["src/b.py"],
                    },
                ],
            },
        )
        write_json_atomic(
            run_dir / "swarm.state.json",
            {
                "phase": "shutdown",
                "dag": {
                    "nodes": [
                        {"task_id": "t1", "status": "done"},
                        {"task_id": "t2", "status": "pending"},
                    ]
                },
            },
        )

        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(run_dir)
        cfg.workspace.git_safety = False
        orch = SwarmOrchestrator(cfg, "resume goal", resume=True)

        monkeypatch.setattr(orch, "_init_ast_service", lambda: None)
        monkeypatch.setattr(orch, "_init_code_intel", lambda: (_ for _ in ()).throw(AssertionError("code-intel should be skipped")))
        monkeypatch.setattr(orch, "_init_budget_projector", lambda: None)
        monkeypatch.setattr(orch, "_init_trace_bridge", lambda: None)
        monkeypatch.setattr(orch, "_init_file_ledger", lambda: None)
        monkeypatch.setattr(orch, "_bootstrap_context", lambda: (_ for _ in ()).throw(AssertionError("bootstrap should be skipped")))
        monkeypatch.setattr(orch, "_decompose_goal", AsyncMock(side_effect=AssertionError("decompose should be skipped")))
        monkeypatch.setattr(orch, "_check_pause", AsyncMock(return_value=None))
        monkeypatch.setattr(orch, "_check_control_messages", lambda: None)
        monkeypatch.setattr(orch, "_check_stale_agents", lambda: None)
        monkeypatch.setattr(orch._subagent_mgr, "execute_batch", AsyncMock(return_value=[
            TaskResult(task_id="t2", success=True, files_modified=["src/b.py"], result_summary="ok", tokens_used=500),
        ]))
        monkeypatch.setattr(orch._subagent_mgr, "shutdown_all", AsyncMock(return_value=None))

        completed = await orch.run()

        assert completed == 1
        assert orch._aot_graph.get_node("t1").status == "done"
        assert orch._aot_graph.get_node("t2").status == "done"


# ── _decompose_goal ──────────────────────────────────────────────────


class TestDecomposeGoal:
    def test_bootstrap_context_includes_parent_summary_without_code_intel(self, orch: SwarmOrchestrator) -> None:
        orch._lineage = LineageSpec(parent_summary={"parent_run_id": "parent-1", "branch": "attoswarm/demo"})
        orch._code_intel = None

        ctx = orch._bootstrap_context()

        assert json.loads(ctx) == {
            "parent_summary": {"parent_run_id": "parent-1", "branch": "attoswarm/demo"}
        }

    @pytest.mark.asyncio
    async def test_missing_decomposer_raises_planning_failure(self, orch: SwarmOrchestrator) -> None:
        with pytest.raises(PlanningFailure):
            await orch._decompose_goal()

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
    async def test_decompose_fn_failure_raises_planning_failure(self, tmp_path: Path) -> None:
        async def failing_decompose(goal: str, **kwargs: Any) -> list[TaskSpec]:
            raise RuntimeError("LLM error")

        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(tmp_path / "run")
        o = SwarmOrchestrator(cfg, "goal", decompose_fn=failing_decompose)
        o._setup_directories()

        with pytest.raises(PlanningFailure):
            await o._decompose_goal()

    def test_resolve_task_timeout_uses_watchdog_default(self, tmp_path: Path) -> None:
        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(tmp_path / "run")
        cfg.watchdog.task_max_duration_seconds = 123.0
        o = SwarmOrchestrator(cfg, "goal")

        task = TaskSpec(task_id="t1", title="One", description="desc", timeout_seconds=45)

        assert o._resolve_task_timeout(None) == 123.0
        assert o._resolve_task_timeout(task) == 45.0

    @pytest.mark.asyncio
    async def test_run_decompose_failure_sets_planning_failed_phase(self, tmp_path: Path, monkeypatch) -> None:
        async def failing_decompose(goal: str, **kwargs: Any) -> list[TaskSpec]:
            raise RuntimeError("LLM error")

        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(tmp_path / "run")
        o = SwarmOrchestrator(cfg, "goal", decompose_fn=failing_decompose)
        monkeypatch.setattr(o, "_init_ast_service", lambda: None)
        monkeypatch.setattr(o, "_init_code_intel", lambda: None)
        monkeypatch.setattr(o, "_init_budget_projector", lambda: None)
        monkeypatch.setattr(o, "_init_trace_bridge", lambda: None)
        monkeypatch.setattr(o, "_init_file_ledger", lambda: None)
        monkeypatch.setattr(o, "_bootstrap_context", lambda: "")

        code = await o.run()
        state = read_json(o._layout["state"], default={})

        assert code == 1
        assert o.phase == "planning_failed"
        assert state["phase"] == "planning_failed"

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


# ── _validate_task_result ────────────────────────────────────────────


class TestValidateTaskResultNone:
    """quality_gate='none' always passes."""

    def test_none_gate_passes_regardless(self, orch: SwarmOrchestrator) -> None:
        orch._config.orchestration.quality_gate = "none"
        _add_task(orch, "t1", status="running")
        result = TaskResult(task_id="t1", success=True, files_modified=[], tokens_used=0)
        passed, reason = orch._validate_task_result(result)
        assert passed is True
        assert reason == ""

    def test_none_gate_passes_unknown_task(self, orch: SwarmOrchestrator) -> None:
        orch._config.orchestration.quality_gate = "none"
        # Task not registered in orch._tasks — should still pass
        result = TaskResult(task_id="unknown", success=True, files_modified=[], tokens_used=0)
        passed, reason = orch._validate_task_result(result)
        assert passed is True


class TestValidateTaskResultBasic:
    """quality_gate='basic' checks files_modified and tokens_used."""

    def test_implement_empty_files_fails(self, orch: SwarmOrchestrator) -> None:
        orch._config.orchestration.quality_gate = "basic"
        task = _add_task(orch, "t1", status="running")
        task.task_kind = "implement"
        result = TaskResult(task_id="t1", success=True, files_modified=[], tokens_used=500)
        passed, reason = orch._validate_task_result(result)
        assert passed is False
        assert "implement task produced no file modifications" in reason

    def test_test_empty_files_fails(self, orch: SwarmOrchestrator) -> None:
        orch._config.orchestration.quality_gate = "basic"
        task = _add_task(orch, "t1", status="running")
        task.task_kind = "test"
        result = TaskResult(task_id="t1", success=True, files_modified=[], tokens_used=500)
        passed, reason = orch._validate_task_result(result)
        assert passed is False
        assert "test task produced no file modifications" in reason

    def test_implement_with_files_and_tokens_passes(self, orch: SwarmOrchestrator) -> None:
        orch._config.orchestration.quality_gate = "basic"
        task = _add_task(orch, "t1", status="running")
        task.task_kind = "implement"
        result = TaskResult(task_id="t1", success=True, files_modified=["src/a.py"], tokens_used=1000)
        passed, reason = orch._validate_task_result(result)
        assert passed is True
        assert reason == ""

    def test_zero_tokens_fails(self, orch: SwarmOrchestrator) -> None:
        orch._config.orchestration.quality_gate = "basic"
        task = _add_task(orch, "t1", status="running")
        task.task_kind = "analysis"
        result = TaskResult(task_id="t1", success=True, files_modified=["report.md"], tokens_used=0)
        passed, reason = orch._validate_task_result(result)
        assert passed is False
        assert "zero tokens used" in reason

    def test_analysis_empty_files_passes(self, orch: SwarmOrchestrator) -> None:
        orch._config.orchestration.quality_gate = "basic"
        task = _add_task(orch, "t1", status="running")
        task.task_kind = "analysis"
        result = TaskResult(task_id="t1", success=True, files_modified=[], tokens_used=500)
        passed, reason = orch._validate_task_result(result)
        assert passed is True
        assert reason == ""


class TestValidateTaskResultStrict:
    """quality_gate='strict' also checks target files exist on disk."""

    def test_strict_missing_target_file_fails(self, orch: SwarmOrchestrator, tmp_path: Path) -> None:
        orch._config.orchestration.quality_gate = "strict"
        orch._root_dir = str(tmp_path)
        task = _add_task(orch, "t1", status="running", target_files=["src/missing.py"])
        task.task_kind = "implement"
        result = TaskResult(task_id="t1", success=True, files_modified=["src/missing.py"], tokens_used=1000)
        passed, reason = orch._validate_task_result(result)
        assert passed is False
        assert "target file missing: src/missing.py" in reason

    def test_strict_existing_target_file_passes(self, orch: SwarmOrchestrator, tmp_path: Path) -> None:
        orch._config.orchestration.quality_gate = "strict"
        orch._root_dir = str(tmp_path)
        # Create the target file on disk
        target = tmp_path / "src" / "a.py"
        target.parent.mkdir(parents=True)
        target.write_text("print('hello')")
        task = _add_task(orch, "t1", status="running", target_files=["src/a.py"])
        task.task_kind = "implement"
        result = TaskResult(task_id="t1", success=True, files_modified=["src/a.py"], tokens_used=1000)
        passed, reason = orch._validate_task_result(result)
        assert passed is True
        assert reason == ""

    def test_strict_partial_missing_lists_all(self, orch: SwarmOrchestrator, tmp_path: Path) -> None:
        """When some target files exist and some don't, reason lists each missing one."""
        orch._config.orchestration.quality_gate = "strict"
        orch._root_dir = str(tmp_path)
        (tmp_path / "exists.py").write_text("ok")
        task = _add_task(orch, "t1", status="running", target_files=["exists.py", "gone.py"])
        task.task_kind = "implement"
        result = TaskResult(task_id="t1", success=True, files_modified=["exists.py"], tokens_used=500)
        passed, reason = orch._validate_task_result(result)
        assert passed is False
        assert "gone.py" in reason
        assert "exists.py" not in reason  # exists.py is present, should not appear in reason
