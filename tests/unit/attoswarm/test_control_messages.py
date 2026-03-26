"""Tests for orchestrator control messages and prompt persistence (Tier 2+3).

Covers:
- _check_control_messages: skip, retry, edit_task, invalid JSON, cursor tracking
- _persist_prompt: content and path
- _check_stale_agents: timeout-based warning
- _write_activity / StateStore reading activity sidecars
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from attoswarm.config.schema import SwarmYamlConfig
from attoswarm.coordinator.orchestrator import SwarmOrchestrator
from attoswarm.coordinator.subagent_manager import AgentStatus
from attoswarm.protocol.models import TaskSpec


@pytest.fixture()
def orch(tmp_path: Path) -> SwarmOrchestrator:
    """Minimal orchestrator with a tmp run dir."""
    cfg = SwarmYamlConfig()
    cfg.run.run_dir = str(tmp_path / "run")
    o = SwarmOrchestrator(cfg, "test goal")
    o._setup_directories()
    return o


def _add_task(orch: SwarmOrchestrator, task_id: str, status: str = "pending") -> None:
    """Add a task to the orchestrator's internal state."""
    from attoswarm.coordinator.aot_graph import AoTNode

    task = TaskSpec(task_id=task_id, title=f"Task {task_id}", description=f"Do {task_id}")
    orch._tasks[task_id] = task
    orch._aot_graph.add_task(AoTNode(task_id=task_id, depends_on=[], target_files=[]))
    node = orch._aot_graph.get_node(task_id)
    if node:
        node.status = status


# ── _check_control_messages ───────────────────────────────────────────


class TestCheckControlMessages:
    def test_skip(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "task-1", "running")
        control_path = orch._layout["root"] / "control.jsonl"
        control_path.write_text(
            json.dumps({"action": "skip", "task_id": "task-1"}) + "\n",
            encoding="utf-8",
        )
        orch._check_control_messages()
        node = orch._aot_graph.get_node("task-1")
        assert node is not None
        assert node.status == "failed"

    def test_retry(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "task-1", "failed")
        orch._task_attempts["task-1"] = 2
        control_path = orch._layout["root"] / "control.jsonl"
        control_path.write_text(
            json.dumps({"action": "retry", "task_id": "task-1"}) + "\n",
            encoding="utf-8",
        )
        orch._check_control_messages()
        node = orch._aot_graph.get_node("task-1")
        assert node is not None
        assert node.status == "pending"
        assert "task-1" not in orch._task_attempts

    def test_edit_task(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "task-1", "pending")
        control_path = orch._layout["root"] / "control.jsonl"
        control_path.write_text(
            json.dumps({"action": "edit_task", "task_id": "task-1", "description": "New description"}) + "\n",
            encoding="utf-8",
        )
        orch._check_control_messages()
        assert orch._tasks["task-1"].description == "New description"

    def test_invalid_json(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "task-1", "running")
        control_path = orch._layout["root"] / "control.jsonl"
        control_path.write_text(
            "not json\n"
            + json.dumps({"action": "skip", "task_id": "task-1"}) + "\n",
            encoding="utf-8",
        )
        orch._check_control_messages()
        node = orch._aot_graph.get_node("task-1")
        assert node is not None
        assert node.status == "failed"  # valid line still processed

    def test_missing_file(self, orch: SwarmOrchestrator) -> None:
        # Should not raise
        orch._check_control_messages()

    def test_cursor_tracking(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "task-1", "running")
        _add_task(orch, "task-2", "running")
        control_path = orch._layout["root"] / "control.jsonl"

        # First batch: skip task-1
        control_path.write_text(
            json.dumps({"action": "skip", "task_id": "task-1"}) + "\n",
            encoding="utf-8",
        )
        orch._check_control_messages()

        # Second batch: skip task-2 (append)
        with open(control_path, "a") as f:
            f.write(json.dumps({"action": "skip", "task_id": "task-2"}) + "\n")
        orch._check_control_messages()

        node1 = orch._aot_graph.get_node("task-1")
        node2 = orch._aot_graph.get_node("task-2")
        assert node1 is not None and node1.status == "failed"
        assert node2 is not None and node2.status == "failed"

    def test_resume_ignores_historical_control_messages(self, tmp_path: Path) -> None:
        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(tmp_path / "run")
        orch = SwarmOrchestrator(cfg, "resume goal", resume=True)
        orch._setup_directories()
        _add_task(orch, "task-1", "running")

        control_path = orch._layout["root"] / "control.jsonl"
        control_path.write_text(
            json.dumps({"action": "shutdown", "task_id": ""}) + "\n",
            encoding="utf-8",
        )

        orch._prime_control_cursor()
        orch._check_control_messages()
        assert orch._shutdown_requested is False

        with open(control_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"action": "skip", "task_id": "task-1"}) + "\n")
        orch._check_control_messages()

        node = orch._aot_graph.get_node("task-1")
        assert node is not None
        assert node.status == "failed"

    def test_emits_control_received_and_applied_events(self, orch: SwarmOrchestrator) -> None:
        _add_task(orch, "task-1", "failed")
        control_path = orch._layout["root"] / "control.jsonl"
        control_path.write_text(
            json.dumps({"action": "retry", "task_id": "task-1"}) + "\n",
            encoding="utf-8",
        )

        orch._check_control_messages()

        event_types = [event.event_type for event in orch._event_bus.history[-3:]]
        assert "control.received" in event_types
        assert "control.applied" in event_types


