"""Tests for HybridCoordinator._default_command, _build_heartbeat_script, _build_task_prompt, decomposition, and review skip."""

from __future__ import annotations

from dataclasses import replace

import pytest

from attoswarm.config.schema import OrchestrationConfig, RoleConfig, SwarmYamlConfig
from attoswarm.coordinator.loop import SKIP_REVIEW_KINDS, HybridCoordinator
from attoswarm.protocol.models import TaskSpec


def _make_coordinator(**overrides: object) -> HybridCoordinator:
    config = SwarmYamlConfig()
    if "orchestration" in overrides:
        config = replace(config, orchestration=overrides["orchestration"])  # type: ignore[arg-type]
    if "roles" in overrides:
        config = replace(config, roles=overrides["roles"])  # type: ignore[arg-type]
    return HybridCoordinator(config, goal="Build a widget")


# ---------------------------------------------------------------------------
# _build_heartbeat_script
# ---------------------------------------------------------------------------


def test_heartbeat_script_contains_heartbeat_loop() -> None:
    script = HybridCoordinator._build_heartbeat_script("echo hi")
    assert "[HEARTBEAT]" in script
    assert "sleep 5" in script


def test_heartbeat_script_emits_startup_heartbeat() -> None:
    script = HybridCoordinator._build_heartbeat_script("echo hi")
    # The script should start with an immediate heartbeat before the read loop
    assert script.startswith('echo "[HEARTBEAT]"')


def test_heartbeat_script_debug_emits_startup_heartbeat() -> None:
    script = HybridCoordinator._build_heartbeat_script("echo hi", debug=True)
    assert script.startswith('echo "[HEARTBEAT]"')
    assert "[DEBUG:STDIN_READ]" in script
    assert "[DEBUG:CMD_START]" in script
    assert "[DEBUG:CMD_EXIT]" in script


def test_heartbeat_script_contains_stdin_isolation() -> None:
    script = HybridCoordinator._build_heartbeat_script("echo hi")
    assert "< /dev/null" in script


def test_heartbeat_script_emits_done_and_failed() -> None:
    script = HybridCoordinator._build_heartbeat_script("echo hi")
    assert "[TASK_DONE]" in script
    assert "[TASK_FAILED]" in script


def test_heartbeat_script_kills_background_process() -> None:
    script = HybridCoordinator._build_heartbeat_script("echo hi")
    assert "kill $_hb" in script


# ---------------------------------------------------------------------------
# _default_command — heartbeat wrapper applied to all backends
# ---------------------------------------------------------------------------


def test_default_command_uses_plain_sh_not_login_shell() -> None:
    coord = _make_coordinator()
    for backend in ("claude", "codex", "aider", "attocode"):
        cmd = coord._default_command(backend, "m")
        assert cmd[0] == "sh", f"{backend}: expected sh"
        assert cmd[1] == "-c", f"{backend}: expected -c, got {cmd[1]}"
        assert "-l" not in cmd, f"{backend}: should not use login shell"


def test_claude_command_has_heartbeat_and_stdin_isolation() -> None:
    coord = _make_coordinator()
    cmd = coord._default_command("claude", "some-model")
    script = cmd[-1]
    assert "[HEARTBEAT]" in script
    assert "< /dev/null" in script
    assert "claude -p" in script


def test_codex_command_has_heartbeat_and_stdin_isolation() -> None:
    coord = _make_coordinator()
    cmd = coord._default_command("codex", "some-model")
    script = cmd[-1]
    assert "[HEARTBEAT]" in script
    assert "< /dev/null" in script
    assert "codex exec" in script


def test_aider_command_has_heartbeat_and_stdin_isolation() -> None:
    coord = _make_coordinator()
    cmd = coord._default_command("aider", "some-model")
    script = cmd[-1]
    assert "[HEARTBEAT]" in script
    assert "< /dev/null" in script
    assert "aider" in script


def test_attocode_command_has_heartbeat_and_stdin_isolation() -> None:
    coord = _make_coordinator()
    cmd = coord._default_command("attocode", "some-model")
    script = cmd[-1]
    assert "[HEARTBEAT]" in script
    assert "< /dev/null" in script
    assert "attocode" in script


