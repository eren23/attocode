"""Swarm lifecycle — decomposition, planning, verification, synthesis, and utilities.

Contains all LLM-driven lifecycle phases plus utility helpers for
stats building, checkpointing, artifact auditing, etc.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING, Any

from attocode.integrations.swarm.types import (
    BUILTIN_TASK_TYPE_CONFIGS,
    AcceptanceCriterion,
    ArtifactFile,
    ArtifactInventory,
    DependencyGraph,
    FixupTask,
    IntegrationTestPlan,
    IntegrationTestStep,
    OrchestratorDecision,
    SmartDecompositionResult,
    SmartSubtask,
    SwarmCheckpoint,
    SwarmError,
    SwarmExecutionResult,
    SwarmExecutionStats,
    SwarmPhase,
    SwarmPlan,
    SwarmStatus,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    SynthesisResult,
    VerificationResult,
    VerificationStepResult,
    swarm_event,
)

if TYPE_CHECKING:
    from attocode.integrations.swarm.orchestrator import OrchestratorInternals

logger = logging.getLogger(__name__)


# =============================================================================
# Decomposition
# =============================================================================


def classify_decomposition_failure(message: str) -> str:
    """Classify the cause of a decomposition failure."""
    lower = message.lower()
    if "429" in lower or "rate limit" in lower:
        return "rate_limit"
    if "402" in lower or "budget" in lower:
        return "provider_budget_limit"
    if "json" in lower or "parse" in lower:
        return "parse_failure"
    if "validation" in lower or "invalid" in lower:
        return "validation_failure"
    return "other"


def build_emergency_decomposition(
    ctx: OrchestratorInternals,
    task: str,
    _reason: str = "",
) -> SmartDecompositionResult:
    """Build a deterministic fallback decomposition with 4 fixed tasks."""
    # Get top files from codebase context
    relevant_files: list[str] = []
    if ctx.codebase_context:
        try:
            repo_map = ctx.codebase_context.get_repo_map()
            if isinstance(repo_map, str):
                # Parse file paths from string
                relevant_files = [
                    line.strip() for line in repo_map.split("\n")
                    if line.strip() and not line.startswith("#")
                ][:10]
        except Exception:
            pass

    subtasks = [
        SmartSubtask(
            id="task-fb-0",
            description=f"Design approach for: {task}",
            type="design",
            complexity=2,
            dependencies=[],
            relevant_files=relevant_files[:5],
        ),
        SmartSubtask(
            id="task-fb-1",
            description=f"Implement: {task}",
            type="implement",
            complexity=5,
            dependencies=["task-fb-0"],
            relevant_files=relevant_files,
        ),
        SmartSubtask(
            id="task-fb-2",
            description=f"Write tests for: {task}",
            type="test",
            complexity=3,
            dependencies=["task-fb-1"],
            relevant_files=relevant_files,
        ),
        SmartSubtask(
            id="task-fb-3",
            description=f"Integrate and verify: {task}",
            type="integrate",
            complexity=2,
            dependencies=["task-fb-1", "task-fb-2"],
            relevant_files=relevant_files[:5],
        ),
    ]

    return SmartDecompositionResult(
        subtasks=subtasks,
        strategy="emergency-fallback",
        reasoning=f"Emergency decomposition due to: {_reason}",
        dependency_graph=DependencyGraph(
            parallel_groups=[
                ["task-fb-0"],
                ["task-fb-1"],
                ["task-fb-2"],
                ["task-fb-3"],
            ],
        ),
        llm_assisted=False,
    )


async def last_resort_decompose(
    ctx: OrchestratorInternals,
    task: str,
) -> SmartDecompositionResult | None:
    """Simplified LLM decomposition with inline JSON example."""
    prompt = f"""Break this task into 2-5 subtasks. Return ONLY JSON:
{{
  "subtasks": [
    {{"id": "st-0", "description": "...", "type": "implement", "complexity": 5, "dependencies": []}},
    {{"id": "st-1", "description": "...", "type": "test", "complexity": 3, "dependencies": ["st-0"]}}
  ],
  "strategy": "sequential",
  "reasoning": "..."
}}

