"""Planning types and utilities.

Defines the data model for interactive plans: phases, steps,
checkpoints, and markdown serialisation/deserialisation.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum

from attocode.types.agent import TaskStatus


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PlanPhase(StrEnum):
    """Lifecycle phase of an interactive plan."""

    DRAFTING = "drafting"
    DISCUSSING = "discussing"
    APPROVED = "approved"
    EXECUTING = "executing"
    CHECKPOINTING = "checkpointing"
    COMPLETED = "completed"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PlanStep:
    """A single step inside an interactive plan."""

    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    actual_tokens: int = 0
    result: str | None = None


@dataclass(slots=True)
class PlanCheckpoint:
    """Snapshot captured at a specific step boundary."""

    step_index: int
    messages_snapshot: list[dict[str, str]] = field(default_factory=list)
    metrics_snapshot: dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class InteractivePlan:
    """Full interactive plan with lifecycle tracking."""

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    phase: PlanPhase = PlanPhase.DRAFTING
    created_at: float = field(default_factory=time.monotonic)
    approved_at: float | None = None
    checkpoints: list[PlanCheckpoint] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Markdown serialisation
# ---------------------------------------------------------------------------

_STATUS_EMOJI: dict[TaskStatus, str] = {
    TaskStatus.PENDING: "[ ]",
    TaskStatus.IN_PROGRESS: "[~]",
    TaskStatus.COMPLETED: "[x]",
    TaskStatus.FAILED: "[!]",
    TaskStatus.BLOCKED: "[B]",
    TaskStatus.SKIPPED: "[-]",
}

_EMOJI_TO_STATUS: dict[str, TaskStatus] = {v: k for k, v in _STATUS_EMOJI.items()}


def plan_to_markdown(plan: InteractivePlan) -> str:
    """Render an interactive plan as a human-readable markdown string."""
    lines: list[str] = [
        f"# Plan: {plan.goal}",
        "",
        f"**Phase:** {plan.phase.value}",
        f"**Steps:** {len(plan.steps)}",
        f"**Checkpoints:** {len(plan.checkpoints)}",
        "",
        "## Steps",
        "",
    ]

    for i, step in enumerate(plan.steps, 1):
        marker = _STATUS_EMOJI.get(step.status, "[ ]")
        dep_info = ""
        if step.dependencies:
            dep_info = f" (depends on: {', '.join(step.dependencies)})"
        tokens_info = ""
        if step.estimated_tokens:
            tokens_info = f" [est:{step.estimated_tokens}"
            if step.actual_tokens:
                tokens_info += f"/act:{step.actual_tokens}"
            tokens_info += "]"
        lines.append(f"{i}. {marker} {step.description}{dep_info}{tokens_info}")
        if step.result:
            lines.append(f"   > {step.result}")

    if plan.checkpoints:
        lines.append("")
        lines.append("## Checkpoints")
        lines.append("")
        for cp in plan.checkpoints:
            lines.append(
                f"- Step {cp.step_index}: "
                f"{len(cp.messages_snapshot)} messages, "
                f"{len(cp.metrics_snapshot)} metrics"
            )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

_STEP_RE = re.compile(
    r"^\d+\.\s+"
    r"\[([x~!B\-\s])\]\s+"
    r"(.+?)$",
    re.MULTILINE,
)


def parse_plan_from_markdown(text: str) -> InteractivePlan:
    """Parse a markdown plan back into an :class:`InteractivePlan`.

    This is a best-effort parser that extracts goal, phase, and steps.
    Checkpoint data is not round-tripped because it contains opaque
    binary-ish snapshots.
    """
    # Extract goal from the first heading
    goal = "unknown"
    goal_match = re.search(r"^#\s+Plan:\s*(.+)$", text, re.MULTILINE)
    if goal_match:
        goal = goal_match.group(1).strip()

    # Extract phase
    phase = PlanPhase.DRAFTING
    phase_match = re.search(r"\*\*Phase:\*\*\s*(\w+)", text)
    if phase_match:
        try:
            phase = PlanPhase(phase_match.group(1))
        except ValueError:
            pass

    # Extract steps
    steps: list[PlanStep] = []
    for i, match in enumerate(_STEP_RE.finditer(text)):
        marker = f"[{match.group(1)}]"
        description_raw = match.group(2).strip()

        # Parse optional dependency info: (depends on: step-1, step-2)
        deps: list[str] = []
        dep_match = re.search(r"\(depends on:\s*([^)]+)\)", description_raw)
        if dep_match:
            deps = [d.strip() for d in dep_match.group(1).split(",")]
            description_raw = description_raw[: dep_match.start()].strip()

        # Parse optional token info: [est:500/act:320]
        est_tokens = 0
        act_tokens = 0
        tok_match = re.search(r"\[est:(\d+)(?:/act:(\d+))?\]", description_raw)
        if tok_match:
            est_tokens = int(tok_match.group(1))
            if tok_match.group(2):
                act_tokens = int(tok_match.group(2))
            description_raw = description_raw[: tok_match.start()].strip()

        status = _EMOJI_TO_STATUS.get(marker, TaskStatus.PENDING)

        steps.append(
            PlanStep(
                id=f"step-{i + 1}",
                description=description_raw,
                status=status,
                dependencies=deps,
                estimated_tokens=est_tokens,
                actual_tokens=act_tokens,
            )
        )

    return InteractivePlan(goal=goal, steps=steps, phase=phase)
