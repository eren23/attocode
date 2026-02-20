"""Execution economics manager.

Manages token budgets, cost tracking, and intelligent budget enforcement
with soft/hard limits. Integrates loop detection and phase tracking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from attocode.integrations.budget.loop_detector import LoopDetection, LoopDetector
from attocode.integrations.budget.phase_tracker import PhaseTracker
from attocode.types.budget import (
    BudgetCheckResult,
    BudgetEnforcementMode,
    BudgetStatus,
    ExecutionBudget,
    STANDARD_BUDGET,
)


@dataclass(slots=True)
class UsageSnapshot:
    """A snapshot of token usage at a point in time."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    timestamp: float = 0.0


@dataclass(slots=True)
class BudgetCheck:
    """Result of a budget check."""

    can_continue: bool
    status: BudgetStatus
    usage_fraction: float
    force_text_only: bool = False
    budget_type: str = ""
    message: str = ""
    injected_prompt: str = ""
    allows_task_continuation: bool = True


@dataclass
class ExecutionEconomicsManager:
    """Manages execution budget and resource tracking.

    Tracks token usage, cost, and duration against configurable budgets.
    Provides soft limits (nudges) and hard limits (stops). Integrates
    loop detection and phase tracking.
    """

    budget: ExecutionBudget = field(default_factory=lambda: STANDARD_BUDGET)
    enforcement_mode: BudgetEnforcementMode = BudgetEnforcementMode.STRICT

    # Sub-managers
    loop_detector: LoopDetector = field(default_factory=LoopDetector)
    phase_tracker: PhaseTracker = field(default_factory=PhaseTracker)

    # Tracking state
    _total_input_tokens: int = field(default=0, repr=False)
    _total_output_tokens: int = field(default=0, repr=False)
    _total_tokens: int = field(default=0, repr=False)
    _estimated_cost: float = field(default=0.0, repr=False)
    _llm_calls: int = field(default=0, repr=False)
    _tool_calls: int = field(default=0, repr=False)
    _start_time: float = field(default=0.0, repr=False)

    # Baseline for incremental accounting
    _baseline_tokens: int = field(default=0, repr=False)
    _baseline_set: bool = field(default=False, repr=False)

    # Duration pause tracking
    _pause_start: float = field(default=0.0, repr=False)
    _paused_duration: float = field(default=0.0, repr=False)

    # Recovery tracking
    _recovery_attempted: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self._start_time = time.monotonic()

    def set_baseline(self, tokens: int | None = None) -> None:
        """Set the token baseline for incremental accounting.

        Must be called after the first LLM response. Without this,
        token accounting grows quadratically causing premature budget
        exhaustion.
        """
        if tokens is not None:
            self._baseline_tokens = tokens
        else:
            self._baseline_tokens = self._total_tokens
        self._baseline_set = True

    def update_baseline(self, tokens_after: int) -> None:
        """Update baseline after compaction.

        Must be called after context compaction to reset incremental
        accounting. Without this, token deltas accumulate quadratically.
        """
        self._baseline_tokens = tokens_after

    def record_llm_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cost: float = 0.0,
        cache_read_tokens: int = 0,
    ) -> None:
        """Record token usage from an LLM call."""
        self._llm_calls += 1
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_tokens += input_tokens + output_tokens
        self._estimated_cost += cost

    def record_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        iteration: int = 0,
    ) -> tuple[LoopDetection, str | None]:
        """Record a tool call and check for loops/phase transitions.

        Returns:
            Tuple of (loop_detection, nudge_message).
        """
        self._tool_calls += 1

        loop = self.loop_detector.record(tool_name, arguments or {})
        nudge = self.phase_tracker.record_tool_use(tool_name, iteration)

        return loop, nudge

    def check_budget(self) -> BudgetCheck:
        """Check if execution can continue within budget.

        Returns a BudgetCheck with the current status and whether
        the agent can continue.
        """
        # Iteration check
        if self.budget.max_iterations is not None and self.budget.max_iterations > 0:
            if self._llm_calls >= self.budget.max_iterations:
                return BudgetCheck(
                    can_continue=False,
                    status=BudgetStatus.EXHAUSTED,
                    usage_fraction=1.0,
                    budget_type="iterations",
                    message=f"Iteration limit reached ({self.budget.max_iterations})",
                )

        # Token check
        if self.budget.max_tokens > 0:
            usage_fraction = self._total_tokens / self.budget.max_tokens

            # Hard limit
            if usage_fraction >= 1.0:
                return BudgetCheck(
                    can_continue=False,
                    status=BudgetStatus.EXHAUSTED,
                    usage_fraction=usage_fraction,
                    budget_type="tokens",
                    message=f"Token budget exhausted ({self._total_tokens}/{self.budget.max_tokens})",
                )

            # Soft limit — nudge but allow continuation
            soft_ratio = self.budget.soft_ratio or 0.8
            if usage_fraction >= soft_ratio:
                force_text = (
                    self.enforcement_mode == BudgetEnforcementMode.STRICT
                    and usage_fraction >= 0.95
                )
                return BudgetCheck(
                    can_continue=True,
                    status=BudgetStatus.WARNING,
                    usage_fraction=usage_fraction,
                    force_text_only=force_text,
                    budget_type="tokens",
                    message=f"Token budget at {usage_fraction:.0%}",
                    injected_prompt=self._budget_nudge(usage_fraction),
                    allows_task_continuation=not force_text,
                )

            return BudgetCheck(
                can_continue=True,
                status=BudgetStatus.OK,
                usage_fraction=usage_fraction,
            )

        # No budget limits
        return BudgetCheck(
            can_continue=True,
            status=BudgetStatus.OK,
            usage_fraction=0.0,
        )

    def _budget_nudge(self, fraction: float) -> str:
        """Generate a budget-aware nudge message."""
        remaining_pct = max(0, (1.0 - fraction) * 100)
        if remaining_pct < 5:
            return (
                "CRITICAL: Less than 5% budget remaining. "
                "Wrap up immediately. Complete current task and stop."
            )
        if remaining_pct < 15:
            return (
                f"WARNING: Only {remaining_pct:.0f}% budget remaining. "
                "Focus on completing the most important remaining work."
            )
        return (
            f"Budget at {fraction:.0%}. "
            "Be efficient with remaining budget."
        )

    def pause_duration(self) -> None:
        """Pause duration tracking (during LLM calls or approval waits)."""
        self._pause_start = time.monotonic()

    def resume_duration(self) -> None:
        """Resume duration tracking."""
        if self._pause_start > 0:
            self._paused_duration += time.monotonic() - self._pause_start
            self._pause_start = 0.0

    @property
    def recovery_attempted(self) -> bool:
        return self._recovery_attempted

    @recovery_attempted.setter
    def recovery_attempted(self, value: bool) -> None:
        self._recovery_attempted = value

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def incremental_tokens(self) -> int:
        """Tokens used since baseline was set."""
        if not self._baseline_set:
            return self._total_tokens
        return max(0, self._total_tokens - self._baseline_tokens)

    @property
    def estimated_cost(self) -> float:
        return self._estimated_cost

    @property
    def llm_calls(self) -> int:
        return self._llm_calls

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock seconds elapsed, excluding paused time."""
        total = time.monotonic() - self._start_time
        return total - self._paused_duration

    @property
    def usage_fraction(self) -> float:
        """Current budget usage as a fraction (0.0 to 1.0)."""
        if self.budget.max_tokens <= 0:
            return 0.0
        return min(self._total_tokens / self.budget.max_tokens, 1.0)

    def get_snapshot(self) -> UsageSnapshot:
        """Get a snapshot of current usage."""
        return UsageSnapshot(
            input_tokens=self._total_input_tokens,
            output_tokens=self._total_output_tokens,
            total_tokens=self._total_tokens,
            estimated_cost=self._estimated_cost,
            timestamp=time.monotonic(),
        )

    def reset(self) -> None:
        """Reset all tracking state."""
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_tokens = 0
        self._estimated_cost = 0.0
        self._llm_calls = 0
        self._tool_calls = 0
        self._start_time = time.monotonic()
        self._baseline_tokens = 0
        self._baseline_set = False
        self._paused_duration = 0.0
        self._pause_start = 0.0
        self._recovery_attempted = False
        self.loop_detector.reset()
        self.phase_tracker.reset()
