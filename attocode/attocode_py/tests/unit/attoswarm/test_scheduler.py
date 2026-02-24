import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attoswarm.config.schema import SwarmYamlConfig, WatchdogConfig
from attoswarm.coordinator.loop import HybridCoordinator
from attoswarm.coordinator.scheduler import AgentSlot, assign_tasks, compute_ready_tasks
from attoswarm.protocol.models import RoleSpec, TaskSpec


def test_compute_ready_tasks_respects_dependencies() -> None:
    tasks = [
        TaskSpec(task_id="t1", title="root", description="", deps=[], status="pending"),
        TaskSpec(task_id="t2", title="dep", description="", deps=["t1"], status="pending"),
    ]
    state = {"t1": "done", "t2": "pending"}
    ready = compute_ready_tasks(tasks, state)
    assert [t.task_id for t in ready] == ["t2"]


def test_assign_tasks_role_and_kind_filtering() -> None:
    tasks = [
        TaskSpec(task_id="t1", title="impl", description="", task_kind="implement", role_hint="impl"),
        TaskSpec(task_id="t2", title="review", description="", task_kind="review", role_hint="judge"),
    ]
    free = [
        AgentSlot(agent_id="a1", role_id="impl", backend="codex", busy=False),
        AgentSlot(agent_id="a2", role_id="judge", backend="aider", busy=False),
    ]
    roles = [
        RoleSpec(role_id="impl", role_type="worker", backend="codex", model="o3", task_kinds=["implement"]),
        RoleSpec(role_id="judge", role_type="judge", backend="aider", model="sonnet", task_kinds=["review"]),
    ]
    out = assign_tasks(tasks, free, roles)
    assert {(a.task_id, a.agent_id) for a in out} == {("t1", "a1"), ("t2", "a2")}


def test_judge_critic_tasks_ready_when_dep_reviewing() -> None:
    """Judge and critic tasks should dispatch when their dependency is in 'reviewing' state."""
    tasks = [
        TaskSpec(task_id="t0", title="impl", description="", deps=[], status="reviewing"),
        TaskSpec(
            task_id="review-t0-judge",
            title="Review t0",
            description="",
            deps=["t0"],
            task_kind="judge",
            status="ready",
        ),
        TaskSpec(
            task_id="review-t0-critic",
            title="Review t0",
            description="",
            deps=["t0"],
            task_kind="critic",
            status="ready",
        ),
    ]
    state = {"t0": "reviewing", "review-t0-judge": "ready", "review-t0-critic": "ready"}
    ready = compute_ready_tasks(tasks, state)
    ids = {t.task_id for t in ready}
    assert "review-t0-judge" in ids
    assert "review-t0-critic" in ids


def test_regular_tasks_blocked_when_dep_reviewing() -> None:
    """Non-merge/judge/critic tasks should NOT be ready when dep is only 'reviewing'."""
    tasks = [
        TaskSpec(task_id="t0", title="impl", description="", deps=[], status="reviewing"),
        TaskSpec(
            task_id="t1",
            title="next step",
            description="",
            deps=["t0"],
            task_kind="implement",
            status="pending",
        ),
    ]
    state = {"t0": "reviewing", "t1": "pending"}
    ready = compute_ready_tasks(tasks, state)
    assert ready == []


def test_judge_tasks_ready_when_dep_done() -> None:
    """Judge/critic tasks should also work when dep is fully 'done'."""
    tasks = [
        TaskSpec(task_id="t0", title="impl", description="", deps=[], status="done"),
        TaskSpec(
            task_id="review-t0-judge",
            title="Review t0",
            description="",
            deps=["t0"],
            task_kind="judge",
            status="pending",
        ),
    ]
    state = {"t0": "done", "review-t0-judge": "pending"}
    ready = compute_ready_tasks(tasks, state)
    assert [t.task_id for t in ready] == ["review-t0-judge"]


# ---------------------------------------------------------------------------
# Duration enforcement tests
# ---------------------------------------------------------------------------

def _make_coordinator(task_max_duration: float = 60.0) -> HybridCoordinator:
    """Build a minimal coordinator for unit testing (no real agents)."""
    cfg = SwarmYamlConfig()
    cfg.watchdog = WatchdogConfig(
        heartbeat_timeout_seconds=45.0,
        task_silence_timeout_seconds=120.0,
        task_max_duration_seconds=task_max_duration,
    )
    coord = HybridCoordinator(cfg, goal="test", resume=False)
    # Fake manifest so assertions don't trip
    coord.manifest = MagicMock()
    coord.manifest.tasks = []
    return coord