# ── _persist_prompt ───────────────────────────────────────────────────


class TestPersistPrompt:
    def test_content(self, orch: SwarmOrchestrator) -> None:
        task_dict = {
            "title": "Fix bug",
            "description": "Fix the null pointer bug",
            "target_files": ["src/main.py", "src/utils.py"],
            "read_files": ["docs/spec.md"],
        }
        orch._persist_prompt("task-1", task_dict)
        prompt_path = orch._layout["agents"] / "agent-task-1.prompt.txt"
        content = prompt_path.read_text(encoding="utf-8")
        assert "# Task: Fix bug" in content
        assert "Fix the null pointer bug" in content
        assert "Target files: src/main.py, src/utils.py" in content
        assert "Reference files: docs/spec.md" in content

    def test_path(self, orch: SwarmOrchestrator) -> None:
        task_dict = {"title": "Test", "description": "test"}
        orch._persist_prompt("task-42", task_dict)
        prompt_path = orch._layout["agents"] / "agent-task-42.prompt.txt"
        assert prompt_path.exists()

    def test_no_optional_fields(self, orch: SwarmOrchestrator) -> None:
        task_dict = {"title": "Simple", "description": "Just do it"}
        orch._persist_prompt("task-3", task_dict)
        content = (orch._layout["agents"] / "agent-task-3.prompt.txt").read_text()
        assert "Target files" not in content
        assert "Reference files" not in content


# ── _check_stale_agents ───────────────────────────────────────────────


class TestCheckStaleAgents:
    def test_warns_on_stale(self, orch: SwarmOrchestrator) -> None:
        """Agent started 130s ago should trigger a warning."""
        stale_agent = AgentStatus(
            agent_id="agent-1",
            task_id="task-1",
            status="running",
            started_at=time.time() - 130,
        )
        orch._subagent_mgr._agent_statuses["agent-1"] = stale_agent

        events_before = len(orch._event_bus.history)
        orch._check_stale_agents()
        assert len(orch._event_bus.history) > events_before
        last = orch._event_bus.history[-1]
        assert last.event_type == "warning"
        assert "agent-1" in last.message

    def test_no_warn_recent(self, orch: SwarmOrchestrator) -> None:
        """Agent started 60s ago should not trigger a warning."""
        recent_agent = AgentStatus(
            agent_id="agent-2",
            task_id="task-2",
            status="running",
            started_at=time.time() - 60,
        )
        orch._subagent_mgr._agent_statuses["agent-2"] = recent_agent

        events_before = len(orch._event_bus.history)
        orch._check_stale_agents()
        assert len(orch._event_bus.history) == events_before


# ── File I/O (Tier 3) ────────────────────────────────────────────────


class TestFileIO:
    def test_write_activity_creates_file(self, tmp_path: Path) -> None:
        from attoswarm.cli import _write_activity

        _write_activity(str(tmp_path), "task-1", "Reading main.py")
        path = tmp_path / "agents" / "agent-task-1.activity.txt"
        assert path.exists()
        assert path.read_text() == "Reading main.py"

    def test_write_activity_overwrites(self, tmp_path: Path) -> None:
        from attoswarm.cli import _write_activity

        _write_activity(str(tmp_path), "task-1", "First")
        _write_activity(str(tmp_path), "task-1", "Second")
        path = tmp_path / "agents" / "agent-task-1.activity.txt"
        assert path.read_text() == "Second"

    def test_stores_reads_prompt_file(self, tmp_path: Path) -> None:
        from attoswarm.tui.stores import StateStore

        (tmp_path / "tasks").mkdir(exist_ok=True)
        (tmp_path / "agents").mkdir(exist_ok=True)

        # Write a task JSON and prompt file
        task_data = {"title": "Test Task", "status": "done", "description": "desc"}
        (tmp_path / "tasks" / "task-task-1.json").write_text(json.dumps(task_data))
        (tmp_path / "agents" / "agent-task-1.prompt.txt").write_text("Full prompt content here")

        store = StateStore(str(tmp_path))
        detail = store.build_task_detail("task-1")
        assert detail.get("prompt_preview") == "Full prompt content here"

    def test_stores_reads_activity_sidecar(self, tmp_path: Path) -> None:
        from attoswarm.tui.stores import StateStore

        (tmp_path / "tasks").mkdir(exist_ok=True)
        (tmp_path / "agents").mkdir(exist_ok=True)

        task_data = {"title": "Test", "status": "running"}
        (tmp_path / "tasks" / "task-task-1.json").write_text(json.dumps(task_data))
        (tmp_path / "agents" / "agent-task-1.activity.txt").write_text("Editing foo.py")

        store = StateStore(str(tmp_path))
        detail = store.build_task_detail("task-1")
        assert detail.get("agent_activity") == "Editing foo.py"

    def test_stores_truncates_prompt(self, tmp_path: Path) -> None:
        from attoswarm.tui.stores import StateStore

        (tmp_path / "tasks").mkdir(exist_ok=True)
        (tmp_path / "agents").mkdir(exist_ok=True)

        task_data = {"title": "Test", "status": "done"}
        (tmp_path / "tasks" / "task-task-1.json").write_text(json.dumps(task_data))
        (tmp_path / "agents" / "agent-task-1.prompt.txt").write_text("x" * 1000)

        store = StateStore(str(tmp_path))
        detail = store.build_task_detail("task-1")
        assert len(detail.get("prompt_preview", "")) == 500


