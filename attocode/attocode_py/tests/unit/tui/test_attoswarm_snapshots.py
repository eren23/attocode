"""Textual snapshot tests for AttoswarmApp using synthetic run directories.

Run with:
    .venv/bin/python -m pytest tests/unit/tui/test_attoswarm_snapshots.py -v

Generate/update baselines:
    .venv/bin/python -m pytest tests/unit/tui/test_attoswarm_snapshots.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.helpers.fixtures import (
    SyntheticAgent,
    SyntheticRunSpec,
    SyntheticTask,
    _build_healthy_events,
    _ts,
    create_synthetic_run,
)

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stable_app(run_dir: Path) -> "AttoswarmApp":
    """Create an AttoswarmApp subclass with deterministic output.

    Disables the clock and status log at composition time so the SVG
    content doesn't vary between runs.
    """
    from textual.app import ComposeResult
    from textual.widgets import Header

    from attoswarm.tui.app import AttoswarmApp

    class StableApp(AttoswarmApp):
        def compose(self) -> ComposeResult:
            # Override compose to match AttoswarmApp layout but with clock disabled
            from textual.containers import Horizontal, Vertical
            from textual.widgets import Footer, Header, Static

            from attocode.tui.widgets.swarm.agent_grid import AgentGrid
            from attocode.tui.widgets.swarm.task_board import TaskBoard
            from attocode.tui.widgets.swarm.dag_view import DependencyDAGView
            from attocode.tui.widgets.swarm.event_timeline import EventTimeline
            from attocode.tui.widgets.swarm.detail_inspector import DetailInspector
            from attocode.tui.widgets.swarm.file_activity_map import FileActivityMap
            from attocode.tui.screens.swarm_dashboard import SwarmStatusFooter

            yield Header(show_clock=False)
            with Vertical(id="swarm-outer"):
                yield AgentGrid(id="swarm-agent-grid")
                with Horizontal(id="swarm-middle"):
                    with Vertical(id="swarm-left"):
                        yield TaskBoard(id="swarm-task-board")
                    with Vertical(id="swarm-right"):
                        yield DependencyDAGView(id="swarm-dag-view")
                        yield DetailInspector(id="swarm-detail")
                yield EventTimeline(id="swarm-timeline")
                yield FileActivityMap(id="swarm-file-activity")
            yield SwarmStatusFooter(id="swarm-status-footer")
            yield Static("", id="status-log")
            yield Footer()

        def on_mount(self) -> None:
            # Call parent on_mount but suppress status log
            super().on_mount()
            try:
                self.query_one("#status-log", Static).update("")
            except Exception:
                pass

    return StableApp(str(run_dir))


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------


def test_snapshot_empty_init(snap_compare: "Callable", tmp_path: Path) -> None:
    """Empty/init state — no agents, no tasks, blank dashboard."""
    spec = SyntheticRunSpec(
        phase="init",
        agents=[],
        tasks=[],
        events=[],
    )
    run_dir = create_synthetic_run(tmp_path, spec)
    app = _make_stable_app(run_dir)
    assert snap_compare(app, terminal_size=(120, 30))


def test_snapshot_executing(snap_compare: "Callable", tmp_path: Path) -> None:
    """Executing state — 3 agents, 5 tasks (mix of done/running/pending)."""
    agents = [
        SyntheticAgent(agent_id="a1", role_id="coder", status="busy", task_id="t3"),
        SyntheticAgent(agent_id="a2", role_id="tester", status="busy", task_id="t4"),
        SyntheticAgent(agent_id="a3", role_id="reviewer", status="idle"),
    ]
    tasks = [
        SyntheticTask(task_id="t1", title="Setup project structure", status="done", task_kind="implement", assigned_agent_id="a1"),
        SyntheticTask(task_id="t2", title="Design API schema", status="done", task_kind="design", assigned_agent_id="a1"),
        SyntheticTask(task_id="t3", title="Implement REST endpoints", status="running", task_kind="implement", assigned_agent_id="a1", deps=["t1", "t2"]),
        SyntheticTask(task_id="t4", title="Write unit tests", status="running", task_kind="test", assigned_agent_id="a2", deps=["t3"]),
        SyntheticTask(task_id="t5", title="Integration testing", status="pending", task_kind="integrate", deps=["t3", "t4"]),
    ]
    events = _build_healthy_events("a1", [tasks[0], tasks[1]])
    events.append({
        "timestamp": _ts(50),
        "type": "task.transition",
        "payload": {"task_id": "t3", "from_state": "ready", "to_state": "running", "reason": "assigned"},
    })
    events.append({
        "timestamp": _ts(55),
        "type": "agent.event",
        "payload": {"agent_id": "a1", "task_id": "t3", "message": "Implementing REST endpoints..."},
    })

    spec = SyntheticRunSpec(
        phase="executing",
        agents=agents,
        tasks=tasks,
        events=events,
        budget_tokens_used=250_000,
    )
    run_dir = create_synthetic_run(tmp_path, spec)
    app = _make_stable_app(run_dir)
    assert snap_compare(app, terminal_size=(120, 30))


def test_snapshot_completed(snap_compare: "Callable", tmp_path: Path) -> None:
    """Completed state — all tasks done, budget summary."""
    agents = [
        SyntheticAgent(agent_id="a1", role_id="coder", status="idle"),
        SyntheticAgent(agent_id="a2", role_id="tester", status="idle"),
    ]
    tasks = [
        SyntheticTask(task_id="t1", title="Implement auth module", status="done", task_kind="implement", assigned_agent_id="a1"),
        SyntheticTask(task_id="t2", title="Write auth tests", status="done", task_kind="test", assigned_agent_id="a2", deps=["t1"]),
        SyntheticTask(task_id="t3", title="Integrate with gateway", status="done", task_kind="integrate", assigned_agent_id="a1", deps=["t2"]),
    ]
    events = _build_healthy_events("a1", [tasks[0]]) + _build_healthy_events("a2", [tasks[1]])
    events += _build_healthy_events("a1", [tasks[2]])

    spec = SyntheticRunSpec(
        phase="completed",
        agents=agents,
        tasks=tasks,
        events=events,
        budget_tokens_used=1_200_000,
        budget_cost_used=4.80,
    )
    run_dir = create_synthetic_run(tmp_path, spec)
    app = _make_stable_app(run_dir)
    assert snap_compare(app, terminal_size=(120, 30))


def test_snapshot_failed_with_errors(snap_compare: "Callable", tmp_path: Path) -> None:
    """Failed state — timeout error, failed tasks, error panel."""
    agents = [
        SyntheticAgent(agent_id="a1", role_id="coder", status="exited", exit_code=1),
    ]
    tasks = [
        SyntheticTask(task_id="t1", title="Implement feature X", status="done", task_kind="implement", assigned_agent_id="a1"),
        SyntheticTask(task_id="t2", title="Implement feature Y", status="failed", task_kind="implement", assigned_agent_id="a1", last_error="Timeout after 120s"),
        SyntheticTask(task_id="t3", title="Write tests", status="pending", task_kind="test", deps=["t1", "t2"]),
    ]
    events = _build_healthy_events("a1", [tasks[0]])
    events += [
        {"timestamp": _ts(80), "type": "task.transition", "payload": {"task_id": "t2", "from_state": "running", "to_state": "failed", "reason": "timeout"}},
    ]

    spec = SyntheticRunSpec(
        phase="failed",
        agents=agents,
        tasks=tasks,
        events=events,
        errors=[
            {"timestamp": _ts(80), "type": "agent_timeout", "message": "Agent a1 timed out on task t2 after 120s"},
            {"timestamp": _ts(81), "type": "phase_transition", "message": "Swarm failed: 1 task failed, 1 task pending"},
        ],
        budget_tokens_used=800_000,
        budget_cost_used=3.20,
    )
    run_dir = create_synthetic_run(tmp_path, spec)
    app = _make_stable_app(run_dir)
    assert snap_compare(app, terminal_size=(120, 30))


def test_snapshot_many_agents(snap_compare: "Callable", tmp_path: Path) -> None:
    """Many agents — 6 agents, 7 tasks, table overflow."""
    agents = [
        SyntheticAgent(agent_id=f"a{i}", role_id=role, status="busy" if i < 4 else "idle", task_id=f"t{i}" if i < 4 else None)
        for i, role in enumerate(["coder", "coder", "tester", "reviewer", "merger", "researcher"], start=1)
    ]
    tasks = [
        SyntheticTask(task_id="t1", title="Setup foundation", status="done", task_kind="implement", assigned_agent_id="a1"),
        SyntheticTask(task_id="t2", title="Build auth layer", status="running", task_kind="implement", assigned_agent_id="a2"),
        SyntheticTask(task_id="t3", title="Write auth tests", status="running", task_kind="test", assigned_agent_id="a3"),
        SyntheticTask(task_id="t4", title="Review auth code", status="running", task_kind="design", assigned_agent_id="a4"),
        SyntheticTask(task_id="t5", title="Build API gateway", status="pending", task_kind="implement", deps=["t2"]),
        SyntheticTask(task_id="t6", title="E2E integration", status="pending", task_kind="integrate", deps=["t2", "t3"]),
        SyntheticTask(task_id="t7", title="Performance benchmark", status="pending", task_kind="test", deps=["t5", "t6"]),
    ]
    events = _build_healthy_events("a1", [tasks[0]])
    events += [
        {"timestamp": _ts(40), "type": "task.transition", "payload": {"task_id": "t2", "from_state": "ready", "to_state": "running", "reason": "assigned"}},
        {"timestamp": _ts(42), "type": "task.transition", "payload": {"task_id": "t3", "from_state": "ready", "to_state": "running", "reason": "assigned"}},
        {"timestamp": _ts(44), "type": "task.transition", "payload": {"task_id": "t4", "from_state": "ready", "to_state": "running", "reason": "assigned"}},
        {"timestamp": _ts(50), "type": "agent.event", "payload": {"agent_id": "a2", "task_id": "t2", "message": "Building auth layer..."}},
        {"timestamp": _ts(52), "type": "agent.event", "payload": {"agent_id": "a3", "task_id": "t3", "message": "Writing test cases..."}},
    ]

    spec = SyntheticRunSpec(
        phase="executing",
        agents=agents,
        tasks=tasks,
        events=events,
        budget_tokens_used=500_000,
        budget_cost_used=2.00,
    )
    run_dir = create_synthetic_run(tmp_path, spec)
    app = _make_stable_app(run_dir)
    assert snap_compare(app, terminal_size=(120, 40))
