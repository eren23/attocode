"""Tests for the swarm quality gate — pre-flight checks, LLM judge, test-specific logic."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from attocode.integrations.swarm.quality_gate import (
    ArtifactReport,
    QualityGateConfig,
    evaluate_worker_output,
    run_pre_flight_checks,
    _build_quality_prompt,
)
from attocode.integrations.swarm.types import (
    SubtaskType,
    SwarmConfig,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str = "t1",
    task_type: SubtaskType = SubtaskType.IMPLEMENT,
    description: str = "Implement feature",
    target_files: list[str] | None = None,
    complexity: int = 5,
) -> SwarmTask:
    return SwarmTask(
        id=task_id,
        description=description,
        type=task_type,
        status=SwarmTaskStatus.DISPATCHED,
        complexity=complexity,
        target_files=target_files,
    )


def _make_result(
    success: bool = True,
    output: str = "Done.",
    tool_calls: int = 3,
    files_modified: list[str] | None = None,
    test_output: str | None = None,
) -> SwarmTaskResult:
    return SwarmTaskResult(
        success=success,
        output=output,
        tool_calls=tool_calls,
        files_modified=files_modified,
        test_output=test_output,
    )


# =============================================================================
# Pre-flight checks
# =============================================================================


class TestPreFlightChecks:
    def test_passes_for_normal_task(self) -> None:
        task = _make_task()
        result = _make_result(tool_calls=3)
        assert run_pre_flight_checks(task, result) is None

    def test_v7_rejects_zero_tool_calls_for_test_task(self) -> None:
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(tool_calls=0)
        gate_result = run_pre_flight_checks(task, result)
        assert gate_result is not None
        assert gate_result.passed is False
        assert gate_result.score == 0

    def test_v4_rejects_empty_target_files(self) -> None:
        task = _make_task(target_files=["missing.py"])
        result = _make_result()
        # Provide a report showing all empty
        report = ArtifactReport(all_empty=True, summary="ALL EMPTY")
        gate_result = run_pre_flight_checks(task, result, cached_artifacts=report)
        assert gate_result is not None
        assert gate_result.passed is False
        assert gate_result.artifact_auto_fail is True

    def test_v11_rejects_test_task_without_evidence(self) -> None:
        """Test task with tool calls but no test keywords in output → rejected."""
        config = SwarmConfig(test_require_execution_evidence=True)
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(
            tool_calls=5,
            output="I created some files and did some work.",
        )
        gate_result = run_pre_flight_checks(task, result, swarm_config=config)
        assert gate_result is not None
        assert gate_result.passed is False
        assert gate_result.score == 1
        assert "no evidence of test execution" in gate_result.feedback.lower()

    def test_v11_passes_test_task_with_evidence(self) -> None:
        """Test task with pytest keywords in output → passes pre-flight."""
        config = SwarmConfig(test_require_execution_evidence=True)
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(
            tool_calls=5,
            output="Ran pytest, 3 passed, 1 failed.",
        )
        gate_result = run_pre_flight_checks(task, result, swarm_config=config)
        assert gate_result is None  # passes

    def test_v11_passes_test_task_with_test_output_field(self) -> None:
        """Test task with test_output field populated → passes pre-flight."""
        config = SwarmConfig(test_require_execution_evidence=True)
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(
            tool_calls=5,
            output="Did some work.",  # no keywords here
            test_output="$ pytest\n3 passed",  # but test_output has evidence
        )
        gate_result = run_pre_flight_checks(task, result, swarm_config=config)
        assert gate_result is None  # passes

    def test_v11_skips_non_test_tasks(self) -> None:
        """Non-test tasks don't trigger V11 even without test keywords."""
        config = SwarmConfig(test_require_execution_evidence=True)
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        result = _make_result(
            tool_calls=5,
            output="I created some files.",
        )
        gate_result = run_pre_flight_checks(task, result, swarm_config=config)
        assert gate_result is None  # not a test task, no V11

    def test_v11_disabled_via_config(self) -> None:
        """When test_require_execution_evidence=False, V11 doesn't run."""
        config = SwarmConfig(test_require_execution_evidence=False)
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(
            tool_calls=5,
            output="I created some files.",
        )
        gate_result = run_pre_flight_checks(task, result, swarm_config=config)
        assert gate_result is None  # V11 disabled


# =============================================================================
# _build_quality_prompt
# =============================================================================