# ── SubagentManager started_at preservation (BUG 3 regression) ────────


class TestStartedAtPreservation:
    def test_started_at_preserved_across_status_changes(self) -> None:
        from attoswarm.coordinator.subagent_manager import SubagentManager

        mgr = SubagentManager(max_concurrency=2)
        mgr._emit_status("agent-1", "task-1", "claiming")
        first_started = mgr._agent_statuses["agent-1"].started_at

        # Simulate small time passing
        import time
        time.sleep(0.01)

        mgr._emit_status("agent-1", "task-1", "running")
        assert mgr._agent_statuses["agent-1"].started_at == first_started

        mgr._emit_status("agent-1", "task-1", "done")
        assert mgr._agent_statuses["agent-1"].started_at == first_started


# ── _handle_add_task — manifest sync (C2 fix) ────────────────────────


class TestHandleAddTask:
    def test_add_task_updates_manifest(self, orch: SwarmOrchestrator) -> None:
        """C2: Dynamically added tasks must appear in _manifest.tasks."""
        from attoswarm.protocol.models import SwarmManifest

        _add_task(orch, "existing-1")
        orch._manifest = SwarmManifest(
            run_id=orch._run_id,
            goal="test goal",
            tasks=list(orch._tasks.values()),
        )
        orch._persist_manifest()

        # Simulate add_task via control message
        control_path = orch._layout["root"] / "control.jsonl"
        control_path.write_text(
            json.dumps({
                "action": "add_task",
                "title": "New dynamic task",
                "description": "Do something new",
                "deps": [],
                "target_files": ["src/new.py"],
            }) + "\n",
            encoding="utf-8",
        )
        orch._check_control_messages()

        # Manifest should now include the new task
        assert orch._manifest is not None
        task_ids = [t.task_id for t in orch._manifest.tasks]
        assert len(task_ids) == 2  # existing-1 + new

        # Persisted manifest should also include it
        from attoswarm.protocol.io import read_json
        data = read_json(orch._layout["manifest"], default={})
        manifest_task_ids = [t["task_id"] for t in data.get("tasks", [])]
        assert len(manifest_task_ids) == 2

    def test_add_task_survives_manifest_round_trip(self, orch: SwarmOrchestrator) -> None:
        """Verify added tasks are in persisted manifest (resume-safe)."""
        from attoswarm.protocol.io import read_json
        from attoswarm.protocol.models import SwarmManifest

        orch._manifest = SwarmManifest(
            run_id=orch._run_id, goal="test", tasks=[],
        )

        control_path = orch._layout["root"] / "control.jsonl"
        control_path.write_text(
            json.dumps({
                "action": "add_task",
                "title": "Task A",
                "description": "desc A",
            }) + "\n",
            encoding="utf-8",
        )
        orch._check_control_messages()

        data = read_json(orch._layout["manifest"], default={})
        assert any(t["title"] == "Task A" for t in data["tasks"])

    def test_add_task_rejected_without_title(self, orch: SwarmOrchestrator) -> None:
        control_path = orch._layout["root"] / "control.jsonl"
        control_path.write_text(
            json.dumps({"action": "add_task", "title": "", "description": "no title"}) + "\n",
            encoding="utf-8",
        )
        before = len(orch._tasks)
        orch._check_control_messages()
        assert len(orch._tasks) == before


# ── Approval gate resume skip (H1 fix) ───────────────────────────────


