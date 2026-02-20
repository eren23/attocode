"""Tests for TUI widgets."""

from __future__ import annotations

import pytest

from attocode.tui.widgets.tool_calls import ToolCallInfo, ToolCallsPanel, _truncate
from attocode.tui.widgets.agents_panel import ActiveAgentInfo, AgentsPanel
from attocode.tui.widgets.status_bar import StatusBar
from attocode.types.agent import AgentPlan, PlanTask, TaskStatus


class TestToolCallInfo:
    def test_defaults(self) -> None:
        info = ToolCallInfo(tool_id="t1", name="read_file")
        assert info.status == "running"
        assert info.args == {}
        assert info.result is None

    def test_with_args(self) -> None:
        info = ToolCallInfo(
            tool_id="t1",
            name="bash",
            args={"command": "ls -la"},
            status="completed",
            result="total 42",
        )
        assert info.args["command"] == "ls -la"
        assert info.result == "total 42"


class TestTruncate:
    def test_short_string(self) -> None:
        assert _truncate("hello", 10) == "hello"

    def test_exact_length(self) -> None:
        assert _truncate("hello", 5) == "hello"

    def test_long_string(self) -> None:
        result = _truncate("hello world", 8)
        assert len(result) == 8
        assert result.endswith("\u2026")

    def test_empty(self) -> None:
        assert _truncate("", 5) == ""


class TestActiveAgentInfo:
    def test_defaults(self) -> None:
        info = ActiveAgentInfo(agent_id="a1", task="Build API")
        assert info.status == "running"
        assert info.tokens == 0

    def test_with_metrics(self) -> None:
        info = ActiveAgentInfo(
            agent_id="a1",
            task="Build API",
            tokens=5000,
            elapsed_s=30.0,
            iteration=3,
        )
        assert info.tokens == 5000
        assert info.iteration == 3


class TestPlanTask:
    def test_plan_progress(self) -> None:
        plan = AgentPlan(
            goal="Build feature",
            tasks=[
                PlanTask(id="1", description="Step 1", status=TaskStatus.COMPLETED),
                PlanTask(id="2", description="Step 2", status=TaskStatus.IN_PROGRESS),
                PlanTask(id="3", description="Step 3"),
            ],
        )
        assert plan.progress == pytest.approx(1 / 3)
        assert not plan.is_complete
        assert plan.current_task is not None
        assert plan.current_task.id == "2"

    def test_plan_all_complete(self) -> None:
        plan = AgentPlan(
            goal="Done",
            tasks=[
                PlanTask(id="1", description="Step 1", status=TaskStatus.COMPLETED),
            ],
        )
        assert plan.is_complete
        assert plan.progress == 1.0

    def test_plan_empty(self) -> None:
        plan = AgentPlan(goal="Empty")
        assert plan.is_complete
        assert plan.progress == 1.0
        assert plan.current_task is None