@pytest.mark.asyncio
async def test_enforce_task_duration_limits_kills_stuck_task() -> None:
    """Task exceeding wall-clock duration limit should be failed."""
    coord = _make_coordinator(task_max_duration=60.0)
    coord.running_task_by_agent["agent-1"] = "t0"
    coord.running_task_started_at["t0"] = time.monotonic() - 120  # 120s ago, limit is 60
    coord.running_task_last_progress["t0"] = time.monotonic()  # heartbeats kept it "alive"
    coord.task_state["t0"] = "running"
    coord.task_attempts["t0"] = 1

    # Stub _handle_task_failed to record the call without side-effects
    calls: list[tuple[str, str, str]] = []

    async def fake_fail(agent_id: str, task_id: str, reason: str) -> None:
        calls.append((agent_id, task_id, reason))
        coord.running_task_by_agent.pop(agent_id, None)
        coord.running_task_started_at.pop(task_id, None)
        coord.running_task_last_progress.pop(task_id, None)

    coord._handle_task_failed = fake_fail  # type: ignore[assignment]

    await coord._enforce_task_duration_limits()

    assert len(calls) == 1
    agent_id, task_id, reason = calls[0]
    assert agent_id == "agent-1"
    assert task_id == "t0"
    assert "task_duration_exceeded" in reason


@pytest.mark.asyncio
async def test_enforce_task_duration_limits_spares_young_task() -> None:
    """Task within duration limit should not be killed."""
    coord = _make_coordinator(task_max_duration=180.0)
    coord.running_task_by_agent["agent-1"] = "t0"
    coord.running_task_started_at["t0"] = time.monotonic() - 10  # only 10s old
    coord.running_task_last_progress["t0"] = time.monotonic()
    coord.task_state["t0"] = "running"

    coord._handle_task_failed = AsyncMock()  # type: ignore[assignment]

    await coord._enforce_task_duration_limits()

    coord._handle_task_failed.assert_not_called()


@pytest.mark.asyncio
async def test_duration_limit_respects_minimum_floor() -> None:
    """Even if config says 0, floor should be 30s."""
    coord = _make_coordinator(task_max_duration=0.0)
    coord.running_task_by_agent["agent-1"] = "t0"
    coord.running_task_started_at["t0"] = time.monotonic() - 25  # 25s < 30s floor
    coord.running_task_last_progress["t0"] = time.monotonic()
    coord.task_state["t0"] = "running"

    coord._handle_task_failed = AsyncMock()  # type: ignore[assignment]

    await coord._enforce_task_duration_limits()

    coord._handle_task_failed.assert_not_called()


def test_env_sanitization_strips_claude_vars() -> None:
    """_STRIP_ENV_VARS should be excluded from agent env."""
    from attoswarm.coordinator.loop import _STRIP_ENV_VARS

    assert "CLAUDECODE" in _STRIP_ENV_VARS
    assert "CLAUDE_CODE_ENTRYPOINT" in _STRIP_ENV_VARS
    assert "CLAUDE_REPL" in _STRIP_ENV_VARS

    # Simulate the env filtering logic
    fake_env = {"PATH": "/usr/bin", "CLAUDECODE": "1", "HOME": "/home/user"}
    clean = {k: v for k, v in fake_env.items() if k not in _STRIP_ENV_VARS}
    assert "CLAUDECODE" not in clean
    assert "PATH" in clean
    assert "HOME" in clean


def test_watchdog_config_defaults() -> None:
    """Verify updated default values."""
    cfg = WatchdogConfig()
    assert cfg.task_silence_timeout_seconds == 120.0
    assert cfg.task_max_duration_seconds == 600.0


# ---------------------------------------------------------------------------
# Parallel decomposition tests
# ---------------------------------------------------------------------------


def _make_parallel_coordinator(
    worker_count: int = 2,
    *,
    has_judge: bool = False,
    has_critic: bool = False,
) -> HybridCoordinator:
    """Build a coordinator configured for parallel decomposition testing."""
    from attoswarm.config.schema import OrchestrationConfig, RoleConfig

    roles = [
        RoleConfig(
            role_id="impl",
            role_type="worker",
            backend="claude",
            model="sonnet",
            count=worker_count,
            write_access=True,
            workspace_mode="worktree",
            task_kinds=["implement", "test", "integrate"],
        ),
    ]
    if has_judge:
        roles.append(
            RoleConfig(
                role_id="judge",
                role_type="judge",
                backend="claude",
                model="sonnet",
                count=1,
                task_kinds=["judge"],
            )
        )
    if has_critic:
        roles.append(
            RoleConfig(
                role_id="critic",
                role_type="critic",
                backend="claude",
                model="sonnet",
                count=1,
                task_kinds=["critic"],
            )
        )

    cfg = SwarmYamlConfig(
        roles=roles,
        orchestration=OrchestrationConfig(decomposition="parallel", max_tasks=20),
    )
    coord = HybridCoordinator(cfg, goal="Build a calculator app", resume=False)
    coord.manifest = MagicMock()
    coord.manifest.tasks = []
    return coord


