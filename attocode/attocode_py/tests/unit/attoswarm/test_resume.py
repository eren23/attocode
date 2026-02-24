from pathlib import Path

from attoswarm.config.schema import RoleConfig, SwarmYamlConfig
from attoswarm.coordinator.loop import HybridCoordinator
from attoswarm.protocol.io import write_json_atomic


def test_load_existing_run_converts_running_to_ready(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "tasks").mkdir(parents=True)
    cfg = SwarmYamlConfig(
        roles=[RoleConfig(role_id="worker", role_type="worker", backend="claude", model="x")]
    )
    cfg.run.run_dir = str(run_dir)

    write_json_atomic(
        run_dir / "swarm.manifest.json",
        {
            "schema_version": "1.0",
            "run_id": "r1",
            "goal": "g",
            "roles": [{"role_id": "worker", "role_type": "worker", "backend": "claude", "model": "x", "count": 1}],
            "tasks": [{"task_id": "t0", "title": "t", "description": "d", "deps": [], "status": "running", "task_kind": "implement"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 2.0, "reserve_ratio": 0.1, "chars_per_token_fallback": 4.0},
            "merge_policy": {"authority_role": "merger", "quality_threshold": 0.75},
        },
    )
    write_json_atomic(run_dir / "tasks" / "task-t0.json", {"task_id": "t0", "status": "running", "attempts": 1})
    write_json_atomic(run_dir / "swarm.state.json", {"state_seq": 3, "budget": {"tokens_used": 10, "cost_used_usd": 0.1}})

    c = HybridCoordinator(cfg, "g", resume=True)
    c._ensure_layout()
    c._load_existing_run()

    assert c.task_state["t0"] == "ready"
    assert c.task_attempts["t0"] == 1
    assert c.state_seq == 3