Task: {task}"""

    try:
        response = await ctx.provider.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.1,
        )
        if ctx.track_orchestrator_usage:
            ctx.track_orchestrator_usage(response, "last-resort-decompose")

        parsed = parse_json(response.content)
        if not parsed or not parsed.get("subtasks") or len(parsed["subtasks"]) < 2:
            return None

        subtasks = []
        for st in parsed["subtasks"]:
            subtasks.append(SmartSubtask(
                id=st.get("id", f"st-{len(subtasks)}"),
                description=st.get("description", ""),
                type=st.get("type", "implement"),
                complexity=st.get("complexity", 5),
                dependencies=st.get("dependencies", []),
                relevant_files=st.get("relevantFiles", []),
            ))

        # Build parallel groups from dependencies
        groups = _build_parallel_groups(subtasks)

        return SmartDecompositionResult(
            subtasks=subtasks,
            strategy=parsed.get("strategy", ""),
            reasoning=parsed.get("reasoning", ""),
            dependency_graph=DependencyGraph(parallel_groups=groups),
            llm_assisted=True,
        )
    except Exception as exc:
        logger.warning("Last resort decompose failed: %s", exc)
        return None


async def decompose_task(
    ctx: OrchestratorInternals,
    task: str,
) -> dict[str, Any]:
    """Full decomposition with three-tier fallback.

    1. Primary: decomposer.decompose() (if available)
    2. Last resort: simplified LLM prompt
    3. Emergency: deterministic 4-task fallback
    """
    result: SmartDecompositionResult | None = None
    failure_reason: str | None = None

    # Tier 1: Primary decomposer
    if ctx.decomposer:
        try:
            result = await ctx.decomposer.decompose(task)
            if result and len(result.subtasks) > 0:
                return {"result": result}
        except Exception as exc:
            failure_reason = str(exc)
            logger.warning("Primary decomposition failed: %s", exc)

    # Tier 2: Last resort
    try:
        result = await last_resort_decompose(ctx, task)
        if result and len(result.subtasks) >= 2:
            return {"result": result}
    except Exception as exc:
        failure_reason = failure_reason or str(exc)
        logger.warning("Last resort decomposition failed: %s", exc)

    # Tier 3: Emergency
    result = build_emergency_decomposition(ctx, task, failure_reason or "all decomposers failed")
    return {"result": result, "failure_reason": failure_reason}


# =============================================================================
# Planning
# =============================================================================


async def plan_execution(
    ctx: OrchestratorInternals,
    task: str,
    decomposition: SmartDecompositionResult,
) -> None:
    """LLM call to create execution plan with acceptance criteria."""
    model = (
        (ctx.config.hierarchy.manager.model if ctx.config.hierarchy.manager.model else None)
        or ctx.config.planner_model
        or ctx.config.orchestrator_model
    )

    subtask_descriptions = "\n".join(
        f"- {st.id}: {st.description} (type={st.type}, deps={st.dependencies})"
        for st in decomposition.subtasks
    )

    prompt = f"""Create an execution plan for this swarm task.

Task: {task}

Subtasks:
{subtask_descriptions}