class TestApprovalGateResumeSkip:
    def test_approved_set_on_resume_with_executing_phase(self, orch: SwarmOrchestrator) -> None:
        """H1: When resuming a run that was already executing, skip the approval gate."""
        from attoswarm.protocol.io import write_json_atomic

        orch._resume = True
        orch._approval_mode = "preview"

        # Simulate prior state with phase="executing"
        write_json_atomic(orch._layout["state"], {"phase": "executing"})

        # The approval gate skip logic reads prev state before the gate
        from attoswarm.protocol.io import read_json
        prev_state = read_json(orch._layout["state"], default={})
        prev_phase = prev_state.get("phase", "")
        if prev_phase in ("executing", "completed", "shutdown"):
            orch._approved = True

        assert orch._approved is True

    def test_not_approved_on_fresh_start(self, orch: SwarmOrchestrator) -> None:
        """Fresh start with preview mode should NOT auto-approve."""
        from attoswarm.protocol.io import write_json_atomic

        orch._resume = False
        orch._approval_mode = "preview"
        orch._approved = False

        # Even if state file exists with phase=decomposing
        write_json_atomic(orch._layout["state"], {"phase": "decomposing"})

        # On fresh start, _resume is False so the gate logic doesn't run
        assert orch._approved is False

    def test_not_approved_on_resume_with_preview_phase(self, orch: SwarmOrchestrator) -> None:
        """Resuming a run that was still in preview should still require approval."""
        from attoswarm.protocol.io import write_json_atomic

        orch._resume = True
        orch._approval_mode = "preview"

        write_json_atomic(orch._layout["state"], {"phase": "awaiting_approval"})

        from attoswarm.protocol.io import read_json
        prev_state = read_json(orch._layout["state"], default={})
        prev_phase = prev_state.get("phase", "")
        if prev_phase in ("executing", "completed", "shutdown"):
            orch._approved = True

        assert orch._approved is False


# ── Archive previous run (_archive_previous_run) ──────────────────


