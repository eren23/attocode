"""Autonomous pipeline for unattended feature delivery.

Chains 5 phases: Research → Plan → Implement → Verify → Commit.
Each phase can use fresh context (F1) for peak quality.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class PipelinePhase(StrEnum):
    """Phases of the autonomous pipeline."""

    RESEARCH = "research"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    COMMIT = "commit"


class PipelineStatus(StrEnum):
    """Status of the pipeline."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass(slots=True)
class PhaseResult:
    """Result of a single pipeline phase."""

    phase: PipelinePhase
    success: bool
    output: str = ""
    duration: float = 0.0
    error: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PipelineResult:
    """Result of the full autonomous pipeline."""

    status: PipelineStatus
    task: str
    phases: list[PhaseResult] = field(default_factory=list)
    total_duration: float = 0.0
    commit_hash: str = ""
    files_modified: list[str] = field(default_factory=list)

    @property
    def current_phase(self) -> PipelinePhase | None:
        for phase in PipelinePhase:
            if not any(p.phase == phase for p in self.phases):
                return phase
        return None

    @property
    def failed_phase(self) -> PipelinePhase | None:
        for p in self.phases:
            if not p.success:
                return p.phase
        return None


@dataclass(slots=True)
class PipelineConfig:
    """Configuration for the autonomous pipeline."""

    auto_commit: bool = True
    require_verification: bool = True
    max_implement_iterations: int = 10
    fresh_context_per_phase: bool = True
    commit_message_prefix: str = "auto"
    verify_commands: list[str] = field(default_factory=lambda: ["pytest", "mypy"])


class AutonomousPipeline:
    """Orchestrates unattended feature delivery.

    Five-phase pipeline:
    1. Research — Read codebase, understand context
    2. Plan — Decompose into steps, create plan
    3. Implement — Execute plan steps
    4. Verify — Run tests, linter, type checker
    5. Commit — Create atomic git commit
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self._config = config or PipelineConfig()
        self._result: PipelineResult | None = None
        self._start_time: float = 0.0

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def result(self) -> PipelineResult | None:
        return self._result

    def create_research_prompt(self, task: str, file_hints: list[str] | None = None) -> str:
        """Create the research phase prompt."""
        parts = [
            "## Research Phase",
            f"Task: {task}",
            "",
            "Analyze the codebase to understand:",
            "1. Which files are relevant to this task",
            "2. Existing patterns and conventions",
            "3. Dependencies and imports",
            "4. Test coverage for affected areas",
            "5. Potential risks or complications",
        ]
        if file_hints:
            parts.extend(["", "Suggested starting files:"])
            parts.extend(f"- {f}" for f in file_hints)
        parts.extend([
            "",
            "Output a structured analysis with file paths and key findings.",
        ])
        return "\n".join(parts)

    def create_plan_prompt(self, task: str, research_output: str) -> str:
        """Create the planning phase prompt."""
        return "\n".join([
            "## Planning Phase",
            f"Task: {task}",
            "",
            "## Research Findings",
            research_output,
            "",
            "## Instructions",
            "Create a detailed implementation plan:",
            "1. List specific files to create or modify",
            "2. Describe exact changes for each file",
            "3. Order changes by dependency (foundations first)",
            "4. Note any tests to add or update",
            "5. Identify risks and mitigation strategies",
            "",
            "Output a numbered step-by-step plan.",
        ])

    def create_verify_prompt(self, files_modified: list[str]) -> str:
        """Create the verification phase prompt."""
        file_list = "\n".join(f"- {f}" for f in files_modified) if files_modified else "None"
        commands = "\n".join(f"- `{c}`" for c in self._config.verify_commands)
        return "\n".join([
            "## Verification Phase",
            "",
            "Files modified:",
            file_list,
            "",
            "Run these verification commands:",
            commands,
            "",
            "Report pass/fail for each and any issues found.",
        ])

    def create_commit_prompt(self, task: str, files_modified: list[str]) -> str:
        """Create the commit phase prompt."""
        file_list = "\n".join(f"- {f}" for f in files_modified)
        return "\n".join([
            "## Commit Phase",
            f"Task: {task}",
            "",
            "Files modified:",
            file_list,
            "",
            "Create a descriptive git commit message following conventions.",
            f"Prefix: {self._config.commit_message_prefix}",
        ])

    def start(self, task: str) -> PipelineResult:
        """Initialize a new pipeline run."""
        self._start_time = time.monotonic()
        self._result = PipelineResult(
            status=PipelineStatus.RUNNING,
            task=task,
        )
        return self._result

    def record_phase(
        self,
        phase: PipelinePhase,
        success: bool,
        output: str = "",
        *,
        error: str | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> PhaseResult:
        """Record the result of a pipeline phase."""
        result = PhaseResult(
            phase=phase,
            success=success,
            output=output,
            duration=time.monotonic() - self._start_time,
            error=error,
            artifacts=artifacts or {},
        )

        if self._result is not None:
            self._result.phases.append(result)
            if not success:
                self._result.status = PipelineStatus.FAILED

        return result

    def complete(
        self,
        *,
        commit_hash: str = "",
        files_modified: list[str] | None = None,
    ) -> PipelineResult:
        """Mark the pipeline as completed."""
        if self._result is None:
            return PipelineResult(status=PipelineStatus.FAILED, task="")

        self._result.total_duration = time.monotonic() - self._start_time
        self._result.commit_hash = commit_hash
        self._result.files_modified = files_modified or []

        if self._result.status != PipelineStatus.FAILED:
            self._result.status = PipelineStatus.COMPLETED

        return self._result

    def get_status_summary(self) -> str:
        """Get a human-readable status summary."""
        if self._result is None:
            return "Pipeline not started."

        lines = [
            f"Pipeline: {self._result.status.value}",
            f"Task: {self._result.task}",
        ]

        for pr in self._result.phases:
            status = "pass" if pr.success else "FAIL"
            lines.append(f"  [{status}] {pr.phase.value} ({pr.duration:.1f}s)")

        if self._result.current_phase:
            lines.append(f"  Next: {self._result.current_phase.value}")

        return "\n".join(lines)
