"""Execution economics manager.

Manages token budgets, cost tracking, and intelligent budget enforcement
with soft/hard limits. Integrates loop detection and phase tracking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
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
class CostEstimate:
    """Cost estimate for a single LLM call."""

    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    model: str = ""


@dataclass(slots=True)
class EconomicsTuning:
    """Configurable thresholds for all budget stages.

    Allows fine-tuning of when soft limits, warnings, force_text_only,
    and hard stops trigger.
    """

    # Soft limit ratios
    soft_warning_ratio: float = 0.7  # First budget warning
    soft_nudge_ratio: float = 0.8  # Start nudging efficiency
    soft_limit_ratio: float = 0.9  # Aggressive nudges
    force_text_ratio: float = 0.95  # Force text-only (no tool calls)
    hard_limit_ratio: float = 1.0  # Hard stop

    # Phase-specific reserves
    exploration_reserve: float = 0.3  # % budget for exploration phase
    verification_reserve: float = 0.15  # % budget for verification phase
    wrapup_reserve: float = 0.05  # % budget reserved for wrapup

    # Nudge intervals
    nudge_interval_iterations: int = 3  # Min iterations between nudges
    max_nudges_per_phase: int = 5  # Max nudges before escalating

    # Extension limits
    max_extensions: int = 3  # Max budget extensions
    extension_cooldown_seconds: float = 120.0  # Min time between extensions


@dataclass(slots=True)
class PhaseBudgetConfig:
    """Budget allocation per execution phase."""

    phase: str  # "exploration", "planning", "acting", "verifying"
    token_reserve: float  # Fraction of total budget reserved for this phase
    max_duration_seconds: float = 0.0  # Optional duration cap
    allow_extension: bool = True

    @property
    def display_name(self) -> str:
        """Human-readable name for the phase."""
        return self.phase.replace("_", " ").title()


@dataclass(slots=True)
class ProgressState:
    """Tracks agent progress for smarter budget decisions."""

    files_read: int = 0
    files_modified: int = 0
    commands_run: int = 0
    edits_made: int = 0
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    errors_encountered: int = 0

    @property
    def has_made_progress(self) -> bool:
        """Whether the agent has made any modifications."""
        return self.files_modified > 0 or self.edits_made > 0

    @property
    def productivity_score(self) -> float:
        """Score 0-1 based on progress vs effort."""
        effort = self.files_read + self.commands_run
        output = self.files_modified + self.edits_made
        if effort == 0:
            return 0.0
        return min(1.0, output / max(1, effort))

    def record_tool(self, tool_name: str, success: bool = True) -> None:
        """Record a tool call's contribution to progress."""
        READ_TOOLS = {"read_file", "glob", "grep", "search_files"}
        EDIT_TOOLS = {"write_file", "edit_file", "create_file", "patch_file"}
        BASH_TOOLS = {"bash", "run_command"}
        TEST_TOOLS = {"run_tests", "pytest"}

        if tool_name in READ_TOOLS:
            self.files_read += 1
        elif tool_name in EDIT_TOOLS:
            self.files_modified += 1
            self.edits_made += 1
        elif tool_name in BASH_TOOLS:
            self.commands_run += 1
        elif tool_name in TEST_TOOLS:
            self.tests_run += 1
            if success:
                self.tests_passed += 1
            else:
                self.tests_failed += 1

        if not success:
            self.errors_encountered += 1


class EnforcementLevel(StrEnum):
    """Graduated enforcement levels."""

    NONE = "none"  # No enforcement, tracking only
    WARN = "warn"  # Show warnings, always continue
    RESTRICTED = "restricted"  # Restrict tool calls, nudge efficiency
    HARD = "hard"  # Hard stop at limit


# Per-model cost rates (per million tokens)
MODEL_COST_RATES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-haiku-3-5-20241022": (0.25, 1.25),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "o3-mini": (1.10, 4.40),
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
}