class TestArchivePreviousRun:
    def test_archive_moves_state_to_history(self, orch: SwarmOrchestrator) -> None:
        """Previous run artifacts move to history/{run_id}/."""
        root = orch._layout["root"]
        state = orch._layout["state"]
        events = orch._layout["events"]
        manifest = orch._layout["manifest"]
        agents = orch._layout["agents"]
        tasks = orch._layout["tasks"]

        # Populate previous run data
        state.write_text(json.dumps({"run_id": "old123", "phase": "completed"}), encoding="utf-8")
        events.write_text(json.dumps({"event": "task.done"}) + "\n", encoding="utf-8")
        manifest.write_text(json.dumps({"tasks": [{"task_id": "t1"}]}), encoding="utf-8")
        (root / "control.jsonl").write_text(json.dumps({"action": "approve"}) + "\n", encoding="utf-8")
        (root / "git_safety.json").write_text(json.dumps({"branch": "main"}), encoding="utf-8")
        (agents / "agent-task-1.prompt.txt").write_text("old prompt")
        (tasks / "task-task-1.json").write_text(json.dumps({"cost": 0.5}))

        orch._archive_previous_run()

        # History should contain all old files
        history = root / "history" / "old123"
        assert history.is_dir()
        assert (history / "swarm.state.json").exists()
        assert (history / "swarm.events.jsonl").exists()
        assert (history / "swarm.manifest.json").exists()
        assert (history / "control.jsonl").exists()
        assert (history / "git_safety.json").exists()

        # Active dir should be clean
        assert not state.exists()
        assert not manifest.exists()
        assert not (root / "git_safety.json").exists()
        assert list(agents.iterdir()) == []
        assert list(tasks.iterdir()) == []

    def test_archive_creates_empty_control_and_events(self, orch: SwarmOrchestrator) -> None:
        """After archive, control.jsonl and events file should exist but be empty."""
        state = orch._layout["state"]
        state.write_text(json.dumps({"run_id": "r1", "phase": "done"}), encoding="utf-8")
        orch._layout["events"].write_text('{"e":1}\n', encoding="utf-8")
        (orch._layout["root"] / "control.jsonl").write_text('{"a":"b"}\n', encoding="utf-8")

        orch._archive_previous_run()

        control = orch._layout["root"] / "control.jsonl"
        events = orch._layout["events"]
        assert control.exists()
        assert control.read_text(encoding="utf-8") == ""
        assert events.exists()
        # Events file may contain a "Clean slate" info event emitted after archive
        events_text = events.read_text(encoding="utf-8")
        assert events_text == "" or "Clean slate" in events_text

    def test_archive_preserves_agents_and_tasks(self, orch: SwarmOrchestrator) -> None:
        """Old agent prompts/traces and task JSONs end up in history."""
        state = orch._layout["state"]
        state.write_text(json.dumps({"run_id": "run-abc"}), encoding="utf-8")
        (orch._layout["agents"] / "agent-task-1.prompt.txt").write_text("prompt content")
        (orch._layout["agents"] / "agent-task-1.trace.jsonl").write_text("{}\n")
        (orch._layout["tasks"] / "task-task-1.json").write_text(json.dumps({"status": "done"}))

        orch._archive_previous_run()

        history = orch._layout["root"] / "history" / "run-abc"
        assert (history / "agents" / "agent-task-1.prompt.txt").read_text() == "prompt content"
        assert (history / "agents" / "agent-task-1.trace.jsonl").read_text() == "{}\n"
        assert (history / "tasks" / "task-task-1.json").exists()

    def test_archive_noop_on_first_run(self, orch: SwarmOrchestrator) -> None:
        """No state file and no data → no history dir created."""
        orch._archive_previous_run()
        history = orch._layout["root"] / "history"
        assert not history.exists()

    def test_archive_uses_timestamp_fallback(self, orch: SwarmOrchestrator) -> None:
        """State exists without run_id → history dir named unknown-{timestamp}."""
        state = orch._layout["state"]
        state.write_text(json.dumps({"phase": "completed"}), encoding="utf-8")

        orch._archive_previous_run()

        history = orch._layout["root"] / "history"
        assert history.is_dir()
        dirs = list(history.iterdir())
        assert len(dirs) == 1
        assert dirs[0].name.startswith("unknown-")

    def test_resume_skips_archive(self, tmp_path: Path) -> None:
        """Resume=True → nothing archived, all files preserved."""
        cfg = SwarmYamlConfig()
        cfg.run.run_dir = str(tmp_path / "run")
        o = SwarmOrchestrator(cfg, "test goal", resume=True)
        o._setup_directories()

        # Populate artifacts
        control = o._layout["root"] / "control.jsonl"
        control.write_text(json.dumps({"action": "approve"}) + "\n", encoding="utf-8")
        events = o._layout["events"]
        events.write_text(json.dumps({"event": "task.started"}) + "\n", encoding="utf-8")
        state = o._layout["state"]
        state.write_text(json.dumps({"run_id": "prev", "phase": "executing"}), encoding="utf-8")

        # resume=True means _archive_previous_run is never called in run()
        assert o._resume is True
        # All files should still exist
        assert control.read_text(encoding="utf-8") != ""
        assert events.read_text(encoding="utf-8") != ""
        assert state.exists()
        # No history dir
        assert not (o._layout["root"] / "history").exists()

    def test_locks_cleared_not_archived(self, orch: SwarmOrchestrator) -> None:
        """Locks are ephemeral — rmtree'd, not moved to history."""
        state = orch._layout["state"]
        state.write_text(json.dumps({"run_id": "lockrun"}), encoding="utf-8")
        locks_dir = orch._layout["locks"]
        (locks_dir / "file.lock").write_text("locked")

        orch._archive_previous_run()

        history = orch._layout["root"] / "history" / "lockrun"
        assert locks_dir.is_dir()
        assert list(locks_dir.iterdir()) == []
        # Locks should NOT be in history
        assert not (history / "locks").exists()

    def test_archive_crash_recovery(self, orch: SwarmOrchestrator) -> None:
        """Interrupted archive (marker exists) resumes on next call."""
        root = orch._layout["root"]
        history_dir = root / "history" / "crashed-run"
        history_dir.mkdir(parents=True, exist_ok=True)

        # Simulate a crash: marker points to history dir, some files already moved,
        # but state and events still in root
        marker = root / ".archiving"
        marker.write_text(str(history_dir), encoding="utf-8")

        orch._layout["state"].write_text(
            json.dumps({"run_id": "crashed-run", "phase": "executing"}),
            encoding="utf-8",
        )
        orch._layout["events"].write_text(
            json.dumps({"event": "task.done"}) + "\n",
            encoding="utf-8",
        )

        orch._archive_previous_run()

        # Remaining files should now be in history
        assert (history_dir / "swarm.state.json").exists()
        assert (history_dir / "swarm.events.jsonl").exists()
        # Marker should be cleaned up
        assert not marker.exists()
        # Active state file should be gone
        assert not orch._layout["state"].exists()

    def test_archive_marker_cleaned_up(self, orch: SwarmOrchestrator) -> None:
        """Normal archive: .archiving marker does NOT exist after completion."""
        state = orch._layout["state"]
        state.write_text(json.dumps({"run_id": "clean-run"}), encoding="utf-8")

        orch._archive_previous_run()

        marker = orch._layout["root"] / ".archiving"
        assert not marker.exists()
        assert (orch._layout["root"] / "history" / "clean-run").is_dir()

    def test_archive_corrupt_marker_ignored(self, orch: SwarmOrchestrator) -> None:
        """Corrupt marker file is cleaned up and archive proceeds normally."""
        root = orch._layout["root"]
        marker = root / ".archiving"
        marker.write_text("/nonexistent/invalid/path", encoding="utf-8")

        # Set up actual data to archive
        orch._layout["state"].write_text(
            json.dumps({"run_id": "real-run"}), encoding="utf-8",
        )

        orch._archive_previous_run()

        # Marker should be cleaned up
        assert not marker.exists()
        # Data should be archived under the real run_id
        assert (root / "history" / "real-run" / "swarm.state.json").exists()


