"""Tests for TUI events."""

from __future__ import annotations

from attocode.tui.events import (
    AgentCompleted,
    AgentStarted,
    ApprovalRequired,
    BudgetWarning,
    IterationUpdate,
    LLMCompleted,
    LLMStarted,
    StatusUpdate,
    ToolCompleted,
    ToolStarted,
)


class TestEvents:
    def test_agent_started(self) -> None:
        event = AgentStarted()
        assert isinstance(event, AgentStarted)

    def test_agent_completed_success(self) -> None:
        event = AgentCompleted(success=True, response="Done")
        assert event.success is True
        assert event.response == "Done"
        assert event.error is None

    def test_agent_completed_failure(self) -> None:
        event = AgentCompleted(success=False, response="", error="Boom")
        assert event.success is False
        assert event.error == "Boom"

    def test_tool_started(self) -> None:
        event = ToolStarted(tool_id="t1", name="read_file", args={"path": "x.py"})
        assert event.tool_id == "t1"
        assert event.name == "read_file"
        assert event.args == {"path": "x.py"}

    def test_tool_started_no_args(self) -> None:
        event = ToolStarted(tool_id="t2", name="list_files")
        assert event.args == {}

    def test_tool_completed(self) -> None:
        event = ToolCompleted(tool_id="t1", name="read_file", result="contents")
        assert event.result == "contents"
        assert event.error is None

    def test_tool_completed_error(self) -> None:
        event = ToolCompleted(tool_id="t1", name="bash", error="command failed")
        assert event.error == "command failed"

    def test_llm_started(self) -> None:
        event = LLMStarted()
        assert isinstance(event, LLMStarted)

    def test_llm_completed(self) -> None:
        event = LLMCompleted(tokens=1000, cost=0.05)
        assert event.tokens == 1000
        assert event.cost == 0.05

    def test_budget_warning(self) -> None:
        event = BudgetWarning(usage_fraction=0.85, message="85% used")
        assert event.usage_fraction == 0.85
        assert "85%" in event.message

    def test_approval_required(self) -> None:
        event = ApprovalRequired(
            tool_name="bash",
            args={"command": "rm -rf /"},
            danger_level="critical",
        )
        assert event.tool_name == "bash"
        assert event.danger_level == "critical"

    def test_status_update(self) -> None:
        event = StatusUpdate(text="thinking", mode="info")
        assert event.text == "thinking"

    def test_iteration_update(self) -> None:
        event = IterationUpdate(iteration=5)
        assert event.iteration == 5