# ---------------------------------------------------------------------------
# _default_command — model flag is optional
# ---------------------------------------------------------------------------


def test_model_flag_included_when_model_set() -> None:
    coord = _make_coordinator()
    cmd = coord._default_command("claude", "claude-sonnet-4-20250514")
    script = cmd[-1]
    assert "--model" in script
    assert "claude-sonnet-4-20250514" in script


def test_model_flag_omitted_when_model_empty() -> None:
    coord = _make_coordinator()
    cmd = coord._default_command("claude", "")
    script = cmd[-1]
    assert "--model" not in script


def test_codex_model_flag_omitted_when_empty() -> None:
    coord = _make_coordinator()
    cmd = coord._default_command("codex", "")
    script = cmd[-1]
    assert "--model" not in script


def test_aider_model_flag_omitted_when_empty() -> None:
    coord = _make_coordinator()
    cmd = coord._default_command("aider", "")
    script = cmd[-1]
    assert "--model" not in script


def test_attocode_model_flag_omitted_when_empty() -> None:
    coord = _make_coordinator()
    cmd = coord._default_command("attocode", "")
    script = cmd[-1]
    assert "--model" not in script


# ---------------------------------------------------------------------------
# _default_command — unsupported backend raises
# ---------------------------------------------------------------------------


def test_unsupported_backend_raises() -> None:
    coord = _make_coordinator()
    try:
        coord._default_command("unknown", "m")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "unknown" in str(exc)


# ---------------------------------------------------------------------------
# Fast decomposition mode
# ---------------------------------------------------------------------------


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


def test_fast_mode_creates_implement_and_integrate() -> None:
    coord = _make_coordinator(
        orchestration=OrchestrationConfig(decomposition="fast"),
        roles=[_worker_role(count=1)],
    )
    from attoswarm.protocol.models import RoleSpec

    roles = [
        RoleSpec(role_id="dev", role_type="worker", backend="claude", model="", count=1, write_access=True)
    ]
    tasks = coord._decompose_initial_tasks(roles)
    assert len(tasks) == 2  # implement + integrate (no test task with 1 worker)
    assert tasks[0].task_kind == "implement"
    assert tasks[0].status == "ready"
    assert tasks[0].description == "Build a widget"
    assert tasks[1].task_kind == "integrate"
    assert tasks[1].deps == ["t0"]


def test_fast_mode_adds_test_task_when_multiple_workers() -> None:
    coord = _make_coordinator(
        orchestration=OrchestrationConfig(decomposition="fast"),
        roles=[_worker_role(count=2)],
    )
    from attoswarm.protocol.models import RoleSpec

    roles = [
        RoleSpec(role_id="dev", role_type="worker", backend="claude", model="", count=2, write_access=True)
    ]
    tasks = coord._decompose_initial_tasks(roles)
    assert len(tasks) == 3  # implement + test + integrate
    assert tasks[0].task_kind == "implement"
    assert tasks[1].task_kind == "test"
    assert tasks[1].deps == ["t0"]
    assert tasks[2].task_kind == "integrate"
    assert set(tasks[2].deps) == {"t0", "t1"}


def test_fast_mode_first_task_is_ready() -> None:
    coord = _make_coordinator(
        orchestration=OrchestrationConfig(decomposition="fast"),
        roles=[_worker_role(count=1)],
    )
    from attoswarm.protocol.models import RoleSpec

    roles = [
        RoleSpec(role_id="dev", role_type="worker", backend="claude", model="", count=1, write_access=True)
    ]
    tasks = coord._decompose_initial_tasks(roles)
    assert tasks[0].status == "ready"
    assert coord.task_state.get("t0") == "ready"


def test_fast_mode_respects_max_tasks() -> None:
    coord = _make_coordinator(
        orchestration=OrchestrationConfig(decomposition="fast", max_tasks=1),
        roles=[_worker_role(count=2)],
    )
    from attoswarm.protocol.models import RoleSpec

    roles = [
        RoleSpec(role_id="dev", role_type="worker", backend="claude", model="", count=2, write_access=True)
    ]
    tasks = coord._decompose_initial_tasks(roles)
    assert len(tasks) == 1