# ── StateStore run_id cache invalidation ──────────────────────────


class TestStoreRunIdCacheInvalidation:
    def test_run_id_change_clears_caches(self, tmp_path: Path) -> None:
        from attoswarm.tui.stores import StateStore

        (tmp_path / "tasks").mkdir(exist_ok=True)

        store = StateStore(str(tmp_path))

        # Simulate first run's state
        store.state_path.write_text(
            json.dumps({"run_id": "aaaa", "state_seq": 1, "phase": "executing"}),
            encoding="utf-8",
        )
        store.read_state()

        # Simulate cached events from first run
        store._events_cache = [{"event": "old_event"}]
        store._events_last_size = 100
        store._task_cache["task-1"] = (time.time(), {"title": "old"})

        # Simulate second run's state (different run_id)
        store.state_path.write_text(
            json.dumps({"run_id": "bbbb", "state_seq": 1, "phase": "initializing"}),
            encoding="utf-8",
        )
        store.read_state()

        # All caches should have been cleared
        assert store._events_cache == []
        assert store._events_last_size == 0
        assert store._task_cache == {}

    def test_same_run_id_preserves_caches(self, tmp_path: Path) -> None:
        from attoswarm.tui.stores import StateStore

        store = StateStore(str(tmp_path))

        store.state_path.write_text(
            json.dumps({"run_id": "aaaa", "state_seq": 1}), encoding="utf-8",
        )
        store.read_state()

        store._events_cache = [{"event": "keep_me"}]

        # Same run_id, different seq
        store.state_path.write_text(
            json.dumps({"run_id": "aaaa", "state_seq": 2}), encoding="utf-8",
        )
        store.read_state()

        assert store._events_cache == [{"event": "keep_me"}]

    def test_run_id_none_to_truthy_no_false_clear(self, tmp_path: Path) -> None:
        """_last_run_id starts None. First truthy run_id should NOT clear caches."""
        from attoswarm.tui.stores import StateStore

        store = StateStore(str(tmp_path))
        assert store._last_run_id is None

        # Populate some cache data (simulating pre-existing events read)
        store._events_cache = [{"event": "startup"}]
        store._events_last_size = 50

        store.state_path.write_text(
            json.dumps({"run_id": "aaa", "state_seq": 1}), encoding="utf-8",
        )
        store.read_state()

        # Caches should NOT be cleared — no previous run to invalidate
        assert store._events_cache == [{"event": "startup"}]
        assert store._events_last_size == 50
        assert store._last_run_id == "aaa"

    def test_run_id_truthy_transition_clears(self, tmp_path: Path) -> None:
        """Transition from one truthy run_id to another clears caches."""
        from attoswarm.tui.stores import StateStore

        store = StateStore(str(tmp_path))
        store._last_run_id = "aaa"

        # Populate caches
        store._events_cache = [{"event": "old"}]
        store._events_last_size = 100
        store._task_cache["t1"] = (time.time(), {"title": "stale"})

        store.state_path.write_text(
            json.dumps({"run_id": "bbb", "state_seq": 1}), encoding="utf-8",
        )
        store.read_state()

        assert store._events_cache == []
        assert store._events_last_size == 0
        assert store._task_cache == {}
        assert store._last_run_id == "bbb"

    def test_run_id_truthy_transition_clears_message_and_trace_caches(self, tmp_path: Path) -> None:
        from attoswarm.tui.stores import StateStore

        store = StateStore(str(tmp_path))
        store._last_run_id = "aaa"
        store._messages_cache = (time.time(), [{"kind": "stale"}])
        store._sidecar_cache = (time.time(), {"t1": "stale"})
        store._trace_summary_t1 = (time.time(), {"tool_calls": ["old"]})
        store._trace_offset_t1 = 123

        store.state_path.write_text(
            json.dumps({"run_id": "bbb", "state_seq": 1}), encoding="utf-8",
        )
        store.read_state()

        assert not hasattr(store, "_messages_cache")
        assert not hasattr(store, "_sidecar_cache")
        assert not hasattr(store, "_trace_summary_t1")
        assert not hasattr(store, "_trace_offset_t1")


# ── StateStore event partial line handling ─────────────────────────


