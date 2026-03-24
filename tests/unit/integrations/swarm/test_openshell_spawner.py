"""Tests for the OpenShell sandbox spawner (openshell_spawner)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from attocode.integrations.swarm.openshell_spawner import (
    _find_openshell_binary,
    _map_agent_type,
    _resolve_sandbox_policy,
    create_openshell_spawn_fn,
    spawn_openshell_worker,
)
from attocode.integrations.swarm.types import (
    SpawnResult,
    SwarmConfig,
    SwarmTask,
    SwarmWorkerSpec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(**overrides) -> SwarmTask:
    defaults = {"id": "task-1", "description": "Implement feature X"}
    defaults.update(overrides)
    return SwarmTask(**defaults)


def _make_worker(**overrides) -> SwarmWorkerSpec:
    defaults = {"name": "worker-1", "model": "claude-sonnet-4-20250514"}
    defaults.update(overrides)
    return SwarmWorkerSpec(**defaults)


def _make_config(**overrides) -> SwarmConfig:
    return SwarmConfig(**overrides)


# ---------------------------------------------------------------------------
# _find_openshell_binary
# ---------------------------------------------------------------------------
class TestFindOpenShellBinary:
    @patch("attocode.integrations.swarm.openshell_spawner.shutil.which")
    def test_found(self, mock_which) -> None:
        mock_which.return_value = "/usr/bin/openshell"
        assert _find_openshell_binary() == "/usr/bin/openshell"
        mock_which.assert_called_once_with("openshell")

    @patch("attocode.integrations.swarm.openshell_spawner.shutil.which")
    def test_not_found(self, mock_which) -> None:
        mock_which.return_value = None
        assert _find_openshell_binary() is None


# ---------------------------------------------------------------------------
# _resolve_sandbox_policy
# ---------------------------------------------------------------------------
class TestResolveSandboxPolicy:
    def test_swarm_only(self) -> None:
        cfg = _make_config(sandbox_policy={"version": 1, "key": "swarm"})
        result = _resolve_sandbox_policy(_make_task(), _make_worker(), cfg)
        assert result == {"version": 1, "key": "swarm"}

    def test_worker_override(self) -> None:
        cfg = _make_config(sandbox_policy={"version": 1, "key": "swarm"})
        worker = _make_worker(sandbox_policy={"key": "worker", "extra": True})
        result = _resolve_sandbox_policy(_make_task(), worker, cfg)
        assert result["key"] == "worker"
        assert result["extra"] is True
        assert result["version"] == 1

    def test_task_override(self) -> None:
        cfg = _make_config(sandbox_policy={"version": 1})
        worker = _make_worker(sandbox_policy={"key": "worker"})
        task = _make_task(sandbox_policy={"key": "task"})
        result = _resolve_sandbox_policy(task, worker, cfg)
        assert result["key"] == "task"

    def test_network_policies_concatenated(self) -> None:
        cfg = _make_config(sandbox_policy={
            "network_policies": {"pypi": {"name": "pypi"}},
        })
        worker = _make_worker(sandbox_policy={
            "network_policies": {"github": {"name": "github"}},
        })
        task = _make_task(sandbox_policy={
            "network_policies": {"npm": {"name": "npm"}},
        })
        result = _resolve_sandbox_policy(task, worker, cfg)
        np = result["network_policies"]
        assert "pypi" in np
        assert "github" in np
        assert "npm" in np

    def test_all_none(self) -> None:
        result = _resolve_sandbox_policy(_make_task(), _make_worker(), _make_config())
        assert result is None


# ---------------------------------------------------------------------------
# _map_agent_type
# ---------------------------------------------------------------------------
class TestMapAgentType:
    def test_claude_profile(self) -> None:
        assert _map_agent_type(_make_worker(policy_profile="cc")) == "claude"

    def test_opencode_profile(self) -> None:
        assert _map_agent_type(_make_worker(policy_profile="opencode")) == "opencode"

    def test_codex_profile(self) -> None:
        assert _map_agent_type(_make_worker(policy_profile="codex")) == "codex"

    def test_model_fallback_claude(self) -> None:
        assert _map_agent_type(_make_worker(model="claude-sonnet-4-20250514")) == "claude"

    def test_model_fallback_gpt(self) -> None:
        assert _map_agent_type(_make_worker(model="gpt-4o")) == "codex"

    def test_default(self) -> None:
        assert _map_agent_type(_make_worker(model="unknown-model")) == "claude"


# ---------------------------------------------------------------------------
# spawn_openshell_worker
# ---------------------------------------------------------------------------
class TestSpawnOpenShellWorker:
    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.openshell_spawner._find_openshell_binary", return_value=None)
    async def test_binary_not_found(self, _mock) -> None:
        result = await spawn_openshell_worker(
            _make_task(), _make_worker(), "system prompt",
        )
        assert result.success is False
        assert "not found" in result.output.lower()

    @pytest.mark.asyncio
    @patch("attocode.integrations.swarm.openshell_spawner._find_openshell_binary", return_value="/usr/bin/openshell")
    async def test_sandbox_creation_failure(self, _mock_find) -> None:
        with patch(
            "attocode.integrations.safety.sandbox.openshell.OpenShellSandbox.create_session",
            side_effect=Exception("gateway unreachable"),
        ), patch.object(
            __import__("attocode.integrations.safety.sandbox.openshell", fromlist=["OpenShellSandbox"]).OpenShellSandbox,
            "is_available",
            return_value=True,
        ):
            result = await spawn_openshell_worker(
                _make_task(), _make_worker(), "system prompt",
            )
            assert result.success is False
            assert "sandbox" in result.output.lower() or "gateway" in result.output.lower()


# ---------------------------------------------------------------------------
# create_openshell_spawn_fn
# ---------------------------------------------------------------------------
class TestCreateOpenShellSpawnFn:
    def test_returns_callable(self) -> None:
        fn = create_openshell_spawn_fn("/tmp/workdir")
        assert callable(fn)

    def test_with_config(self) -> None:
        cfg = _make_config(sandbox_gateway_url="remote:50051")
        fn = create_openshell_spawn_fn("/tmp/workdir", config=cfg)
        assert callable(fn)
