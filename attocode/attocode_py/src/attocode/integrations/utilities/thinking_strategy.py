"""Thinking strategy selector.

Determines whether to use extended thinking mode based on
task complexity, budget constraints, and model capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ThinkingMode(StrEnum):
    """Thinking mode for LLM requests."""

    NONE = "none"  # No extended thinking
    BASIC = "basic"  # Standard thinking
    EXTENDED = "extended"  # Extended thinking with budget


@dataclass(slots=True)
class ThinkingConfig:
    """Configuration for thinking strategy."""

    mode: ThinkingMode = ThinkingMode.NONE
    budget_tokens: int = 10_000
    reason: str = ""


# Models known to support extended thinking
THINKING_MODELS = frozenset({
    "claude-3-5-sonnet",
    "claude-sonnet-4",
    "claude-opus-4",
    "claude-3-opus",
})


def select_thinking_strategy(
    *,
    model: str = "",
    complexity: str = "simple",
    iteration: int = 0,
    budget_remaining_fraction: float = 1.0,
    is_planning: bool = False,
    is_debugging: bool = False,
) -> ThinkingConfig:
    """Select the appropriate thinking strategy.

    Args:
        model: Current model name.
        complexity: Task complexity level.
        iteration: Current iteration number.
        budget_remaining_fraction: Remaining budget as fraction (0.0-1.0).
        is_planning: Whether we're in planning mode.
        is_debugging: Whether we're debugging a failure.

    Returns:
        ThinkingConfig with the selected mode.
    """
    # Check if model supports thinking
    model_lower = model.lower()
    supports_thinking = any(m in model_lower for m in THINKING_MODELS)

    if not supports_thinking:
        return ThinkingConfig(
            mode=ThinkingMode.NONE,
            reason=f"Model '{model}' does not support extended thinking",
        )

    # Don't use extended thinking when budget is low
    if budget_remaining_fraction < 0.2:
        return ThinkingConfig(
            mode=ThinkingMode.NONE,
            reason="Budget too low for extended thinking",
        )

    # Use extended thinking for complex tasks
    if complexity in ("complex", "deep_research"):
        budget = 20_000 if complexity == "deep_research" else 10_000
        return ThinkingConfig(
            mode=ThinkingMode.EXTENDED,
            budget_tokens=budget,
            reason=f"Complex task ({complexity}) benefits from extended thinking",
        )

    # Use extended thinking for planning
    if is_planning:
        return ThinkingConfig(
            mode=ThinkingMode.EXTENDED,
            budget_tokens=15_000,
            reason="Planning phase benefits from extended thinking",
        )

    # Use extended thinking for debugging
    if is_debugging:
        return ThinkingConfig(
            mode=ThinkingMode.EXTENDED,
            budget_tokens=10_000,
            reason="Debugging benefits from extended thinking",
        )

    # First iteration often benefits from thinking
    if iteration == 0 and complexity != "trivial":
        return ThinkingConfig(
            mode=ThinkingMode.BASIC,
            budget_tokens=5_000,
            reason="First iteration - basic thinking for task understanding",
        )

    return ThinkingConfig(
        mode=ThinkingMode.NONE,
        reason="Standard task, no extended thinking needed",
    )