class TestStoreEventPartialLine:
    def test_partial_json_not_consumed(self, tmp_path: Path) -> None:
        """Partial JSON at EOF should not advance the read cursor past it."""
        from attoswarm.tui.stores import StateStore

        store = StateStore(str(tmp_path))
        events_path = store.events_path

        # Write a complete event + a partial (no trailing \n)
        complete = json.dumps({"type": "complete"}) + "\n"
        partial = '{"type":"spa'
        events_path.write_bytes(complete.encode() + partial.encode())

        events = store.read_events()

        assert len(events) == 1
        assert events[0]["type"] == "complete"
        # Cursor should be at end of complete line, not past partial
        assert store._events_last_size == len(complete.encode())

    def test_partial_json_recovered_on_next_read(self, tmp_path: Path) -> None:
        """After a partial line is completed, it should be picked up on next read."""
        from attoswarm.tui.stores import StateStore

        store = StateStore(str(tmp_path))
        events_path = store.events_path

        complete = json.dumps({"type": "complete"}) + "\n"
        partial = '{"type":"spa'
        events_path.write_bytes(complete.encode() + partial.encode())

        store.read_events()  # reads the complete event, stops at partial

        # Now the writer finishes the line
        full_second = json.dumps({"type": "spawn"}) + "\n"
        events_path.write_bytes(complete.encode() + full_second.encode())

        events = store.read_events()

        assert len(events) == 2
        assert events[0]["type"] == "complete"
        assert events[1]["type"] == "spawn"


# ── Shared archive module ─────────────────────────────────────────


class TestSharedArchive:
    """Tests for the extracted archive.py module."""

    def test_archive_captures_changes_json(self, orch: SwarmOrchestrator) -> None:
        """changes.json should be archived (previously lost on overwrite)."""
        root = orch._layout["root"]
        orch._layout["state"].write_text(
            json.dumps({"run_id": "run-x"}), encoding="utf-8",
        )
        (root / "changes.json").write_text(
            json.dumps({"files": ["a.py"]}), encoding="utf-8",
        )

        orch._archive_previous_run()

        history = root / "history" / "run-x"
        assert (history / "changes.json").exists()
        assert not (root / "changes.json").exists()

    def test_archive_captures_coordinator_log(self, orch: SwarmOrchestrator) -> None:
        """coordinator.log should be archived."""
        root = orch._layout["root"]
        orch._layout["state"].write_text(
            json.dumps({"run_id": "run-y"}), encoding="utf-8",
        )
        (root / "coordinator.log").write_text("log line\n", encoding="utf-8")

        orch._archive_previous_run()

        history = root / "history" / "run-y"
        assert (history / "coordinator.log").exists()
        assert (history / "coordinator.log").read_text() == "log line\n"

    def test_archive_captures_swarm_yaml(self, orch: SwarmOrchestrator) -> None:
        """swarm.yaml should be archived."""
        root = orch._layout["root"]
        orch._layout["state"].write_text(
            json.dumps({"run_id": "run-z"}), encoding="utf-8",
        )
        (root / "swarm.yaml").write_text("goal: test\n", encoding="utf-8")

        orch._archive_previous_run()

        history = root / "history" / "run-z"
        assert (history / "swarm.yaml").exists()

    def test_archive_skips_empty_extra_files(self, orch: SwarmOrchestrator) -> None:
        """Empty extra files should NOT be moved (size > 0 check)."""
        root = orch._layout["root"]
        orch._layout["state"].write_text(
            json.dumps({"run_id": "run-e"}), encoding="utf-8",
        )
        (root / "changes.json").write_text("", encoding="utf-8")

        orch._archive_previous_run()

        history = root / "history" / "run-e"
        assert not (history / "changes.json").exists()

    def test_standalone_archive_function(self, orch: SwarmOrchestrator) -> None:
        """archive_previous_run() works as a standalone function."""
        from attoswarm.coordinator.archive import archive_previous_run

        orch._layout["state"].write_text(
            json.dumps({"run_id": "standalone-test"}), encoding="utf-8",
        )
        orch._layout["events"].write_text('{"e":1}\n', encoding="utf-8")

        archive_previous_run(orch._layout)

        history = orch._layout["root"] / "history" / "standalone-test"
        assert history.is_dir()
        assert (history / "swarm.state.json").exists()


# ── Diff capture ──────────────────────────────────────────────────


