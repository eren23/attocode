"""Per-worker budget enforcement with shared state reporting.

Lightweight tracker for individual swarm workers that enforces local
budget limits and reports to SharedEconomicsState for cross-worker
doom loop detection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from attocode.shared.shared_economics_state import SharedEconomicsState


@dataclass(slots=True)
class WorkerBudgetConfig:
    """Budget configuration for a single worker."""

    max_tokens: int = 300_000
    max_iterations: int = 50
    doom_loop_threshold: int = 3  # Consecutive identical calls before flagging


@dataclass(slots=True)
class WorkerBudgetCheckResult:
    """Result of a worker budget check."""

    can_continue: bool
    reason: str = ""
    budget_type: str = ""  # "tokens", "iterations", "doom_loop"


def compute_tool_fingerprint(tool_name: str, args: dict[str, Any]) -> str:
    """Compute a stable fingerprint for a tool call."""
    key = json.dumps({"tool": tool_name, "args": args}, sort_keys=True, default=str)
    return hashlib.md5(key.encode()).hexdigest()[:12]


@dataclass
class WorkerBudgetTracker:
    """Per-worker budget enforcement with shared state reporting.

    Tracks token usage, iterations, and doom loops locally.
    Reports fingerprints to shared economics state for global detection.
    """

    worker_id: str = ""
    config: WorkerBudgetConfig = field(default_factory=WorkerBudgetConfig)
    shared_state: SharedEconomicsState | None = None

    _input_tokens: int = field(default=0, repr=False)
    _output_tokens: int = field(default=0, repr=False)
    _total_tokens: int = field(default=0, repr=False)
    _iterations: int = field(default=0, repr=False)

    # Local doom loop detection
    _last_fingerprints: list[str] = field(default_factory=list)
    _consecutive_count: int = field(default=0, repr=False)

    def record_llm_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Update token counters."""
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._total_tokens += input_tokens + output_tokens

    def record_iteration(self) -> None:
        """Increment iteration count."""
        self._iterations += 1

    def record_tool_call(self, tool_name: str, args: dict[str, Any] | None = None) -> bool:
        """Compute fingerprint, report to shared state, check local doom loop.

        Returns True if a local doom loop is detected.
        """
        fp = compute_tool_fingerprint(tool_name, args or {})

        # Report to shared state
        if self.shared_state is not None:
            self.shared_state.record_tool_call(self.worker_id, fp)

        # Local doom loop detection
        if self._last_fingerprints and self._last_fingerprints[-1] == fp:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 1

        self._last_fingerprints.append(fp)
        if len(self._last_fingerprints) > 20:
            self._last_fingerprints = self._last_fingerprints[-20:]

        return self._consecutive_count >= self.config.doom_loop_threshold

    def check_budget(self) -> WorkerBudgetCheckResult:
        """Return budget check result with detailed reason."""
        # Token check
        if self.config.max_tokens > 0 and self._total_tokens >= self.config.max_tokens:
            return WorkerBudgetCheckResult(
                can_continue=False,
                reason=f"Token budget exhausted: {self._total_tokens} / {self.config.max_tokens}",
                budget_type="tokens",
            )

        # Iteration check
        if self.config.max_iterations > 0 and self._iterations >= self.config.max_iterations:
            return WorkerBudgetCheckResult(
                can_continue=False,
                reason=f"Iteration limit reached: {self._iterations} / {self.config.max_iterations}",
                budget_type="iterations",
            )

        # Doom loop check
        if self._consecutive_count >= self.config.doom_loop_threshold:
            return WorkerBudgetCheckResult(
                can_continue=False,
                reason=f"Local doom loop: {self._consecutive_count} consecutive identical calls",
                budget_type="doom_loop",
            )

        return WorkerBudgetCheckResult(can_continue=True)

    def get_usage(self) -> dict[str, int]:
        """Current usage stats."""
        return {
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "total_tokens": self._total_tokens,
            "iterations": self._iterations,
        }

    def get_utilization(self) -> float:
        """Usage as percentage (0-100%)."""
        if self.config.max_tokens <= 0:
            return 0.0
        return min(100.0, (self._total_tokens / self.config.max_tokens) * 100)