def test_parallel_decomposition_two_workers() -> None:
    """With 2 workers: 2 ready impl tasks + 1 pending integrate."""
    coord = _make_parallel_coordinator(worker_count=2)
    role_specs = [
        RoleSpec(role_id="impl", role_type="worker", backend="claude", model="sonnet", count=2),
    ]
    tasks = coord._decompose_initial_tasks(role_specs)

    # Should have 2 impl + 1 integrate = 3 tasks
    assert len(tasks) == 3
    impl_tasks = [t for t in tasks if t.task_kind in ("implement", "test")]
    integrate_tasks = [t for t in tasks if t.task_kind == "integrate"]
    assert len(impl_tasks) == 2
    assert len(integrate_tasks) == 1

    # All impl tasks start as ready with no deps
    for t in impl_tasks:
        assert t.status == "ready"
        assert t.deps == []
        assert coord.task_state[t.task_id] == "ready"

    # Integrate depends on all impl tasks
    assert set(integrate_tasks[0].deps) == {t.task_id for t in impl_tasks}
    assert integrate_tasks[0].status == "pending"


def test_parallel_decomposition_single_worker_degrades() -> None:
    """With 1 worker: degrades to single ready task."""
    coord = _make_parallel_coordinator(worker_count=1)
    role_specs = [
        RoleSpec(role_id="impl", role_type="worker", backend="claude", model="sonnet", count=1),
    ]
    tasks = coord._decompose_initial_tasks(role_specs)

    assert len(tasks) == 1
    assert tasks[0].status == "ready"
    assert tasks[0].task_kind == "implement"
    assert tasks[0].deps == []


def test_parallel_decomposition_three_workers() -> None:
    """With 3 workers: 3 ready parallel tasks + integrate."""
    coord = _make_parallel_coordinator(worker_count=3)
    role_specs = [
        RoleSpec(role_id="impl", role_type="worker", backend="claude", model="sonnet", count=3),
    ]
    tasks = coord._decompose_initial_tasks(role_specs)

    impl_tasks = [t for t in tasks if t.task_kind != "integrate"]
    integrate_tasks = [t for t in tasks if t.task_kind == "integrate"]
    assert len(impl_tasks) == 3
    assert len(integrate_tasks) == 1
    for t in impl_tasks:
        assert t.status == "ready"
        assert t.deps == []


def test_parallel_decomposition_with_judge_and_critic() -> None:
    """Judge and critic tasks appended after integrate."""
    coord = _make_parallel_coordinator(worker_count=2, has_judge=True, has_critic=True)
    role_specs = [
        RoleSpec(role_id="impl", role_type="worker", backend="claude", model="sonnet", count=2),
        RoleSpec(role_id="judge", role_type="judge", backend="claude", model="sonnet", count=1),
        RoleSpec(role_id="critic", role_type="critic", backend="claude", model="sonnet", count=1),
    ]
    tasks = coord._decompose_initial_tasks(role_specs)

    # 2 impl + 1 integrate + 1 judge + 1 critic = 5
    assert len(tasks) == 5
    kinds = [t.task_kind for t in tasks]
    assert "judge" in kinds
    assert "critic" in kinds

    integrate_task = next(t for t in tasks if t.task_kind == "integrate")
    judge_task = next(t for t in tasks if t.task_kind == "judge")
    critic_task = next(t for t in tasks if t.task_kind == "critic")

    # Judge depends on integrate
    assert integrate_task.task_id in judge_task.deps
    # Critic depends on both integrate and judge
    assert integrate_task.task_id in critic_task.deps
    assert judge_task.task_id in critic_task.deps


def test_llm_fallback_uses_parallel() -> None:
    """LLM mode without planner should fall back to parallel, not heuristic."""
    from attoswarm.config.schema import OrchestrationConfig, RoleConfig

    cfg = SwarmYamlConfig(
        roles=[
            RoleConfig(
                role_id="impl",
                role_type="worker",
                backend="claude",
                model="sonnet",
                count=2,
                write_access=True,
                task_kinds=["implement", "test", "integrate"],
            ),
        ],
        orchestration=OrchestrationConfig(decomposition="llm", max_tasks=20),
    )
    coord = HybridCoordinator(cfg, goal="Test goal", resume=False)
    coord.manifest = MagicMock()
    coord.manifest.tasks = []

    role_specs = [
        RoleSpec(role_id="impl", role_type="worker", backend="claude", model="sonnet", count=2),
    ]
    tasks = coord._decompose_initial_tasks(role_specs)

    # Should produce parallel-style tasks (2 ready impl + integrate), not heuristic pipeline
    ready_tasks = [t for t in tasks if t.status == "ready"]
    assert len(ready_tasks) == 2  # both impl tasks ready immediately