Return JSON:
{{
  "acceptanceCriteria": [{{"taskId": "st-0", "criteria": ["criterion 1", ...]}}],
  "integrationTestPlan": {{
    "description": "...",
    "steps": [{{"description": "...", "command": "...", "expectedResult": "...", "required": true}}],
    "successCriteria": "..."
  }},
  "reasoning": "..."
}}"""

    try:
        response = await ctx.provider.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.3,
        )
        if ctx.track_orchestrator_usage:
            ctx.track_orchestrator_usage(response, "planning")

        parsed = parse_json(response.content)
        if parsed:
            criteria = []
            for ac in parsed.get("acceptanceCriteria", []):
                criteria.append(AcceptanceCriterion(
                    task_id=ac.get("taskId", ""),
                    criteria=ac.get("criteria", []),
                ))

            test_plan = None
            itp = parsed.get("integrationTestPlan")
            if itp:
                steps = []
                for s in itp.get("steps", []):
                    steps.append(IntegrationTestStep(
                        description=s.get("description", ""),
                        command=s.get("command", ""),
                        expected_result=s.get("expectedResult", ""),
                        required=s.get("required", True),
                    ))
                test_plan = IntegrationTestPlan(
                    description=itp.get("description", ""),
                    steps=steps,
                    success_criteria=itp.get("successCriteria", ""),
                )

            ctx.plan = SwarmPlan(
                acceptance_criteria=criteria,
                integration_test_plan=test_plan,
                reasoning=parsed.get("reasoning", ""),
            )

        ctx.emit(swarm_event(
            "swarm.plan.complete",
            criteria_count=len(ctx.plan.acceptance_criteria) if ctx.plan else 0,
            has_integration_plan=ctx.plan.integration_test_plan is not None if ctx.plan else False,
        ))

    except Exception as exc:
        logger.warning("Planning failed (non-fatal): %s", exc)


# =============================================================================
# Synthesis
# =============================================================================


async def synthesize_outputs(ctx: OrchestratorInternals) -> SynthesisResult | None:
    """Collect all completed task outputs and synthesize."""
    completed_tasks = [
        t for t in ctx.task_queue.get_all_tasks()
        if t.status == SwarmTaskStatus.COMPLETED and t.result
    ]

    if not completed_tasks:
        return None

    if ctx.synthesizer:
        try:
            outputs = [
                {"task_id": t.id, "description": t.description, "output": t.result.output}
                for t in completed_tasks
                if t.result
            ]
            return await ctx.synthesizer.synthesize(outputs)
        except Exception:
            pass

    # Fallback: simple concatenation
    findings = []
    for t in completed_tasks:
        if t.result and t.result.findings:
            findings.extend(t.result.findings)

    return SynthesisResult(
        summary=f"Completed {len(completed_tasks)} tasks",
        findings=findings,
    )


# =============================================================================
# Stats & Summary
# =============================================================================


def build_stats(ctx: OrchestratorInternals) -> SwarmExecutionStats:
    """Build execution statistics from current state."""
    stats = ctx.task_queue.get_stats()
    all_tasks = ctx.task_queue.get_all_tasks()

    total_duration = 0
    for t in all_tasks:
        if t.result:
            total_duration += t.result.duration_ms

    return SwarmExecutionStats(
        total_tasks=stats.total,
        completed_tasks=stats.completed,
        failed_tasks=stats.failed,
        skipped_tasks=stats.skipped,
        total_tokens=ctx.total_tokens,
        total_cost=ctx.total_cost,
        total_duration_ms=total_duration,
        quality_rejections=ctx.quality_rejections,
        retries=ctx.retries,
        waves_completed=ctx.task_queue.get_current_wave() + 1,
        orchestrator_tokens=ctx.orchestrator_tokens,
        orchestrator_cost=ctx.orchestrator_cost,
    )


def build_summary(ctx: OrchestratorInternals, stats: SwarmExecutionStats) -> str:
    """Build human-readable summary of execution."""
    lines = [
        f"Swarm Execution Summary",
        f"=" * 40,
        f"Tasks: {stats.completed_tasks}/{stats.total_tasks} completed",
        f"Failed: {stats.failed_tasks}, Skipped: {stats.skipped_tasks}",
        f"Waves: {stats.waves_completed}",
        f"Tokens: {stats.total_tokens:,} (orchestrator: {stats.orchestrator_tokens:,})",
        f"Cost: ${stats.total_cost:.4f} (orchestrator: ${stats.orchestrator_cost:.4f})",
        f"Quality rejections: {stats.quality_rejections}",
        f"Retries: {stats.retries}",
    ]

    # Artifact inventory
    if ctx.artifact_inventory and ctx.artifact_inventory.files:
        lines.append("")
        lines.append("Artifacts:")
        for f in ctx.artifact_inventory.files[:15]:
            size_kb = f.size_bytes / 1024
            lines.append(f"  {f.path} ({size_kb:.1f}KB)")
        if len(ctx.artifact_inventory.files) > 15:
            lines.append(f"  ... and {len(ctx.artifact_inventory.files) - 15} more files")

    return "\n".join(lines)


def build_error_result(
    ctx: OrchestratorInternals,
    message: str,
) -> SwarmExecutionResult:
    """Build a failed execution result."""
    return SwarmExecutionResult(
        success=False,
        summary=f"Swarm failed: {message}",
        errors=[{"phase": str(ctx.current_phase), "message": message}],
    )


# =============================================================================
# Foundation Tasks
# =============================================================================


def detect_foundation_tasks(ctx: OrchestratorInternals) -> None:
    """Mark tasks that are depended upon by 2+ other tasks as foundation tasks.

    Foundation tasks get +1 retry and relaxed quality threshold (-1).
    """
    all_tasks = ctx.task_queue.get_all_tasks()
    dep_counts: dict[str, int] = {}

    for task in all_tasks:
        for dep_id in task.dependencies:
            dep_counts[dep_id] = dep_counts.get(dep_id, 0) + 1

    for task in all_tasks:
        if dep_counts.get(task.id, 0) >= 2:
            task.is_foundation = True


# =============================================================================
# Artifact Inventory
# =============================================================================


def build_artifact_inventory(ctx: OrchestratorInternals) -> ArtifactInventory:
    """Post-execution filesystem audit of all artifacts."""
    all_tasks = ctx.task_queue.get_all_tasks()
    seen_paths: set[str] = set()
    files: list[ArtifactFile] = []

    for task in all_tasks:
        paths: list[str] = []
        if task.target_files:
            paths.extend(task.target_files)
        if task.read_files:
            paths.extend(task.read_files)
        if task.result and task.result.files_modified:
            paths.extend(task.result.files_modified)

        for path in paths:
            if path in seen_paths:
                continue
            seen_paths.add(path)

            try:
                stat = os.stat(path)
                if stat.st_size > 0:
                    files.append(ArtifactFile(
                        path=path,
                        size_bytes=stat.st_size,
                        exists=True,
                    ))
            except OSError:
                pass

    total_bytes = sum(f.size_bytes for f in files)
    return ArtifactInventory(
        files=files,
        total_files=len(files),
        total_bytes=total_bytes,
    )


# =============================================================================
# Persistence
# =============================================================================


def save_checkpoint(ctx: OrchestratorInternals, label: str) -> None:
    """Save a checkpoint of current swarm state."""
    if not ctx.config.enable_persistence or not ctx.state_store:
        return

    try:
        checkpoint_state = ctx.task_queue.get_checkpoint_state()
        ctx.emit(swarm_event(
            "swarm.state.checkpoint",
            session_id=ctx.config.resume_session_id or "",
            wave=ctx.task_queue.get_current_wave(),
        ))
    except Exception as exc:
        logger.warning("Checkpoint save failed: %s", exc)


# =============================================================================
# Skip & Budget Helpers
# =============================================================================


def skip_remaining_tasks(ctx: OrchestratorInternals, reason: str) -> None:
    """Skip all pending and ready tasks."""
    for task in ctx.task_queue.get_all_tasks():
        if task.status in (SwarmTaskStatus.PENDING, SwarmTaskStatus.READY):
            task.status = SwarmTaskStatus.SKIPPED
            ctx.emit(swarm_event(
                "swarm.task.skipped",
                task_id=task.id,
                reason=reason,
            ))


def emit_budget_update(ctx: OrchestratorInternals) -> None:
    """Emit a budget update event."""
    ctx.emit(swarm_event(
        "swarm.budget.update",
        tokens_used=ctx.total_tokens + ctx.orchestrator_tokens,
        tokens_total=ctx.config.total_budget,
        cost_used=ctx.total_cost + ctx.orchestrator_cost,
        cost_total=ctx.config.max_cost,
    ))


def get_effective_retries(ctx: OrchestratorInternals, task: SwarmTask) -> int:
    """Get effective retry count for a task."""
    if isinstance(task, FixupTask):
        return 2
    if task.is_foundation:
        return ctx.config.worker_retries + 1
    return ctx.config.worker_retries


def get_swarm_progress_summary(ctx: OrchestratorInternals) -> str:
    """Human-readable summary of completed tasks for retry context."""
    completed = [
        t for t in ctx.task_queue.get_all_tasks()
        if t.status == SwarmTaskStatus.COMPLETED
    ]

    if not completed:
        return "No tasks completed yet."

    lines = [f"Completed {len(completed)} tasks:"]
    for t in completed:
        score = f" (quality: {t.result.quality_score})" if t.result and t.result.quality_score else ""
        files = ""
        if t.result and t.result.files_modified:
            files = f" → {', '.join(t.result.files_modified[:3])}"
        lines.append(f"  - {t.description}{score}{files}")

    return "\n".join(lines)


# =============================================================================
# JSON Parsing
# =============================================================================


def parse_json(content: str) -> dict[str, Any] | None:
    """Extract JSON from LLM response, handling markdown code blocks."""
    if not content:
        return None

    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in content
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(content[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


# =============================================================================
# Parallel Group Builder
# =============================================================================


def _build_parallel_groups(subtasks: list[SmartSubtask]) -> list[list[str]]:
    """Build wave groups from subtask dependencies."""
    if not subtasks:
        return []

    # Topological sort into waves
    task_ids = {st.id for st in subtasks}
    dep_map = {st.id: [d for d in st.dependencies if d in task_ids] for st in subtasks}
    assigned_wave: dict[str, int] = {}

    def get_wave(task_id: str, visited: set[str] | None = None) -> int:
        if task_id in assigned_wave:
            return assigned_wave[task_id]
        if visited is None:
            visited = set()
        if task_id in visited:
            return 0  # Cycle protection
        visited.add(task_id)

        deps = dep_map.get(task_id, [])
        if not deps:
            assigned_wave[task_id] = 0
            return 0

        max_dep_wave = max(get_wave(d, visited) for d in deps)
        wave = max_dep_wave + 1
        assigned_wave[task_id] = wave
        return wave

    for st in subtasks:
        get_wave(st.id)

    # Group by wave
    max_wave = max(assigned_wave.values()) if assigned_wave else 0
    groups: list[list[str]] = []
    for w in range(max_wave + 1):
        group = [tid for tid, wave in assigned_wave.items() if wave == w]
        if group:
            groups.append(group)

    return groups
