"""Tests for autonomous pipeline."""

from __future__ import annotations

import pytest

from attocode.core.autonomous import (
    AutonomousPipeline,
    PipelineConfig,
    PipelinePhase,
    PipelineResult,
    PipelineStatus,
)


class TestPipelineConfig:
    def test_defaults(self) -> None:
        config = PipelineConfig()
        assert config.auto_commit is True
        assert config.require_verification is True
        assert config.fresh_context_per_phase is True

    def test_custom(self) -> None:
        config = PipelineConfig(auto_commit=False, max_implement_iterations=5)
        assert config.auto_commit is False
        assert config.max_implement_iterations == 5


class TestAutonomousPipeline:
    def test_start(self) -> None:
        pipeline = AutonomousPipeline()
        result = pipeline.start("Add login feature")
        assert result.status == PipelineStatus.RUNNING
        assert result.task == "Add login feature"

    def test_research_prompt(self) -> None:
        pipeline = AutonomousPipeline()
        prompt = pipeline.create_research_prompt(
            "Fix auth bug",
            file_hints=["src/auth.py"],
        )
        assert "Research Phase" in prompt
        assert "Fix auth bug" in prompt
        assert "src/auth.py" in prompt

    def test_plan_prompt(self) -> None:
        pipeline = AutonomousPipeline()
        prompt = pipeline.create_plan_prompt(
            "Add feature",
            "Found relevant files in src/core/",
        )
        assert "Planning Phase" in prompt
        assert "Add feature" in prompt
        assert "src/core/" in prompt

    def test_verify_prompt(self) -> None:
        pipeline = AutonomousPipeline()
        prompt = pipeline.create_verify_prompt(["src/main.py", "src/utils.py"])
        assert "Verification" in prompt
        assert "src/main.py" in prompt

    def test_commit_prompt(self) -> None:
        pipeline = AutonomousPipeline()
        prompt = pipeline.create_commit_prompt("Fix bug", ["src/fix.py"])
        assert "Commit" in prompt
        assert "Fix bug" in prompt

    def test_record_phase_success(self) -> None:
        pipeline = AutonomousPipeline()
        pipeline.start("task")
        result = pipeline.record_phase(
            PipelinePhase.RESEARCH,
            success=True,
            output="Found 5 relevant files",
        )
        assert result.success is True
        assert result.phase == PipelinePhase.RESEARCH

    def test_record_phase_failure(self) -> None:
        pipeline = AutonomousPipeline()
        pipeline.start("task")
        pipeline.record_phase(PipelinePhase.VERIFY, success=False, error="Tests failed")
        assert pipeline.result is not None
        assert pipeline.result.status == PipelineStatus.FAILED

    def test_complete(self) -> None:
        pipeline = AutonomousPipeline()
        pipeline.start("task")
        pipeline.record_phase(PipelinePhase.RESEARCH, success=True)
        pipeline.record_phase(PipelinePhase.PLAN, success=True)
        pipeline.record_phase(PipelinePhase.IMPLEMENT, success=True)
        pipeline.record_phase(PipelinePhase.VERIFY, success=True)
        result = pipeline.complete(
            commit_hash="abc123",
            files_modified=["a.py", "b.py"],
        )
        assert result.status == PipelineStatus.COMPLETED
        assert result.commit_hash == "abc123"
        assert len(result.files_modified) == 2

    def test_complete_after_failure(self) -> None:
        pipeline = AutonomousPipeline()
        pipeline.start("task")
        pipeline.record_phase(PipelinePhase.VERIFY, success=False)
        result = pipeline.complete()
        assert result.status == PipelineStatus.FAILED

    def test_current_phase(self) -> None:
        pipeline = AutonomousPipeline()
        result = pipeline.start("task")
        assert result.current_phase == PipelinePhase.RESEARCH

        pipeline.record_phase(PipelinePhase.RESEARCH, success=True)
        assert result.current_phase == PipelinePhase.PLAN

    def test_failed_phase(self) -> None:
        pipeline = AutonomousPipeline()
        pipeline.start("task")
        pipeline.record_phase(PipelinePhase.RESEARCH, success=True)
        pipeline.record_phase(PipelinePhase.PLAN, success=False, error="Bad plan")
        assert pipeline.result is not None
        assert pipeline.result.failed_phase == PipelinePhase.PLAN

    def test_status_summary(self) -> None:
        pipeline = AutonomousPipeline()
        pipeline.start("Build login")
        pipeline.record_phase(PipelinePhase.RESEARCH, success=True)
        summary = pipeline.get_status_summary()
        assert "Build login" in summary
        assert "research" in summary
        assert "pass" in summary

    def test_status_summary_not_started(self) -> None:
        pipeline = AutonomousPipeline()
        assert "not started" in pipeline.get_status_summary().lower()

    def test_complete_without_start(self) -> None:
        pipeline = AutonomousPipeline()
        result = pipeline.complete()
        assert result.status == PipelineStatus.FAILED
