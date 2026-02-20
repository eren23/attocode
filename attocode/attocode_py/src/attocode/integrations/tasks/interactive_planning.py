"""Interactive planning: Draft -> Discuss -> Execute -> Checkpoint cycle.

Orchestrates the lifecycle of an :class:`InteractivePlan`, mediating
between user feedback, LLM-generated plans, and step-by-step execution.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from attocode.integrations.tasks.planning import (
    InteractivePlan,
    PlanCheckpoint,
    PlanPhase,
    PlanStep,
)
from attocode.types.agent import TaskStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM provider protocol
# ---------------------------------------------------------------------------


class _LLMProvider(Protocol):
    """Minimal LLM provider interface for plan generation."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Prompt builders (stateless, testable)
# ---------------------------------------------------------------------------


def build_draft_prompt(goal: str, context: str) -> str:
    """Build the LLM prompt that generates an initial plan.

    The prompt instructs the LLM to return a JSON array of steps, each
    with ``description``, ``dependencies`` (list of step IDs), and
    ``estimated_tokens``.
    """
    return (
        "You are a planning assistant. Given the goal and context below, "
        "produce a step-by-step execution plan.\n\n"
        f"## Goal\n{goal}\n\n"
        f"## Context\n{context}\n\n"
        "## Instructions\n"
        "Return a JSON array of step objects.  Each object has:\n"
        '  - "description": concise step description\n'
        '  - "dependencies": list of step IDs this depends on (e.g. ["step-1"])\n'
        '  - "estimated_tokens": rough token budget for this step (integer)\n\n'
        "Use step IDs of the form step-1, step-2, etc.\n"
        "Return ONLY the JSON array, no markdown fences or commentary."
    )


def build_discuss_prompt(plan: InteractivePlan, feedback: str) -> str:
    """Build a prompt that revises an existing plan based on user feedback."""
    steps_json = json.dumps(
        [
            {
                "id": s.id,
                "description": s.description,
                "dependencies": s.dependencies,
                "estimated_tokens": s.estimated_tokens,
            }
            for s in plan.steps
        ],
        indent=2,
    )
    return (
        "You are a planning assistant. The user wants to revise the plan below.\n\n"
        f"## Current Plan\n```json\n{steps_json}\n```\n\n"
        f"## User Feedback\n{feedback}\n\n"
        "## Instructions\n"
        "Return the revised JSON array of step objects (same schema).\n"
        "Return ONLY the JSON array, no markdown fences or commentary."
    )


