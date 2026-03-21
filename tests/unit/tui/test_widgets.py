"""Tests for TUI widgets."""

from __future__ import annotations

import pytest

from attocode.types.agent import AgentPlan, PlanTask, TaskStatus
from attocode.tui.widgets.agents_panel import ActiveAgentInfo
from attocode.tui.widgets.status_bar import StatusBar
from attocode.tui.widgets.tool_calls import ToolCallInfo, _truncate


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


class TestEventTimelineTrim:
    """EventTimeline trims events to 100."""

    def test_update_events_trims_to_100(self) -> None:
        from unittest.mock import patch

        from attocode.tui.widgets.swarm.event_timeline import EventTimeline

        with patch.object(EventTimeline, "_rebuild"):
            et = EventTimeline()
            et.update_events([{"type": f"e{i}", "data": {}} for i in range(150)])
            assert len(et.events) == 100

    def test_add_event_trims_to_100(self) -> None:
        from unittest.mock import patch

        from attocode.tui.widgets.swarm.event_timeline import EventTimeline

        with patch.object(EventTimeline, "_rebuild"):
            et = EventTimeline()
            # Pre-set to exactly 100
            et.events = [{"type": f"e{i}", "data": {}} for i in range(100)]
            et.add_event({"type": "new", "data": {}})
            assert len(et.events) == 100
            assert et.events[-1]["type"] == "new"


class TestEventsLogMaxLines:
    """EventsLog compose yields RichLog with max_lines=1000."""

    def test_compose_yields_richlog_with_max_lines(self) -> None:
        from attocode.tui.widgets.swarm.event_timeline import EventsLog

        log = EventsLog()
        children = list(log.compose())
        assert len(children) >= 1
        assert children[0].max_lines == 1000


class TestStatusBar:
    def test_line1_shows_context_and_budget_together(self) -> None:
        status = StatusBar()
        status.context_pct = 0.25
        status.budget_pct = 0.90
        status.context_tokens = 25_000
        status.context_window = 200_000
        status.total_tokens = 900_000
        status.max_tokens = 1_000_000

        line1 = status._render_line1().plain

        assert "ctx 25%" in line1
        assert "bud 90%" in line1
        assert "ctx 25,000/200,000" in line1
        assert "bud 900,000/1,000,000" in line1

    def test_line2_shows_batched_indicator(self) -> None:
        status = StatusBar()
        status.live_updates_coalesced = True

        line2 = status._render_line2().plain

        assert "batched" in line2
