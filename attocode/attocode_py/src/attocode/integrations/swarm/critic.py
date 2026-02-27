"""Swarm critic — wave reviewer that assesses completed wave output.

The critic reviews each wave's output after completion and produces:
- An overall assessment (good / needs-fixes / critical-issues)
- Per-task assessments with specific feedback
- Fixup instructions that generate FixupTask entries

Only runs if the ``critic`` role is configured in the swarm roles.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from attocode.integrations.swarm.types import (
    FixupTask,
    SubtaskType,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    WaveReviewResult,
    swarm_event,
)

if TYPE_CHECKING:
    from attocode.integrations.swarm.orchestrator import OrchestratorInternals
    from attocode.integrations.swarm.roles import RoleConfig

logger = logging.getLogger(__name__)


async def review_wave(
    ctx: OrchestratorInternals,
    critic_config: RoleConfig,
    wave_index: int,
    wave_tasks: list[SwarmTask],
) -> WaveReviewResult:
    """Review a completed wave's output using the critic role.

    Args:
        ctx: Orchestrator context.
        critic_config: The critic role configuration.
        wave_index: 0-based wave index.
        wave_tasks: Tasks that were part of this wave.

    Returns:
        WaveReviewResult with assessment and optional fixup instructions.
    """
    completed = [t for t in wave_tasks if t.status == SwarmTaskStatus.COMPLETED]
    failed = [t for t in wave_tasks if t.status == SwarmTaskStatus.FAILED]

    if not completed:
        return WaveReviewResult(
            assessment="critical-issues",
            task_assessments=[
                {"task_id": t.id, "assessment": "failed", "feedback": "Task did not complete"}
                for t in failed
            ],
        )

    # Build review prompt
    prompt = _build_review_prompt(wave_index, completed, failed)

    # Determine model
    model = critic_config.model or ctx.config.orchestrator_model

    try:
        response = await ctx.provider.chat(
            messages=[
                {"role": "system", "content": _CRITIC_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            model=model,
            max_tokens=2000,
            temperature=0.2,
        )

        if ctx.track_orchestrator_usage:
            ctx.track_orchestrator_usage(response, "wave-review")

        content = _extract_content(response)
        result = _parse_review_response(content, completed)

        # Emit wave review event
        ctx.emit(swarm_event(
            "swarm.wave.review",
            wave=wave_index + 1,
            assessment=result.assessment,
            task_assessments=result.task_assessments,
            fixup_count=len(result.fixup_instructions),
        ))

        return result

    except Exception as exc:
        logger.warning("Critic wave review failed: %s", exc)
        return WaveReviewResult(
            assessment="good",
            task_assessments=[],
        )


def build_fixup_tasks(
    review_result: WaveReviewResult,
    wave_index: int,
) -> list[FixupTask]:
    """Convert fixup instructions from a wave review into FixupTask instances.

    Only creates tasks if assessment is 'needs-fixes' or 'critical-issues'.
    """
    if review_result.assessment == "good":
        return []

    fixups: list[FixupTask] = []
    for i, instr in enumerate(review_result.fixup_instructions):
        task_id = instr.get("fixes_task_id", "")
        description = instr.get("fix_description", "")
        if not task_id or not description:
            continue

        fixup = FixupTask(
            id=f"fixup-w{wave_index}-{i}",
            description=description,
            type=SubtaskType.IMPLEMENT,
            complexity=3,
            dependencies=[task_id],
            fixes_task_id=task_id,
            fix_instructions=description,
            target_files=instr.get("target_files"),
        )
        fixups.append(fixup)

    return fixups


# =============================================================================
# Private
# =============================================================================

_CRITIC_SYSTEM_PROMPT = """\
You are a strict code review critic for a multi-agent AI coding system. \
Your job is to review the output of a completed wave of tasks and identify \
issues that need fixing. Be specific, actionable, and concise. Focus on:
1. Missing functionality or incomplete implementations
2. Broken inter-task dependencies (task A changed something task B relies on)
3. Code quality issues that will cause runtime errors
4. Missing test coverage for new code
Do NOT flag style issues, minor naming concerns, or documentation gaps."""


def _build_review_prompt(
    wave_index: int,
    completed: list[SwarmTask],
    failed: list[SwarmTask],
) -> str:
    """Build the critic review prompt."""
    sections: list[str] = [
        f"## Wave {wave_index + 1} Review",
        f"Completed: {len(completed)} tasks, Failed: {len(failed)} tasks",
        "",
    ]

    for task in completed:
        sections.append(f"### Task: {task.id}")
        sections.append(f"**Description:** {task.description}")
        sections.append(f"**Type:** {task.type}")

        if task.result:
            output = task.result.output
            if len(output) > 2000:
                output = output[:2000] + "\n... [truncated]"
            sections.append(f"**Output:**\n{output}")
            if task.result.files_modified:
                sections.append(f"**Files modified:** {', '.join(task.result.files_modified)}")
            if task.result.quality_score:
                sections.append(f"**Quality score:** {task.result.quality_score}/5")
        sections.append("")

    if failed:
        sections.append("### Failed Tasks")
        for task in failed:
            sections.append(f"- {task.id}: {task.description} (failure: {task.failure_mode})")
        sections.append("")

    sections.append(
        "## Instructions\n"
        "Assess the wave output. Respond with:\n"
        "ASSESSMENT: good | needs-fixes | critical-issues\n\n"
        "Then for each task that needs fixing:\n"
        "FIXUP: <task_id> | <one-sentence fix description>\n\n"
        "If assessment is 'good', no FIXUP lines needed."
    )

    return "\n".join(sections)


def _parse_review_response(
    content: str,
    completed: list[SwarmTask],
) -> WaveReviewResult:
    """Parse the critic's response into a WaveReviewResult."""
    import re

    assessment = "good"
    task_assessments: list[dict[str, Any]] = []
    fixup_instructions: list[dict[str, Any]] = []

    # Parse ASSESSMENT line
    assessment_match = re.search(r"ASSESSMENT:\s*(\S+)", content, re.IGNORECASE)
    if assessment_match:
        raw = assessment_match.group(1).strip().lower()
        if raw in ("needs-fixes", "needs_fixes", "needsfixes"):
            assessment = "needs-fixes"
        elif raw in ("critical-issues", "critical_issues", "criticalissues"):
            assessment = "critical-issues"
        else:
            assessment = "good"

    # Parse FIXUP lines
    for match in re.finditer(r"FIXUP:\s*(\S+)\s*\|\s*(.+)", content, re.IGNORECASE):
        task_id = match.group(1).strip()
        fix_desc = match.group(2).strip()
        fixup_instructions.append({
            "fixes_task_id": task_id,
            "fix_description": fix_desc,
        })
        task_assessments.append({
            "task_id": task_id,
            "assessment": "needs-fix",
            "feedback": fix_desc,
        })

    # Mark completed tasks without fixups as good
    fixup_ids = {f["fixes_task_id"] for f in fixup_instructions}
    for task in completed:
        if task.id not in fixup_ids:
            task_assessments.append({
                "task_id": task.id,
                "assessment": "good",
                "feedback": "",
            })

    return WaveReviewResult(
        assessment=assessment,
        task_assessments=task_assessments,
        fixup_instructions=fixup_instructions,
    )


def _extract_content(response: Any) -> str:
    """Extract text content from an LLM response."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        content = response.get("content", "")
        if content:
            return content
        msg = response.get("message", {})
        if isinstance(msg, dict):
            return msg.get("content", "")
    if hasattr(response, "content"):
        c = response.content
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return "\n".join(
                getattr(b, "text", str(b)) for b in c
            )
    return str(response)
