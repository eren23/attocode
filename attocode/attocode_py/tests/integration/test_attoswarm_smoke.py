"""Integration smoke tests for attoswarm with deterministic fake workers."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
import yaml

from attoswarm.config.loader import load_swarm_yaml
from attoswarm.coordinator.loop import HybridCoordinator
from attoswarm.protocol.io import read_json


def _write_fake_worker(path: Path) -> None:
    path.write_text(
        """
import json
import sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    print(json.dumps({"event": "progress", "message": "working"}), flush=True)
    print(json.dumps({"event": "task_done", "message": "done", "token_usage": {"total": 17}, "cost_usd": 0.002}), flush=True)
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_config(path: Path, run_dir: Path, worker_roles: list[dict], merge: dict | None = None) -> None:
    cfg = {
        "version": 1,
        "run": {
            "working_dir": str(run_dir),
            "run_dir": str(run_dir / "swarm"),
            "poll_interval_ms": 50,
            "max_runtime_seconds": 25,
        },
        "roles": worker_roles,
        "budget": {"max_tokens": 100000, "max_cost_usd": 10, "reserve_ratio": 0.15, "chars_per_token_fallback": 4.0},
        "merge": merge or {"authority_role": "merger", "judge_roles": [], "quality_threshold": 0.5},
        "retries": {"max_task_attempts": 2},
        "watchdog": {"heartbeat_timeout_seconds": 10},
    }
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_claude_smoke_fake_worker(tmp_path: Path) -> None:
    worker = tmp_path / "fake_worker.py"
    _write_fake_worker(worker)

    config_path = tmp_path / "swarm.yaml"
    _write_config(
        config_path,
        tmp_path,
        worker_roles=[
            {
                "role_id": "impl",
                "role_type": "worker",
                "backend": "claude",
                "model": "fake",
                "count": 2,
                "write_access": True,
                "workspace_mode": "shared_ro",
                "task_kinds": ["implement"],
                "command": [sys.executable, str(worker)],
            },
            {
                "role_id": "merger",
                "role_type": "merger",
                "backend": "claude",
                "model": "fake",
                "count": 1,
                "write_access": True,
                "workspace_mode": "shared_ro",
                "task_kinds": ["merge"],
                "command": [sys.executable, str(worker)],
            },
        ],
    )

    cfg = load_swarm_yaml(config_path)
    code = await HybridCoordinator(cfg, "Create swarm_smoke/hello.txt and report complete").run()
    assert code == 0

    state = read_json(Path(cfg.run.run_dir) / "swarm.state.json", default={})
    assert state.get("phase") == "completed"
    nodes = state.get("dag", {}).get("nodes", [])
    assert any(n.get("task_id") == "t0" and n.get("status") == "done" for n in nodes)
    assert any(str(n.get("task_id", "")).startswith("merge-") for n in nodes)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_claude_codex_smoke_fake_worker(tmp_path: Path) -> None:
    worker = tmp_path / "fake_worker.py"
    _write_fake_worker(worker)

    config_path = tmp_path / "swarm.yaml"
    _write_config(
        config_path,
        tmp_path,
        worker_roles=[
            {
                "role_id": "impl",
                "role_type": "worker",
                "backend": "claude",
                "model": "fake",
                "count": 1,
                "write_access": True,
                "workspace_mode": "shared_ro",
                "task_kinds": ["implement"],
                "command": [sys.executable, str(worker)],
            },
            {
                "role_id": "merger",
                "role_type": "merger",
                "backend": "codex",
                "model": "fake",
                "count": 1,
                "write_access": True,
                "workspace_mode": "shared_ro",
                "task_kinds": ["merge"],
                "command": [sys.executable, str(worker)],
            },
        ],
    )

    cfg = load_swarm_yaml(config_path)
    code = await HybridCoordinator(cfg, "Write swarm_smoke/mixed.txt with one line").run()
    assert code == 0

    state = read_json(Path(cfg.run.run_dir) / "swarm.state.json", default={})
    backends = {a.get("backend") for a in state.get("active_agents", [])}
    assert {"claude", "codex"}.issubset(backends)
    assert state.get("budget", {}).get("tokens_used", 0) > 0
