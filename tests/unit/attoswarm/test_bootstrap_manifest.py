"""Integration tests for HybridCoordinator._bootstrap_manifest."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from attoswarm.config.schema import OrchestrationConfig, RoleConfig, SwarmYamlConfig
from attoswarm.coordinator.loop import HybridCoordinator
from attoswarm.protocol.models import default_run_layout


def _make_config(**overrides: object) -> SwarmYamlConfig:
    config = SwarmYamlConfig()
    if "orchestration" in overrides:
        config = replace(config, orchestration=overrides["orchestration"])  # type: ignore[arg-type]
    if "roles" in overrides:
        config = replace(config, roles=overrides["roles"])  # type: ignore[arg-type]
    return config


def _worker_role(count: int = 1) -> RoleConfig:
    return RoleConfig(
        role_id="dev",
        role_type="worker",
        backend="claude",
        model="",
        count=count,
        write_access=True,
        workspace_mode="worktree",
    )


class TestBootstrapManifest:
    """Verify _bootstrap_manifest creates correct files and populates state."""

    @pytest.fixture()
    def coord(self, tmp_path: Path) -> HybridCoordinator:
        """Coordinator wired to a tmp_path run directory."""
        config = _make_config(
            orchestration=OrchestrationConfig(decomposition="fast"),
            roles=[_worker_role(count=2)],
        )
        c = HybridCoordinator(config, goal="Build a widget")
        c.layout = default_run_layout(tmp_path)
        c._ensure_layout()
        return c

    def _bootstrap(self, coord: HybridCoordinator) -> None:
        """Call _bootstrap_manifest with index snapshot mocked out."""
        with patch.object(coord, "_build_index_snapshot"):
            coord._bootstrap_manifest()

    # ---- manifest.json ---------------------------------------------------

    def test_manifest_file_created(self, coord: HybridCoordinator) -> None:
        self._bootstrap(coord)
        manifest_path = coord.layout["manifest"]
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["schema_version"] == "1.0"
        assert data["goal"] == "Build a widget"
        assert data["run_id"] == coord.run_id

    def test_manifest_roles(self, coord: HybridCoordinator) -> None:
        self._bootstrap(coord)
        data = json.loads(coord.layout["manifest"].read_text())
        roles = data["roles"]
        assert len(roles) >= 1
        assert roles[0]["role_id"] == "dev"
        assert roles[0]["role_type"] == "worker"

    def test_manifest_tasks(self, coord: HybridCoordinator) -> None:
        self._bootstrap(coord)
        data = json.loads(coord.layout["manifest"].read_text())
        tasks = data["tasks"]
        assert len(tasks) >= 2
        # fast mode with 2 workers: implement + test + integrate
        kinds = [t["task_kind"] for t in tasks]
        assert "implement" in kinds
        assert "integrate" in kinds

    # ---- per-task JSON files ---------------------------------------------

    def test_task_json_files_created(self, coord: HybridCoordinator) -> None:
        self._bootstrap(coord)
        tasks_dir = coord.layout["tasks"]
        task_files = sorted(tasks_dir.glob("task-*.json"))
        assert len(task_files) >= 2
        for tf in task_files:
            data = json.loads(tf.read_text())
            assert "task_id" in data
            assert "status" in data
            assert "transitions" in data
            assert "attempts" in data

    def test_task_json_matches_manifest(self, coord: HybridCoordinator) -> None:
        self._bootstrap(coord)
        manifest = json.loads(coord.layout["manifest"].read_text())
        for mt in manifest["tasks"]:
            task_file = coord.layout["tasks"] / f"task-{mt['task_id']}.json"
            assert task_file.exists(), f"Missing task file for {mt['task_id']}"
            data = json.loads(task_file.read_text())
            assert data["task_id"] == mt["task_id"]
            assert data["status"] == mt["status"]

    # ---- task_state and task_attempts ------------------------------------

    def test_task_state_populated(self, coord: HybridCoordinator) -> None:
        self._bootstrap(coord)
        assert len(coord.task_state) >= 2
        # First task should be ready (fast mode)
        assert coord.task_state["t0"] == "ready"

    def test_task_attempts_initialized(self, coord: HybridCoordinator) -> None:
        self._bootstrap(coord)
        for tid in coord.task_state:
            assert coord.task_attempts[tid] == 0

    # ---- manual mode -----------------------------------------------------

    def test_manual_mode_single_ready_task(self, tmp_path: Path) -> None:
        config = _make_config(
            orchestration=OrchestrationConfig(decomposition="manual"),
            roles=[_worker_role(count=1)],
        )
        coord = HybridCoordinator(config, goal="Manual task")
        coord.layout = default_run_layout(tmp_path)
        coord._ensure_layout()

        with patch.object(coord, "_build_index_snapshot"):
            coord._bootstrap_manifest()

        assert coord.task_state["t0"] == "ready"
        task_file = coord.layout["tasks"] / "task-t0.json"
        data = json.loads(task_file.read_text())
        assert data["status"] == "ready"

    # ---- index snapshot failure is non-fatal -----------------------------

    def test_index_snapshot_failure_does_not_crash(self, coord: HybridCoordinator) -> None:
        with patch(
            "attoswarm.coordinator.loop.CodeIndex.build",
            side_effect=IsADirectoryError("glob-to-regex.js"),
        ):
            coord._bootstrap_manifest()  # should not raise

        # Manifest and tasks still created
        assert coord.layout["manifest"].exists()
        assert len(coord.task_state) >= 2

    def test_index_snapshot_failure_emits_event(self, coord: HybridCoordinator) -> None:
        with patch(
            "attoswarm.coordinator.loop.CodeIndex.build",
            side_effect=OSError("disk full"),
        ):
            coord._bootstrap_manifest()

        events_path = coord.layout["events"]
        lines = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        snapshot_events = [e for e in lines if e["type"] == "index.snapshot_failed"]
        assert len(snapshot_events) == 1
        payload = snapshot_events[0]["payload"]
        assert payload["reason"] == "build_error"
        assert payload["error"] == "disk full"
        assert payload["error_type"] == "OSError"

    # ---- decomposition mode fallback events --------------------------------

    def test_unknown_mode_emits_fallback_event(self, tmp_path: Path) -> None:
        config = _make_config(
            orchestration=OrchestrationConfig(decomposition="nonexistent"),
            roles=[_worker_role(count=1)],
        )
        coord = HybridCoordinator(config, goal="Fallback test")
        coord.layout = default_run_layout(tmp_path)
        coord._ensure_layout()

        with patch.object(coord, "_build_index_snapshot"):
            coord._bootstrap_manifest()

        events_path = coord.layout["events"]
        lines = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        fallback_events = [e for e in lines if e["type"] == "decomposition.fallback"]
        assert len(fallback_events) == 1
        payload = fallback_events[0]["payload"]
        assert payload["reason"] == "unknown_mode"
        assert payload["mode"] == "nonexistent"
        assert payload["using"] == "default_pipeline"

    def test_heuristic_mode_no_fallback_event(self, tmp_path: Path) -> None:
        config = _make_config(
            orchestration=OrchestrationConfig(decomposition="heuristic"),
            roles=[_worker_role(count=1)],
        )
        coord = HybridCoordinator(config, goal="Heuristic test")
        coord.layout = default_run_layout(tmp_path)
        coord._ensure_layout()

        with patch.object(coord, "_build_index_snapshot"):
            coord._bootstrap_manifest()

        events_path = coord.layout["events"]
        if events_path.exists():
            lines = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
            fallback_events = [e for e in lines if e["type"] == "decomposition.fallback"]
            assert len(fallback_events) == 0
        # Tasks should still be created via default pipeline
        assert len(coord.task_state) >= 1