class TestBuildQualityPrompt:
    def test_test_task_uses_stricter_rubric(self) -> None:
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result()
        report = ArtifactReport(all_empty=False, summary="ok")
        prompt = _build_quality_prompt(task, result, report)
        assert "TEST task" in prompt
        assert "CRITICAL" in prompt
        assert "test execution output" in prompt.lower()

    def test_implement_task_uses_generic_rubric(self) -> None:
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        result = _make_result()
        report = ArtifactReport(all_empty=False, summary="ok")
        prompt = _build_quality_prompt(task, result, report)
        assert "TEST TASK" not in prompt
        assert "No meaningful work done" in prompt

    def test_verification_evidence_included(self) -> None:
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result()
        report = ArtifactReport(all_empty=False, summary="ok")
        evidence = {
            "passed": True,
            "checks": [
                {"name": "tests", "passed": True, "message": "3 passed"},
                {"name": "type_check", "passed": False, "message": "1 error"},
            ],
        }
        prompt = _build_quality_prompt(task, result, report, verification_evidence=evidence)
        assert "Verification Gate Results" in prompt
        assert "tests: PASS" in prompt
        assert "type_check: FAIL" in prompt

    def test_test_output_included(self) -> None:
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(test_output="$ pytest\n3 passed, 0 failed")
        report = ArtifactReport(all_empty=False, summary="ok")
        prompt = _build_quality_prompt(task, result, report)
        assert "Test Execution Output" in prompt
        assert "3 passed" in prompt

    def test_tool_actions_included(self) -> None:
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result()
        result.tool_actions_summary = [
            {"tool": "Bash", "args": "pytest", "output": "ok", "exit_code": 0, "is_test": True},
        ]
        report = ArtifactReport(all_empty=False, summary="ok")
        prompt = _build_quality_prompt(task, result, report)
        assert "Tool Actions" in prompt
        assert "[TEST]" in prompt


# =============================================================================
# evaluate_worker_output
# =============================================================================


class TestEvaluateWorkerOutput:
    @pytest.mark.asyncio
    async def test_test_task_uses_higher_threshold(self) -> None:
        """Test tasks should use test_quality_threshold (default 4)."""
        provider = AsyncMock()
        provider.chat.return_value = {"content": "SCORE: 3\nFEEDBACK: Acceptable"}
        config = SwarmConfig(test_quality_threshold=4)
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(tool_calls=5, output="pytest ran, 2 passed")

        gate_result = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="test-model",
            task=task,
            result=result,
            swarm_config=config,
        )
        # Score 3 < threshold 4 → should fail
        assert gate_result.passed is False
        assert gate_result.score == 3

    @pytest.mark.asyncio
    async def test_implement_task_uses_default_threshold(self) -> None:
        """Implement tasks should use quality_threshold (default 3)."""
        provider = AsyncMock()
        provider.chat.return_value = {"content": "SCORE: 3\nFEEDBACK: Acceptable"}
        config = SwarmConfig()
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        result = _make_result(tool_calls=5)

        gate_result = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="test-model",
            task=task,
            result=result,
            swarm_config=config,
        )
        # Score 3 >= threshold 3 → should pass
        assert gate_result.passed is True

    @pytest.mark.asyncio
    async def test_failsafe_score_2_for_test_tasks(self) -> None:
        """On LLM error, test tasks get score=2 (reject)."""
        provider = AsyncMock()
        provider.chat.side_effect = RuntimeError("LLM unavailable")
        config = SwarmConfig(test_quality_threshold=4)
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(tool_calls=5, output="pytest ran, 2 passed")

        gate_result = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="test-model",
            task=task,
            result=result,
            swarm_config=config,
        )
        assert gate_result.gate_error is True
        assert gate_result.score == 2
        assert gate_result.passed is False

    @pytest.mark.asyncio
    async def test_failsafe_score_3_for_non_test_tasks(self) -> None:
        """On LLM error, non-test tasks get score=3 (pass with default threshold)."""
        provider = AsyncMock()
        provider.chat.side_effect = RuntimeError("LLM unavailable")
        config = SwarmConfig()
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        result = _make_result(tool_calls=5)

        gate_result = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="test-model",
            task=task,
            result=result,
            swarm_config=config,
        )
        assert gate_result.gate_error is True
        assert gate_result.score == 3
        assert gate_result.passed is True

    @pytest.mark.asyncio
    async def test_verification_evidence_passed_to_prompt(self) -> None:
        """Verification evidence should appear in the judge prompt."""
        provider = AsyncMock()
        provider.chat.return_value = {"content": "SCORE: 5\nFEEDBACK: Great"}
        config = SwarmConfig()
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(tool_calls=5, output="pytest ran, all passed")

        evidence = {"passed": True, "checks": [{"name": "tests", "passed": True, "message": "ok"}]}
        gate_result = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="test-model",
            task=task,
            result=result,
            swarm_config=config,
            verification_evidence=evidence,
        )
        # Check the prompt sent to the LLM contains verification info
        call_args = provider.chat.call_args
        messages = call_args[0][0]
        user_prompt = messages[1]["content"]
        assert "Verification Gate Results" in user_prompt

    @pytest.mark.asyncio
    async def test_pre_flight_reject_returns_early(self) -> None:
        """V11 pre-flight should reject before LLM is called."""
        provider = AsyncMock()
        config = SwarmConfig(test_require_execution_evidence=True)
        task = _make_task(task_type=SubtaskType.TEST)
        result = _make_result(
            tool_calls=5,
            output="I created some files.",  # no test evidence
        )

        gate_result = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="test-model",
            task=task,
            result=result,
            swarm_config=config,
        )
        assert gate_result.passed is False
        assert gate_result.pre_flight_reject is True
        # LLM should NOT have been called
        provider.chat.assert_not_called()