def build_step_prompt(plan: InteractivePlan, step: PlanStep) -> str:
    """Build a prompt used when executing a single plan step."""
    completed = [
        f"- {s.description}: {s.result or 'done'}"
        for s in plan.steps
        if s.status == TaskStatus.COMPLETED
    ]
    completed_text = "\n".join(completed) if completed else "None yet."

    return (
        f"## Overall Goal\n{plan.goal}\n\n"
        f"## Completed Steps\n{completed_text}\n\n"
        f"## Current Step\n**{step.id}:** {step.description}\n\n"
        "Execute this step now. Be thorough but concise."
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_steps_json(text: str) -> list[PlanStep]:
    """Extract a list of PlanStep objects from LLM JSON output."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        raw_steps = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find a JSON array somewhere in the text
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            raw_steps = json.loads(match.group(0))
        else:
            logger.warning("Failed to parse plan steps from LLM response")
            return []

    steps: list[PlanStep] = []
    for i, raw in enumerate(raw_steps):
        step_id = raw.get("id", f"step-{i + 1}")
        steps.append(
            PlanStep(
                id=step_id,
                description=raw.get("description", f"Step {i + 1}"),
                dependencies=raw.get("dependencies", []),
                estimated_tokens=raw.get("estimated_tokens", 0),
            )
        )
    return steps


def _extract_llm_content(response: dict[str, Any] | str) -> str:
    """Pull plain-text content out of an LLM response envelope."""
    if isinstance(response, str):
        return response
    content = response.get("content", "")
    if not content:
        msg = response.get("message", {})
        if isinstance(msg, dict):
            content = msg.get("content", "")
    return content


# ---------------------------------------------------------------------------
# InteractivePlanner
# ---------------------------------------------------------------------------


class InteractivePlanner:
    """Manages the lifecycle of an interactive plan.

    Transitions:
        drafting -> discussing -> approved -> executing -> completed
                                         \\-> rejected
    """

    def __init__(
        self,
        provider: _LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model

    # -- Plan creation / revision ------------------------------------------

    async def draft(self, goal: str, context: str = "") -> InteractivePlan:
        """Create an initial plan by calling the LLM.

        Falls back to a single-step plan if no provider is configured or
        the LLM call fails.
        """
        plan = InteractivePlan(goal=goal, phase=PlanPhase.DRAFTING)

        if self._provider is None:
            plan.steps = [
                PlanStep(id="step-1", description=goal),
            ]
            return plan

        prompt = build_draft_prompt(goal, context)
        try:
            response = await self._provider.chat(
                [{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=2000,
                temperature=0.3,
            )
            content = _extract_llm_content(response)
            plan.steps = _parse_steps_json(content) or [
                PlanStep(id="step-1", description=goal)
            ]
        except Exception:
            logger.warning("Plan draft LLM call failed, using single-step fallback")
            plan.steps = [PlanStep(id="step-1", description=goal)]

        return plan

    async def discuss(
        self, plan: InteractivePlan, feedback: str
    ) -> InteractivePlan:
        """Revise *plan* according to user *feedback* via LLM.

        Transitions the plan to :attr:`PlanPhase.DISCUSSING`.
        """
        plan.phase = PlanPhase.DISCUSSING

        if self._provider is None:
            return plan

        prompt = build_discuss_prompt(plan, feedback)
        try:
            response = await self._provider.chat(
                [{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=2000,
                temperature=0.3,
            )
            content = _extract_llm_content(response)
            new_steps = _parse_steps_json(content)
            if new_steps:
                plan.steps = new_steps
        except Exception:
            logger.warning("Plan discuss LLM call failed, keeping current steps")

        return plan

    # -- Phase transitions -------------------------------------------------

    def approve(self, plan: InteractivePlan) -> InteractivePlan:
        """Mark *plan* as approved and ready for execution."""
        if plan.phase in (PlanPhase.COMPLETED, PlanPhase.REJECTED):
            raise ValueError(f"Cannot approve a plan in phase '{plan.phase.value}'")
        plan.phase = PlanPhase.APPROVED
        plan.approved_at = time.monotonic()
        return plan

    def reject(self, plan: InteractivePlan, reason: str = "") -> InteractivePlan:
        """Reject *plan* with an optional reason."""
        plan.phase = PlanPhase.REJECTED
        logger.info("Plan rejected: %s", reason or "no reason given")
        return plan

    def start_execution(self, plan: InteractivePlan) -> InteractivePlan:
        """Begin executing an approved plan.

        Marks the first ready step as :attr:`TaskStatus.IN_PROGRESS`.
        """
        if plan.phase not in (PlanPhase.APPROVED, PlanPhase.CHECKPOINTING):
            raise ValueError(
                f"Cannot start execution from phase '{plan.phase.value}'"
            )
        plan.phase = PlanPhase.EXECUTING

        # Kick off the first step
        first = self._find_next_step(plan)
        if first is not None:
            first.status = TaskStatus.IN_PROGRESS

        return plan

    def advance_step(self, plan: InteractivePlan, result: str = "") -> InteractivePlan:
        """Mark the current step as completed and advance to the next.

        If no more steps remain, transitions the plan to
        :attr:`PlanPhase.COMPLETED`.
        """
        current = self.get_current_step(plan)
        if current is None:
            plan.phase = PlanPhase.COMPLETED
            return plan

        current.status = TaskStatus.COMPLETED
        current.result = result or None

        next_step = self._find_next_step(plan)
        if next_step is not None:
            next_step.status = TaskStatus.IN_PROGRESS
        else:
            plan.phase = PlanPhase.COMPLETED

        return plan

    # -- Checkpointing -----------------------------------------------------

    def checkpoint(
        self,
        plan: InteractivePlan,
        messages: list[dict[str, str]] | None = None,
        metrics: dict[str, float] | None = None,
    ) -> PlanCheckpoint:
        """Save a checkpoint at the current step boundary.

        Returns the newly created :class:`PlanCheckpoint`.
        """
        current = self.get_current_step(plan)
        step_index = 0
        if current is not None:
            try:
                step_index = next(
                    i for i, s in enumerate(plan.steps) if s.id == current.id
                )
            except StopIteration:
                pass

        previous_phase = plan.phase
        plan.phase = PlanPhase.CHECKPOINTING

        cp = PlanCheckpoint(
            step_index=step_index,
            messages_snapshot=list(messages) if messages else [],
            metrics_snapshot=dict(metrics) if metrics else {},
        )
        plan.checkpoints.append(cp)

        # Restore to executing if we were mid-execution
        if previous_phase == PlanPhase.EXECUTING:
            plan.phase = PlanPhase.EXECUTING

        return cp

    # -- Queries -----------------------------------------------------------

    def get_current_step(self, plan: InteractivePlan) -> PlanStep | None:
        """Return the step currently in progress, or ``None``."""
        for step in plan.steps:
            if step.status == TaskStatus.IN_PROGRESS:
                return step
        return None

    def get_progress(self, plan: InteractivePlan) -> float:
        """Return plan progress as a float from 0.0 to 1.0."""
        if not plan.steps:
            return 1.0
        completed = sum(
            1
            for s in plan.steps
            if s.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        )
        return completed / len(plan.steps)

    # -- Private helpers ---------------------------------------------------

    @staticmethod
    def _find_next_step(plan: InteractivePlan) -> PlanStep | None:
        """Find the next pending step whose dependencies are satisfied."""
        completed_ids = {
            s.id
            for s in plan.steps
            if s.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        }
        for step in plan.steps:
            if step.status == TaskStatus.PENDING:
                if all(dep in completed_ids for dep in step.dependencies):
                    return step
        return None