def estimate_call_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> CostEstimate:
    """Estimate cost for an LLM call based on model rates."""
    rates = MODEL_COST_RATES.get(model)
    if rates is None:
        # Try prefix matching
        for key, val in MODEL_COST_RATES.items():
            if model.startswith(key.split("-")[0]):
                rates = val
                break
    if rates is None:
        rates = (3.0, 15.0)  # Default to sonnet rates

    input_rate, output_rate = rates
    input_cost = (input_tokens / 1_000_000) * input_rate
    output_cost = (output_tokens / 1_000_000) * output_rate
    return CostEstimate(
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=input_cost + output_cost,
        model=model,
    )


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
    recovery_suggestions: list[str] | None = None


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

    # Cache read tracking
    _total_cache_read_tokens: int = field(default=0, repr=False)

    # Model for cost estimation
    model: str = field(default="", repr=False)

    # Force text-only tracking
    _force_text_only: bool = field(default=False, repr=False)

    # Budget extension tracking
    _extensions_granted: int = field(default=0, repr=False)
    _original_max_tokens: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self._start_time = time.monotonic()
        self._original_max_tokens = self.budget.max_tokens
        self._tuning = EconomicsTuning()
        self._progress = ProgressState()
        self._last_extension_time: float = 0.0
        self._last_nudge_iteration: int = 0
        self._nudge_count: int = 0

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
        self._total_cache_read_tokens += cache_read_tokens

        # Use provided cost or estimate from model rates
        if cost > 0:
            self._estimated_cost += cost
        elif self.model:
            est = estimate_call_cost(self.model, input_tokens, output_tokens)
            self._estimated_cost += est.total_cost

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

        self._progress.record_tool(tool_name, success=True)

        return loop, nudge

    def check_budget(self) -> BudgetCheck:
        """Check if execution can continue within budget.

        Enforcement modes:
        - STRICT: Hard stop at limit, force_text_only near limit.
        - ADVISORY: Nudge but always allow continuation.
        - NONE: No enforcement, just tracking.

        Returns a BudgetCheck with the current status and whether
        the agent can continue.
        """
        # Soft enforcement mode means always continue (tracking only)
        if self.enforcement_mode == BudgetEnforcementMode.SOFT:
            frac = self._total_tokens / max(1, self.budget.max_tokens) if self.budget.max_tokens > 0 else 0.0
            return BudgetCheck(
                can_continue=True,
                status=BudgetStatus.OK,
                usage_fraction=frac,
            )

        # Iteration check
        if self.budget.max_iterations is not None and self.budget.max_iterations > 0:
            if self._llm_calls >= self.budget.max_iterations:
                if self.enforcement_mode == BudgetEnforcementMode.ADVISORY:
                    return BudgetCheck(
                        can_continue=True,
                        status=BudgetStatus.WARNING,
                        usage_fraction=1.0,
                        budget_type="iterations",
                        message=f"Iteration limit reached ({self.budget.max_iterations}) [advisory]",
                        injected_prompt="You have exceeded the iteration limit. Wrap up efficiently.",
                        allows_task_continuation=True,
                    )
                return BudgetCheck(
                    can_continue=False,
                    status=BudgetStatus.EXHAUSTED,
                    usage_fraction=1.0,
                    budget_type="iterations",
                    message=f"Iteration limit reached ({self.budget.max_iterations})",
                    recovery_suggestions=["Request budget extension", "Complete current task immediately"],
                )

        # Duration check
        if self.budget.max_duration_seconds and self.budget.max_duration_seconds > 0:
            elapsed = self.elapsed_seconds
            if elapsed >= self.budget.max_duration_seconds:
                if self.enforcement_mode == BudgetEnforcementMode.STRICT:
                    return BudgetCheck(
                        can_continue=False,
                        status=BudgetStatus.EXHAUSTED,
                        usage_fraction=1.0,
                        budget_type="duration",
                        message=f"Duration limit reached ({elapsed:.0f}s/{self.budget.max_duration_seconds}s)",
                    )

        # Token check
        if self.budget.max_tokens > 0:
            usage_fraction = self._total_tokens / self.budget.max_tokens

            # Hard limit
            if usage_fraction >= 1.0:
                if self.enforcement_mode == BudgetEnforcementMode.ADVISORY:
                    return BudgetCheck(
                        can_continue=True,
                        status=BudgetStatus.WARNING,
                        usage_fraction=usage_fraction,
                        budget_type="tokens",
                        message=f"Token budget exceeded ({self._total_tokens}/{self.budget.max_tokens}) [advisory]",
                        injected_prompt=self._budget_nudge(usage_fraction),
                        allows_task_continuation=True,
                    )
                return BudgetCheck(
                    can_continue=False,
                    status=BudgetStatus.EXHAUSTED,
                    usage_fraction=usage_fraction,
                    budget_type="tokens",
                    message=f"Token budget exhausted ({self._total_tokens}/{self.budget.max_tokens})",
                    recovery_suggestions=[
                        "Request budget extension",
                        "Trigger compaction to free context",
                        "Complete the most important remaining task",
                    ],
                )

            # Soft limit — nudge but allow continuation
            soft_ratio = self.budget.soft_ratio or 0.8
            if usage_fraction >= soft_ratio:
                force_text = (
                    self.enforcement_mode == BudgetEnforcementMode.STRICT
                    and usage_fraction >= 0.95
                )
                self._force_text_only = force_text
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

    @property
    def cache_read_tokens(self) -> int:
        """Total cache read tokens (KV-cache hits)."""
        return self._total_cache_read_tokens

    @property
    def force_text_only(self) -> bool:
        """Whether force_text_only mode is active."""
        return self._force_text_only

    @property
    def extensions_granted(self) -> int:
        """Number of budget extensions granted."""
        return self._extensions_granted

    @property
    def original_max_tokens(self) -> int:
        """Original max tokens before any extensions."""
        return self._original_max_tokens

    def record_extension(self, additional_tokens: int) -> None:
        """Record a budget extension."""
        self._extensions_granted += 1
        self._last_extension_time = time.monotonic()
        self.budget = ExecutionBudget(
            max_tokens=self.budget.max_tokens + additional_tokens,
            max_iterations=self.budget.max_iterations,
            soft_ratio=self.budget.soft_ratio,
            enforcement_mode=self.budget.enforcement_mode,
        )

    def estimate_remaining_calls(self, avg_tokens_per_call: int = 0) -> int:
        """Estimate how many more LLM calls can fit in the budget."""
        if self.budget.max_tokens <= 0:
            return 999

        remaining_tokens = max(0, self.budget.max_tokens - self._total_tokens)
        if avg_tokens_per_call <= 0:
            # Estimate from history
            if self._llm_calls > 0:
                avg_tokens_per_call = self._total_tokens // self._llm_calls
            else:
                avg_tokens_per_call = 10_000  # Reasonable default

        return max(0, remaining_tokens // max(1, avg_tokens_per_call))

    def get_snapshot(self) -> UsageSnapshot:
        """Get a snapshot of current usage."""
        return UsageSnapshot(
            input_tokens=self._total_input_tokens,
            output_tokens=self._total_output_tokens,
            total_tokens=self._total_tokens,
            estimated_cost=self._estimated_cost,
            timestamp=time.monotonic(),
        )

    def get_detailed_metrics(self) -> dict[str, Any]:
        """Get comprehensive metrics for dashboards and debugging."""
        return {
            "total_tokens": self._total_tokens,
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "cache_read_tokens": self._total_cache_read_tokens,
            "incremental_tokens": self.incremental_tokens,
            "estimated_cost": self._estimated_cost,
            "llm_calls": self._llm_calls,
            "tool_calls": self._tool_calls,
            "elapsed_seconds": self.elapsed_seconds,
            "usage_fraction": self.usage_fraction,
            "budget_max_tokens": self.budget.max_tokens,
            "budget_max_iterations": self.budget.max_iterations,
            "enforcement_mode": str(self.enforcement_mode),
            "baseline_set": self._baseline_set,
            "baseline_tokens": self._baseline_tokens,
            "recovery_attempted": self._recovery_attempted,
            "force_text_only": self._force_text_only,
            "extensions_granted": self._extensions_granted,
            "original_max_tokens": self._original_max_tokens,
            "phase": self.phase_tracker.current_phase if hasattr(self.phase_tracker, "current_phase") else "unknown",
            "estimated_remaining_calls": self.estimate_remaining_calls(),
        }

    @property
    def progress(self) -> "ProgressState":
        """Get progress tracking state."""
        return self._progress

    def allow_task_continuation(self) -> bool:
        """Check if the agent should be allowed to continue to the next task.

        Used by task gates to decide whether to start a new task
        vs wrapping up. More conservative than check_budget() —
        requires enough budget for at least one meaningful task.
        """
        usage = self.usage_fraction

        # Always allow if below 70%
        if usage < 0.7:
            return True

        # Between 70-90%, allow if we estimate at least 3 more calls
        remaining_calls = self.estimate_remaining_calls()
        if usage < 0.9 and remaining_calls >= 3:
            return True

        # Above 90%, only allow if advisory mode
        if self.enforcement_mode in (
            BudgetEnforcementMode.SOFT,
            BudgetEnforcementMode.ADVISORY,
        ):
            return True

        return False

    def get_graduated_enforcement(self) -> "EnforcementLevel":
        """Get the current enforcement level based on usage progression.

        Enforcement graduates from none -> warn -> restricted -> hard
        as usage increases, providing smooth degradation instead of
        a cliff at the budget limit.
        """
        usage = self.usage_fraction
        tuning = self._tuning if hasattr(self, "_tuning") else EconomicsTuning()

        if self.enforcement_mode == BudgetEnforcementMode.SOFT:
            return EnforcementLevel.NONE

        if usage < tuning.soft_warning_ratio:
            return EnforcementLevel.NONE
        elif usage < tuning.soft_limit_ratio:
            return EnforcementLevel.WARN
        elif usage < tuning.force_text_ratio:
            return EnforcementLevel.RESTRICTED
        else:
            return EnforcementLevel.HARD

    def request_extension(
        self, additional_tokens: int, reason: str = ""
    ) -> dict[str, Any]:
        """Build a budget extension request.

        Returns a request dict for the extension handler to process.
        Does not actually grant the extension — that's done by record_extension().
        """
        tuning = self._tuning if hasattr(self, "_tuning") else EconomicsTuning()

        can_request = self._extensions_granted < tuning.max_extensions
        cooldown_ok = True
        if hasattr(self, "_last_extension_time"):
            elapsed = time.monotonic() - self._last_extension_time
            cooldown_ok = elapsed >= tuning.extension_cooldown_seconds

        return {
            "can_request": can_request and cooldown_ok,
            "current_tokens": self._total_tokens,
            "max_tokens": self.budget.max_tokens,
            "requested_additional": additional_tokens,
            "reason": reason,
            "extensions_granted": self._extensions_granted,
            "max_extensions": tuning.max_extensions,
            "usage_fraction": self.usage_fraction,
            "cooldown_ok": cooldown_ok,
        }

    def get_phase_budget(self, phase: str) -> "PhaseBudgetConfig":
        """Get budget allocation for a specific execution phase."""
        tuning = self._tuning if hasattr(self, "_tuning") else EconomicsTuning()

        reserves = {
            "exploration": tuning.exploration_reserve,
            "planning": 0.1,
            "acting": 1.0
            - tuning.exploration_reserve
            - tuning.verification_reserve
            - tuning.wrapup_reserve,
            "verifying": tuning.verification_reserve,
            "wrapup": tuning.wrapup_reserve,
        }

        return PhaseBudgetConfig(
            phase=phase,
            token_reserve=reserves.get(phase, 0.1),
            allow_extension=(phase != "wrapup"),
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
        self._total_cache_read_tokens = 0
        self._force_text_only = False
        self._extensions_granted = 0
        self._original_max_tokens = self.budget.max_tokens
        self.loop_detector.reset()
        self.phase_tracker.reset()
