"""Tests for boomerang orchestrator mode."""

from __future__ import annotations

import pytest

from attocode.core.orchestrator import (
    Orchestrator,
    OrchestratorPlan,
    Subtask,
    SubtaskStatus,
)


class TestSubtask:
    def test_defaults(self) -> None:
        st = Subtask(id="t1", description="Do something")
        assert st.status == SubtaskStatus.PENDING
        assert st.mode == "code"
        assert st.depends_on == []


class TestOrchestratorPlan:
    def test_empty_plan(self) -> None:
        plan = OrchestratorPlan(task="test")
        assert plan.is_complete is True
        assert plan.progress == 0.0

    def test_progress(self) -> None:
        plan = OrchestratorPlan(
            task="test",
            subtasks=[
                Subtask(id="t1", description="a", status=SubtaskStatus.COMPLETED),
                Subtask(id="t2", description="b", status=SubtaskStatus.PENDING),
            ],
        )
        assert plan.progress == pytest.approx(0.5)

    def test_is_complete(self) -> None:
        plan = OrchestratorPlan(
            task="test",
            subtasks=[
                Subtask(id="t1", description="a", status=SubtaskStatus.COMPLETED),
                Subtask(id="t2", description="b", status=SubtaskStatus.SKIPPED),
            ],
        )
        assert plan.is_complete is True

    def test_not_complete_with_pending(self) -> None:
        plan = OrchestratorPlan(
            task="test",
            subtasks=[
                Subtask(id="t1", description="a", status=SubtaskStatus.COMPLETED),
                Subtask(id="t2", description="b", status=SubtaskStatus.PENDING),
            ],
        )
        assert plan.is_complete is False

    def test_get_ready_subtasks(self) -> None:
        plan = OrchestratorPlan(
            task="test",
            subtasks=[
                Subtask(id="t1", description="a", status=SubtaskStatus.COMPLETED),
                Subtask(id="t2", description="b", depends_on=["t1"]),
                Subtask(id="t3", description="c", depends_on=["t2"]),
            ],
        )
        ready = plan.get_ready_subtasks()
        assert len(ready) == 1
        assert ready[0].id == "t2"

    def test_get_ready_no_deps(self) -> None:
        plan = OrchestratorPlan(
            task="test",
            subtasks=[
                Subtask(id="t1", description="a"),
                Subtask(id="t2", description="b"),
            ],
        )
        ready = plan.get_ready_subtasks()
        assert len(ready) == 2

    def test_failed_count(self) -> None:
        plan = OrchestratorPlan(
            task="test",
            subtasks=[
                Subtask(id="t1", description="a", status=SubtaskStatus.FAILED),
                Subtask(id="t2", description="b", status=SubtaskStatus.COMPLETED),
            ],
        )
        assert len(plan.failed) == 1
        assert len(plan.completed) == 1


class TestOrchestrator:
    def test_create_plan(self) -> None:
        orch = Orchestrator()
        plan = orch.create_plan("Build login", [
            Subtask(id="t1", description="Analyze auth", mode="architect"),
            Subtask(id="t2", description="Implement", mode="code", depends_on=["t1"]),
        ])
        assert plan.task == "Build login"
        assert len(plan.subtasks) == 2

    def test_decomposition_prompt(self) -> None:
        orch = Orchestrator()
        prompt = orch.create_decomposition_prompt("Build auth system")
        assert "Decomposition" in prompt
        assert "Build auth system" in prompt
        assert "code" in prompt
        assert "architect" in prompt

    def test_subtask_prompt(self) -> None:
        orch = Orchestrator()
        st = Subtask(id="t1", description="Analyze auth flow", mode="architect")
        prompt = orch.create_subtask_prompt(st)
        assert "Analyze auth flow" in prompt
        assert "architect" in prompt

    def test_subtask_prompt_with_context(self) -> None:
        orch = Orchestrator()
        st = Subtask(id="t2", description="Implement endpoint", mode="code")
        prompt = orch.create_subtask_prompt(st, context_summaries=["Auth uses JWT tokens"])
        assert "JWT tokens" in prompt

    def test_record_result(self) -> None:
        orch = Orchestrator()
        orch.create_plan("task", [
            Subtask(id="t1", description="do thing"),
        ])
        result = orch.record_result("t1", success=True, summary="Done")
        assert result is not None
        assert result.status == SubtaskStatus.COMPLETED
        assert result.result_summary == "Done"

    def test_record_result_failure(self) -> None:
        orch = Orchestrator()
        orch.create_plan("task", [
            Subtask(id="t1", description="do thing"),
        ])
        result = orch.record_result("t1", success=False, error="Broke")
        assert result is not None
        assert result.status == SubtaskStatus.FAILED

    def test_record_result_unknown_id(self) -> None:
        orch = Orchestrator()
        orch.create_plan("task", [])
        assert orch.record_result("nonexistent", success=True) is None

    def test_record_result_no_plan(self) -> None:
        orch = Orchestrator()
        assert orch.record_result("t1", success=True) is None

    def test_synthesis_prompt(self) -> None:
        orch = Orchestrator()
        orch.create_plan("Build feature", [
            Subtask(id="t1", description="Analyze", status=SubtaskStatus.COMPLETED, result_summary="Found 3 files"),
            Subtask(id="t2", description="Implement", status=SubtaskStatus.COMPLETED, result_summary="Added endpoint"),
        ])
        prompt = orch.create_synthesis_prompt()
        assert "Synthesis" in prompt
        assert "Found 3 files" in prompt
        assert "Added endpoint" in prompt

    def test_get_status(self) -> None:
        orch = Orchestrator()
        orch.create_plan("task", [
            Subtask(id="t1", description="a", status=SubtaskStatus.COMPLETED),
            Subtask(id="t2", description="b"),
        ])
        status = orch.get_status()
        assert status["total_subtasks"] == 2
        assert status["completed"] == 1
        assert status["pending"] == 1
        assert status["is_complete"] is False

    def test_get_status_no_plan(self) -> None:
        orch = Orchestrator()
        assert orch.get_status()["status"] == "no_plan"