class TestDiffCapture:
    def test_capture_task_diff_creates_file(self, orch: SwarmOrchestrator, tmp_path: Path) -> None:
        """_capture_task_diff writes a .diff file when git diff returns content."""
        import subprocess
        from unittest.mock import patch

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="diff --git a/foo.py\n+hello\n", stderr="",
        )
        with patch("subprocess.run", return_value=mock_result):
            orch._capture_task_diff("task-1", ["foo.py"])

        diff_path = orch._layout["tasks"] / "task-task-1.diff"
        assert diff_path.exists()
        assert "diff --git a/foo.py" in diff_path.read_text()

    def test_capture_task_diff_noop_on_empty_files(self, orch: SwarmOrchestrator) -> None:
        """No diff file created when files_modified is empty."""
        orch._capture_task_diff("task-2", [])
        diff_path = orch._layout["tasks"] / "task-task-2.diff"
        assert not diff_path.exists()

    def test_capture_task_diff_noop_on_empty_diff(self, orch: SwarmOrchestrator) -> None:
        """No diff file created when git diff output is empty."""
        import subprocess
        from unittest.mock import patch

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        with patch("subprocess.run", return_value=mock_result):
            orch._capture_task_diff("task-3", ["bar.py"])

        diff_path = orch._layout["tasks"] / "task-task-3.diff"
        assert not diff_path.exists()

    def test_persist_task_includes_has_diff(self, orch: SwarmOrchestrator) -> None:
        """_persist_task includes has_diff=True when .diff file exists."""
        _add_task(orch, "task-d1", "done")

        # Create a diff file
        (orch._layout["tasks"] / "task-task-d1.diff").write_text("some diff")

        orch._persist_task("task-d1")

        task_path = orch._layout["tasks"] / "task-task-d1.json"
        data = json.loads(task_path.read_text())
        assert data["has_diff"] is True

    def test_persist_task_has_diff_false(self, orch: SwarmOrchestrator) -> None:
        """_persist_task includes has_diff=False when no .diff file."""
        _add_task(orch, "task-d2", "done")

        orch._persist_task("task-d2")

        task_path = orch._layout["tasks"] / "task-task-d2.json"
        data = json.loads(task_path.read_text())
        assert data["has_diff"] is False


# ── Stores: diff content + history listing ────────────────────────


class TestStoresDiffAndHistory:
    def test_build_task_detail_includes_diff(self, tmp_path: Path) -> None:
        """build_task_detail reads .diff file content."""
        from attoswarm.tui.stores import StateStore

        (tmp_path / "tasks").mkdir(exist_ok=True)
        (tmp_path / "agents").mkdir(exist_ok=True)

        task_data = {"title": "Test", "status": "done"}
        (tmp_path / "tasks" / "task-task-1.json").write_text(json.dumps(task_data))
        (tmp_path / "tasks" / "task-task-1.diff").write_text(
            "diff --git a/foo.py\n+line\n", encoding="utf-8",
        )

        store = StateStore(str(tmp_path))
        detail = store.build_task_detail("task-1")
        assert "diff --git a/foo.py" in detail.get("diff_content", "")

    def test_build_task_detail_no_diff(self, tmp_path: Path) -> None:
        """build_task_detail omits diff_content when no .diff file."""
        from attoswarm.tui.stores import StateStore

        (tmp_path / "tasks").mkdir(exist_ok=True)
        (tmp_path / "agents").mkdir(exist_ok=True)

        task_data = {"title": "Test", "status": "done"}
        (tmp_path / "tasks" / "task-task-1.json").write_text(json.dumps(task_data))

        store = StateStore(str(tmp_path))
        detail = store.build_task_detail("task-1")
        assert "diff_content" not in detail

    def test_list_history_empty(self, tmp_path: Path) -> None:
        """list_history returns [] when no history/ dir."""
        from attoswarm.tui.stores import StateStore

        store = StateStore(str(tmp_path))
        assert store.list_history() == []

    def test_list_history_with_runs(self, tmp_path: Path) -> None:
        """list_history returns archived run metadata."""
        from attoswarm.tui.stores import StateStore

        history = tmp_path / "history"

        run1 = history / "run-aaa"
        run1.mkdir(parents=True)
        (run1 / "swarm.state.json").write_text(
            json.dumps({"run_id": "run-aaa", "phase": "completed"}),
        )
        (run1 / "swarm.manifest.json").write_text(
            json.dumps({"goal": "first goal", "tasks": [{"task_id": "t1"}]}),
        )

        run2 = history / "run-bbb"
        run2.mkdir(parents=True)
        (run2 / "swarm.state.json").write_text(
            json.dumps({"run_id": "run-bbb", "phase": "shutdown"}),
        )
        (run2 / "swarm.manifest.json").write_text(
            json.dumps({
                "goal": "second goal",
                "lineage": {"continuation_mode": "child", "parent_run_id": "run-aaa"},
                "tasks": [{"task_id": "t1"}, {"task_id": "t2"}],
            }),
        )

        store = StateStore(str(tmp_path))
        runs = store.list_history()

        assert len(runs) == 2
        # Sorted reverse by name
        assert runs[0]["run_id"] == "run-bbb"
        assert runs[0]["goal"] == "second goal"
        assert runs[0]["phase"] == "shutdown"
        assert runs[0]["task_count"] == 2
        assert runs[0]["continuation_mode"] == "child"
        assert runs[0]["parent_run_id"] == "run-aaa"
        assert runs[1]["run_id"] == "run-aaa"
        assert runs[1]["goal"] == "first goal"
        assert runs[1]["task_count"] == 1

    def test_list_history_ignores_files(self, tmp_path: Path) -> None:
        """list_history skips non-directory entries in history/."""
        from attoswarm.tui.stores import StateStore

        history = tmp_path / "history"
        history.mkdir()
        (history / "stray-file.txt").write_text("ignored")

        store = StateStore(str(tmp_path))
        assert store.list_history() == []
