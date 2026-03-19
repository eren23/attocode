from __future__ import annotations

import json
from pathlib import Path

from tests.helpers.fixtures import SyntheticAgent, SyntheticRunSpec, SyntheticTask, create_synthetic_run

from attoswarm.protocol.io import write_json_atomic
from attoswarm.tui.app import AttoswarmApp


def _write_state(run_dir: Path, phase: str = "executing") -> None:
    write_json_atomic(
        run_dir / "swarm.state.json",
        {
            "phase": phase,
            "dag_summary": {"pending": 1},
            "budget": {"cost_used_usd": 0.0, "cost_max_usd": 1.0},
        },
    )


def test_action_quit_detaches_without_shutdown(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    _write_state(run_dir)

    app = AttoswarmApp(str(run_dir))
    exits: list[bool] = []
    monkeypatch.setattr(app, "exit", lambda *args, **kwargs: exits.append(True))

    app.action_quit()

    assert exits == [True]
    assert app.exit_intent == "detach"
    assert not (run_dir / "control.jsonl").exists()


def test_confirmed_stop_writes_shutdown_control(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    _write_state(run_dir)

    app = AttoswarmApp(str(run_dir))
    exits: list[bool] = []
    notices: list[str] = []
    monkeypatch.setattr(app, "exit", lambda *args, **kwargs: exits.append(True))
    monkeypatch.setattr(app, "notify", lambda message, **kwargs: notices.append(str(message)))

    app._on_stop_swarm_dismiss(True)

    control_path = run_dir / "control.jsonl"
    payload = json.loads(control_path.read_text(encoding="utf-8").strip())
    assert exits == [True]
    assert app.exit_intent == "stop"
    assert payload["action"] == "shutdown"
    assert notices


def test_completion_files_modified_uses_summary_helper(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    _write_state(run_dir, phase="shutdown")

    app = AttoswarmApp(str(run_dir))
    monkeypatch.setattr("attoswarm.tui.app.collect_modified_files", lambda run_dir, state: ["a.py", "b.py"])

    assert app._completion_files_modified({"phase": "shutdown"}) == 2


def test_synthetic_run_populates_dag_summary(tmp_path: Path) -> None:
    run_dir = create_synthetic_run(
        tmp_path,
        SyntheticRunSpec(
            phase="completed",
            tasks=[
                SyntheticTask(task_id="t1", status="done"),
                SyntheticTask(task_id="t2", status="failed"),
                SyntheticTask(task_id="t3", status="pending"),
            ],
        ),
    )

    state = json.loads((run_dir / "swarm.state.json").read_text(encoding="utf-8"))

    assert state["dag_summary"] == {"pending": 1, "running": 0, "done": 1, "failed": 1, "skipped": 0}


def test_synthetic_busy_agent_normalizes_to_running(tmp_path: Path) -> None:
    run_dir = create_synthetic_run(
        tmp_path,
        SyntheticRunSpec(
            phase="executing",
            agents=[SyntheticAgent(agent_id="a1", status="busy", task_id="t1")],
            tasks=[SyntheticTask(task_id="t1", status="running", assigned_agent_id="a1")],
        ),
    )

    state = json.loads((run_dir / "swarm.state.json").read_text(encoding="utf-8"))

    assert state["active_agents"][0]["status"] == "running"
