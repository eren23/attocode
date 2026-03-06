"""Opt-in live smoke tests for real claude/codex binaries."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
import yaml

from attoswarm.config.loader import load_swarm_yaml
from attoswarm.coordinator.loop import HybridCoordinator
from attoswarm.protocol.io import read_json


LIVE_FLAG = os.getenv("ATTO_LIVE_SWARM") == "1"


def _require_live(binary_names: list[str]) -> None:
    if not LIVE_FLAG:
        pytest.skip("Set ATTO_LIVE_SWARM=1 to run live swarm smoke tests")
    for b in binary_names:
        if shutil.which(b) is None:
            pytest.skip(f"Missing binary: {b}")


def _write_live_config(path: Path, run_dir: Path, roles: list[dict]) -> None:
    cfg = {
        "version": 1,
        "run": {
            "working_dir": str(run_dir),
            "run_dir": str(run_dir / "swarm-live"),
            "poll_interval_ms": 250,
            "max_runtime_seconds": 40,
        },
        "roles": roles,
        "budget": {"max_tokens": 20000, "max_cost_usd": 2.0, "reserve_ratio": 0.1, "chars_per_token_fallback": 4.0},
        "merge": {"authority_role": "merger", "judge_roles": [], "quality_threshold": 0.5},
        "watchdog": {"heartbeat_timeout_seconds": 20},
        "retries": {"max_task_attempts": 1},
    }
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")


@pytest.mark.live_swarm
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_two_claude_smoke(tmp_path: Path) -> None:
    _require_live(["claude"])

    config_path = tmp_path / "swarm.yaml"
    _write_live_config(
        config_path,
        tmp_path,
        roles=[
            {"role_id": "impl", "role_type": "worker", "backend": "claude", "model": "claude-sonnet-4-20250514", "count": 2, "task_kinds": ["implement"]},
            {"role_id": "merger", "role_type": "merger", "backend": "claude", "model": "claude-sonnet-4-20250514", "count": 1, "task_kinds": ["merge"]},
        ],
    )

    cfg = load_swarm_yaml(config_path)
    await HybridCoordinator(cfg, "Create file swarm_smoke/live_cc.txt and include one line.").run()

    state = read_json(Path(cfg.run.run_dir) / "swarm.state.json", default={})
    assert state.get("phase") in {"completed", "failed"}
    assert state.get("active_agents")


@pytest.mark.live_swarm
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_claude_codex_smoke(tmp_path: Path) -> None:
    _require_live(["claude", "codex"])

    config_path = tmp_path / "swarm.yaml"
    _write_live_config(
        config_path,
        tmp_path,
        roles=[
            {"role_id": "impl", "role_type": "worker", "backend": "claude", "model": "claude-sonnet-4-20250514", "count": 1, "task_kinds": ["implement"]},
            {"role_id": "merger", "role_type": "merger", "backend": "codex", "model": "o3", "count": 1, "task_kinds": ["merge"]},
        ],
    )

    cfg = load_swarm_yaml(config_path)
    await HybridCoordinator(cfg, "Create file swarm_smoke/live_cc_codex.txt and include one line.").run()

    state = read_json(Path(cfg.run.run_dir) / "swarm.state.json", default={})
    assert state.get("phase") in {"completed", "failed"}
    backends = {a.get("backend") for a in state.get("active_agents", [])}
    assert {"claude", "codex"}.issubset(backends)
