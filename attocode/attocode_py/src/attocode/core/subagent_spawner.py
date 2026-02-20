"""Subagent spawner - manages subagent lifecycle, budget allocation, and graceful timeout.

Handles spawning child agents with their own budgets, parsing their
structured closure reports, and managing graceful shutdown with wrapup warnings.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from attocode.types.budget import ExecutionBudget, BudgetEnforcementMode, SUBAGENT_BUDGET
from attocode.types.events import EventType


@dataclass(slots=True)
class SubagentBudget:
    """Budget allocation for a subagent."""

    max_tokens: int
    max_iterations: int
    max_duration_seconds: float
    enforcement_mode: BudgetEnforcementMode = BudgetEnforcementMode.STRICT

    def to_execution_budget(self) -> ExecutionBudget:
        soft_limit = int(self.max_tokens * 0.8)
        return ExecutionBudget(
            max_tokens=self.max_tokens,
            soft_token_limit=soft_limit,
            max_iterations=self.max_iterations,
            max_duration_seconds=self.max_duration_seconds,
            enforcement_mode=self.enforcement_mode,
        )


@dataclass(slots=True)
class ClosureReport:
    """Parsed structured closure report from a subagent."""

    summary: str = ""
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    remaining_work: list[str] = field(default_factory=list)
    errors_encountered: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 to 1.0


@dataclass(slots=True)
class SpawnResult:
    """Result of spawning a subagent."""

    agent_id: str
    success: bool
    response: str = ""
    closure_report: ClosureReport | None = None
    tokens_used: int = 0
    duration_ms: float = 0.0
    error: str | None = None
    timed_out: bool = False


def get_subagent_budget(
    parent_budget: ExecutionBudget,
    parent_tokens_used: int,
    *,
    fraction: float = 0.15,
    min_tokens: int = 50_000,
    max_tokens: int = 200_000,
    max_iterations: int = 30,
    max_duration_seconds: float = 300.0,
) -> SubagentBudget:
    """Calculate budget for a subagent based on parent's remaining budget.

    Allocates a fraction of the parent's remaining tokens, clamped
    between min_tokens and max_tokens.
    """
    remaining = max(0, parent_budget.max_tokens - parent_tokens_used)
    allocated = int(remaining * fraction)
    allocated = max(min_tokens, min(allocated, max_tokens))

    return SubagentBudget(
        max_tokens=allocated,
        max_iterations=max_iterations,
        max_duration_seconds=max_duration_seconds,
    )


def parse_closure_report(text: str) -> ClosureReport:
    """Parse a structured closure report from subagent output.

    Expected format (flexible, extracts what it can):
    ```
    ## Summary
    <text>

    ## Files Modified
    - file1.py
    - file2.py

    ## Files Created
    - new_file.py

    ## Key Decisions
    - Decision 1
    - Decision 2

    ## Remaining Work
    - Task 1

    ## Errors
    - Error 1

    ## Confidence: 0.85
    ```
    """
    report = ClosureReport()

    if not text:
        return report

    # Extract summary
    summary_match = re.search(
        r"##\s*Summary\s*\n(.*?)(?=\n##|\Z)", text, re.DOTALL | re.IGNORECASE,
    )
    if summary_match:
        report.summary = summary_match.group(1).strip()
    else:
        # Use first paragraph as summary fallback
        lines = text.strip().split("\n")
        summary_lines = []
        for line in lines:
            if line.strip() == "" and summary_lines:
                break
            if not line.startswith("#"):
                summary_lines.append(line)
        report.summary = "\n".join(summary_lines).strip()

    def _extract_list(heading: str) -> list[str]:
        pattern = rf"##\s*{heading}\s*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match:
            return []
        items = []
        for line in match.group(1).strip().split("\n"):
            line = line.strip()
            if line.startswith(("- ", "* ", "• ")):
                items.append(line[2:].strip())
            elif line and not line.startswith("#"):
                items.append(line)
        return items

    report.files_modified = _extract_list("Files Modified")
    report.files_created = _extract_list("Files Created")
    report.key_decisions = _extract_list("Key Decisions")
    report.remaining_work = _extract_list("Remaining Work")
    report.errors_encountered = _extract_list("Errors")

    # Extract confidence
    conf_match = re.search(r"##?\s*Confidence[:\s]*([\d.]+)", text, re.IGNORECASE)
    if conf_match:
        try:
            report.confidence = min(1.0, max(0.0, float(conf_match.group(1))))
        except ValueError:
            pass

    return report


class SubagentSpawner:
    """Manages spawning and lifecycle of subagents.

    Handles budget allocation, graceful timeout with wrapup warnings,
    and structured closure report parsing.
    """

    def __init__(
        self,
        *,
        parent_budget: ExecutionBudget | None = None,
        parent_tokens_used: int = 0,
        emit_event: Any = None,
        wrapup_warning_seconds: float = 30.0,
        hard_timeout_seconds: float = 300.0,
    ) -> None:
        self._parent_budget = parent_budget or ExecutionBudget()
        self._parent_tokens_used = parent_tokens_used
        self._emit = emit_event  # Callable for event emission
        self._wrapup_warning_seconds = wrapup_warning_seconds
        self._hard_timeout = hard_timeout_seconds
        self._active_agents: dict[str, asyncio.Task[Any]] = {}

    @property
    def active_count(self) -> int:
        return len(self._active_agents)

    async def spawn(
        self,
        run_fn: Any,
        *,
        task_description: str = "",
        budget_fraction: float = 0.15,
        timeout: float | None = None,
    ) -> SpawnResult:
        """Spawn a subagent with budget allocation and timeout management.

        Args:
            run_fn: Async callable that runs the subagent. Receives (budget, agent_id).
            task_description: Description of the subagent's task.
            budget_fraction: Fraction of remaining parent budget to allocate.
            timeout: Override for hard timeout in seconds.

        Returns:
            SpawnResult with the subagent's output and metrics.
        """
        agent_id = f"sub-{uuid.uuid4().hex[:8]}"
        start_time = time.monotonic()

        # Calculate budget
        sub_budget = get_subagent_budget(
            self._parent_budget,
            self._parent_tokens_used,
            fraction=budget_fraction,
        )

        effective_timeout = timeout or self._hard_timeout

        if self._emit:
            self._emit(EventType.SUBAGENT_SPAWN, agent_id=agent_id, task=task_description)

        try:
            # Create the task
            task = asyncio.create_task(
                run_fn(sub_budget.to_execution_budget(), agent_id),
            )
            self._active_agents[agent_id] = task

            # Set up wrapup warning timer
            wrapup_time = effective_timeout - self._wrapup_warning_seconds
            if wrapup_time > 0:
                asyncio.get_event_loop().call_later(
                    wrapup_time,
                    lambda: self._emit and self._emit(
                        EventType.SUBAGENT_WRAPUP_STARTED, agent_id=agent_id,
                    ),
                )

            # Wait with timeout
            result = await asyncio.wait_for(task, timeout=effective_timeout)

            duration_ms = (time.monotonic() - start_time) * 1000

            # Parse closure report from response
            response_text = ""
            tokens_used = 0
            success = True
            if hasattr(result, "response"):
                response_text = result.response or ""
            if hasattr(result, "metrics") and result.metrics:
                tokens_used = getattr(result.metrics, "total_tokens", 0)
            if hasattr(result, "success"):
                success = result.success

            closure = parse_closure_report(response_text)

            if self._emit:
                self._emit(EventType.SUBAGENT_COMPLETE, agent_id=agent_id)

            return SpawnResult(
                agent_id=agent_id,
                success=success,
                response=response_text,
                closure_report=closure,
                tokens_used=tokens_used,
                duration_ms=duration_ms,
            )

        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - start_time) * 1000
            if self._emit:
                self._emit(EventType.SUBAGENT_TIMEOUT_HARD_KILL, agent_id=agent_id)
            return SpawnResult(
                agent_id=agent_id,
                success=False,
                error=f"Subagent timed out after {effective_timeout}s",
                duration_ms=duration_ms,
                timed_out=True,
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            if self._emit:
                self._emit(EventType.SUBAGENT_ERROR, agent_id=agent_id, error=str(e))
            return SpawnResult(
                agent_id=agent_id,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )
        finally:
            self._active_agents.pop(agent_id, None)

    async def cancel_all(self) -> None:
        """Cancel all active subagents."""
        for agent_id, task in list(self._active_agents.items()):
            if not task.done():
                task.cancel()
        self._active_agents.clear()

    def update_parent_usage(self, tokens_used: int) -> None:
        """Update the parent's token usage for budget calculations."""
        self._parent_tokens_used = tokens_used
