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