# ---------------------------------------------------------------------------
# SKIP_REVIEW_KINDS — analysis and design skip the review queue
# ---------------------------------------------------------------------------


def test_skip_review_kinds_includes_analysis_and_design() -> None:
    assert "analysis" in SKIP_REVIEW_KINDS
    assert "design" in SKIP_REVIEW_KINDS
    assert "judge" in SKIP_REVIEW_KINDS
    assert "critic" in SKIP_REVIEW_KINDS
    assert "merge" in SKIP_REVIEW_KINDS


def test_skip_review_kinds_excludes_implement() -> None:
    assert "implement" not in SKIP_REVIEW_KINDS
    assert "test" not in SKIP_REVIEW_KINDS
    assert "integrate" not in SKIP_REVIEW_KINDS


# ---------------------------------------------------------------------------
# _build_task_prompt — coding context and no protocol markers
# ---------------------------------------------------------------------------


def _make_task(task_kind: str = "implement", **kwargs: object) -> TaskSpec:
    defaults: dict = {
        "task_id": "t0",
        "title": "Do something",
        "description": "Build a REST API endpoint",
        "task_kind": task_kind,
    }
    defaults.update(kwargs)
    return TaskSpec(**defaults)  # type: ignore[arg-type]


class TestBuildTaskPrompt:
    """Tests for _build_task_prompt across all task kinds."""

    def test_no_protocol_markers(self) -> None:
        coord = _make_coordinator()
        for kind in ("implement", "test", "integrate", "analysis", "design", "judge", "critic", "merge"):
            prompt = coord._build_task_prompt(_make_task(task_kind=kind))
            assert "[TASK_DONE]" not in prompt, f"{kind}: should not contain [TASK_DONE]"
            assert "[TASK_FAILED]" not in prompt, f"{kind}: should not contain [TASK_FAILED]"

    def test_implement_has_coding_instructions(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task(task_kind="implement"))
        assert "coding agent" in prompt.lower() or "create or modify" in prompt.lower()
        assert "Build a REST API endpoint" in prompt

    def test_test_has_coding_instructions(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task(task_kind="test"))
        assert "create or modify" in prompt.lower()

    def test_integrate_has_coding_instructions(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task(task_kind="integrate"))
        assert "create or modify" in prompt.lower()

    def test_analysis_has_plan_instructions(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task(task_kind="analysis"))
        assert "analyze" in prompt.lower()
        assert "plan" in prompt.lower() or "analysis" in prompt.lower()

    def test_design_has_plan_instructions(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task(task_kind="design"))
        assert "analyze" in prompt.lower()

    def test_judge_has_evaluation_instructions(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task(task_kind="judge"))
        assert "evaluate" in prompt.lower()

    def test_critic_has_evaluation_instructions(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task(task_kind="critic"))
        assert "evaluate" in prompt.lower()

    def test_includes_goal_context(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task())
        assert "Build a widget" in prompt  # goal from _make_coordinator

    def test_includes_task_id_and_title(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task(task_id="t42", title="Add auth"))
        assert "t42" in prompt
        assert "Add auth" in prompt

    def test_includes_acceptance_criteria(self) -> None:
        coord = _make_coordinator()
        task = _make_task(acceptance=["Tests pass", "No regressions"])
        prompt = coord._build_task_prompt(task)
        assert "Tests pass" in prompt
        assert "No regressions" in prompt

    def test_unknown_kind_uses_fallback(self) -> None:
        coord = _make_coordinator()
        prompt = coord._build_task_prompt(_make_task(task_kind="merge"))
        assert "working directory" in prompt.lower()
        assert "[TASK_DONE]" not in prompt

    def test_newlines_in_description_are_flattened(self) -> None:
        coord = _make_coordinator()
        task = _make_task(description="Line one\nLine two\nLine three")
        prompt = coord._build_task_prompt(task)
        assert "Line one Line two Line three" in prompt
