"""Reliability tests for slash command routing and lifecycle behavior."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from attocode.agent.builder import AgentBuilder
from attocode.commands import handle_command


class _DummyApp:
    def __init__(self) -> None:
        self.cleared = False
        self.exited = False
        self.pushed = 0
        self.dashboard_toggled = 0
        self.swarm_monitor_toggled = 0
        self.tasks_toggled = 0
        self.debug_toggled = 0

    def action_clear_screen(self) -> None:
        self.cleared = True

    def exit(self) -> None:
        self.exited = True

    def push_screen(self, *args, **kwargs) -> None:
        self.pushed += 1

    def action_toggle_dashboard(self) -> None:
        self.dashboard_toggled += 1

    def action_toggle_swarm_monitor(self) -> None:
        self.swarm_monitor_toggled += 1

    def action_toggle_tasks(self) -> None:
        self.tasks_toggled += 1

    def action_toggle_debug(self) -> None:
        self.debug_toggled += 1

    def action_toggle_internals(self) -> None:
        self.debug_toggled += 1


def _extract_routed_commands() -> list[str]:
    src = Path("src/attocode/commands.py").read_text(encoding="utf-8")
    cmds: set[str] = set(re.findall(r'if cmd == "(/[^"]+)"', src))
    for match in re.findall(r"if cmd in \(([^)]*)\):", src):
        cmds.update(re.findall(r'"(/[^"]+)"', match))
    return sorted(cmds)


def _command_arg(command: str) -> str:
    args = {
        "/extend": " 1000",
        "/model": " mock-model",
        "/load": " abc123",
        "/resume": " abc123",
        "/checkpoints": " abc123",
        "/handoff": " markdown",
        "/mode": " plan",
        "/plan": " test objective",
        "/approve": " all",
        "/reject": " all",
        "/agents": " list",
        "/spawn": " write a tiny summary",
        "/find": " coder",
        "/suggest": " write tests",
        "/auto": " write tests",
        "/fork": " branch-a",
        "/switch": " main",
        "/rollback": " 1",
        "/restore": " cp-1",
        "/goals": " list",
        "/mcp": " list",
        "/skills": " list",
        "/context": " breakdown",
        "/repomap": " deps",
        "/trace": " summary",
        "/undo": " .",
        "/diff": " .",
        "/powers": " mock-model",
        "/swarm": " status",
        "/theme": " dark",
        "/config": "",
    }
    return args.get(command, "")


@pytest.mark.asyncio
async def test_command_matrix_pre_and_post_run_no_exceptions(tmp_path: Path) -> None:
    agent = (
        AgentBuilder()
        .with_provider("mock")
        .with_model("mock-model")
        .with_working_dir(str(tmp_path))
        .build()
    )
    app = _DummyApp()
    commands = _extract_routed_commands()

    for phase in ("pre", "post"):
        failures: list[tuple[str, str]] = []
        outputs: list[str] = []
        for cmd in commands:
            text = cmd + _command_arg(cmd)
            try:
                result = await handle_command(text, agent=agent, app=app)
                outputs.append(result.output)
            except Exception as exc:  # pragma: no cover - this is exactly what we guard against
                failures.append((cmd, f"{type(exc).__name__}: {exc}"))

        assert failures == []
        assert not any("/config set mode_manager" in out for out in outputs)
        assert not any("/config set file_tracking" in out for out in outputs)

        if phase == "pre":
            await agent.run("hello")


@pytest.mark.asyncio
async def test_mode_and_threads_persist_across_runs(tmp_path: Path) -> None:
    agent = (
        AgentBuilder()
        .with_provider("mock")
        .with_model("mock-model")
        .with_working_dir(str(tmp_path))
        .build()
    )
    app = _DummyApp()

    await agent.run("first")
    await handle_command("/mode plan", agent=agent, app=app)
    await handle_command("/fork branch-a", agent=agent, app=app)

    await agent.run("second")
    mode_result = await handle_command("/mode", agent=agent, app=app)
    threads_result = await handle_command("/threads", agent=agent, app=app)

    assert "Current mode: plan" in mode_result.output
    assert "branch-a" in threads_result.output


@pytest.mark.asyncio
async def test_spawn_command_no_module_not_available_error(tmp_path: Path) -> None:
    agent = (
        AgentBuilder()
        .with_provider("mock")
        .with_model("mock-model")
        .with_working_dir(str(tmp_path))
        .build()
    )
    app = _DummyApp()
    result = await handle_command("/spawn write a short status line", agent=agent, app=app)

    assert "Subagent module not available" not in result.output
    assert "Subagent completed" in result.output


def test_command_palette_entries_are_routed() -> None:
    routed = set(_extract_routed_commands())
    palette_src = Path("src/attocode/tui/widgets/command_palette.py").read_text(encoding="utf-8")
    palette = set(re.findall(r'\("(/[^"]+)"\s*,', palette_src))

    assert palette.issubset(routed)

