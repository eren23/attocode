"""Swarm task queue with wave scheduling and dependency tracking."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from attocode.integrations.swarm.types import (
    FAILURE_MODE_THRESHOLDS,
    DependencyGraph,
    FileConflictStrategy,
    FixupTask,
    PartialContext,
    ResourceConflict,
    SmartDecompositionResult,
    SmartSubtask,
    SubtaskType,
    SwarmConfig,
    SwarmQueueStats,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    TaskCheckpointState,
    TaskFailureMode,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Terminal statuses — tasks in these states are finished
# =============================================================================

_TERMINAL_STATUSES: frozenset[SwarmTaskStatus] = frozenset({
    SwarmTaskStatus.COMPLETED,
    SwarmTaskStatus.FAILED,
    SwarmTaskStatus.SKIPPED,
    SwarmTaskStatus.DECOMPOSED,
})

_DEP_SATISFIED_STATUSES: frozenset[SwarmTaskStatus] = frozenset({
    SwarmTaskStatus.COMPLETED,
    SwarmTaskStatus.DECOMPOSED,
})


# =============================================================================
# Free function
# =============================================================================


def get_effective_threshold(
    failed_deps: list[SwarmTask],
    configured_threshold: float,
) -> float:
    """Get the effective partial dependency threshold based on failure modes.

    Scans all failed dependencies for their ``failure_mode``, picks the minimum
    threshold among them from :data:`FAILURE_MODE_THRESHOLDS`, and returns
    ``min(all_mode_thresholds, configured_threshold)``.
    """
    if not failed_deps:
        return configured_threshold

    mode_thresholds: list[float] = []
    for dep in failed_deps:
        if dep.failure_mode is not None:
            mode_key = dep.failure_mode.value
            threshold = FAILURE_MODE_THRESHOLDS.get(mode_key)
            if threshold is not None:
                mode_thresholds.append(threshold)

    if not mode_thresholds:
        return configured_threshold

    return min(min(mode_thresholds), configured_threshold)


# =============================================================================
# SwarmTaskQueue
# =============================================================================


class SwarmTaskQueue:
    """Priority queue with wave-based scheduling and dependency tracking.

    Tasks are organised into waves (execution rounds).  A wave's tasks can
    execute in parallel once all their dependencies from previous waves are
    satisfied.  The queue tracks resource conflicts and supports cascade-skip
    on failure, partial-dependency execution, and artifact-aware skip avoidance.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, working_directory: str | None = None) -> None:
        self.tasks: dict[str, SwarmTask] = {}
        self.waves: list[list[str]] = []
        self.current_wave: int = 0
        self.partial_dependency_threshold: float = 0.5
        self.artifact_aware_skip: bool = True
        self.working_directory: str = working_directory or os.getcwd()
        self._conflicts: list[ResourceConflict] = []
        self._on_cascade_skip: Callable[[str, list[str]], None] | None = None

    # ------------------------------------------------------------------
    # Loading / initialisation
    # ------------------------------------------------------------------

    def load_from_decomposition(
        self,
        result: SmartDecompositionResult,
        config: SwarmConfig,
    ) -> None:
        """Convert a decomposition result into the internal queue state."""
        self.partial_dependency_threshold = config.partial_dependency_threshold
        self.artifact_aware_skip = config.artifact_aware_skip
        self.tasks.clear()
        self.waves.clear()
        self.current_wave = 0

        dep_graph: DependencyGraph = result.dependency_graph

        # Detect file conflicts -------------------------------------------------
        self._conflicts = list(dep_graph.conflicts)

        # AST-based conflict detection: if an AST service is available,
        # detect additional conflicts between tasks with overlapping files
        ast_conflicts = self._detect_ast_conflicts(result.subtasks, config)
        if ast_conflicts:
            self._conflicts.extend(ast_conflicts)

        # Serialise conflicting tasks if configured ---------------------------
        if (
            config.file_conflict_strategy == FileConflictStrategy.SERIALIZE
            and self._conflicts
        ):
            self._serialize_conflicts(result, self._conflicts)

        # Build task objects from subtasks ------------------------------------
        parallel_groups: list[list[str]] = dep_graph.parallel_groups
        subtask_map: dict[str, SmartSubtask] = {s.id: s for s in result.subtasks}

        # Assign waves via parallel_groups ------------------------------------
        id_to_wave: dict[str, int] = {}
        for wave_idx, group in enumerate(parallel_groups):
            for task_id in group:
                id_to_wave[task_id] = wave_idx

        # Fallback: any subtask not mentioned in parallel_groups gets wave 0
        for sub in result.subtasks:
            if sub.id not in id_to_wave:
                id_to_wave[sub.id] = 0

        # Identify foundation tasks (3+ dependents) --------------------------
        dependent_count: dict[str, int] = {}
        for sub in result.subtasks:
            for dep_id in sub.dependencies:
                dependent_count[dep_id] = dependent_count.get(dep_id, 0) + 1

        for sub in result.subtasks:
            wave = id_to_wave.get(sub.id, 0)
            is_foundation = dependent_count.get(sub.id, 0) >= 3
            task = SwarmTask(
                id=sub.id,
                description=sub.description,
                type=SubtaskType(sub.type) if sub.type in SubtaskType.__members__.values() else SubtaskType.IMPLEMENT,
                dependencies=list(sub.dependencies),
                status=SwarmTaskStatus.PENDING,
                complexity=sub.complexity,
                wave=wave,
                target_files=list(sub.target_files) if sub.target_files else None,
                read_files=list(sub.read_files) if sub.read_files else None,
                relevant_files=list(sub.relevant_files) if sub.relevant_files else None,
                is_foundation=is_foundation,
                original_subtask={
                    "id": sub.id,
                    "description": sub.description,
                    "type": sub.type,
                    "complexity": sub.complexity,
                    "dependencies": list(sub.dependencies),
                },
            )
            self.tasks[task.id] = task

        self._rebuild_waves()
        self._update_ready_status()

    # ------------------------------------------------------------------
    # Ready task queries
    # ------------------------------------------------------------------

    def get_ready_tasks(self) -> list[SwarmTask]:
        """Return tasks from the *current* wave that are ready for dispatch."""
        now = time.time()
        if self.current_wave >= len(self.waves):
            return []
        wave_ids = self.waves[self.current_wave]
        ready: list[SwarmTask] = []
        for tid in wave_ids:
            task = self.tasks.get(tid)
            if task is None:
                continue
            if task.status != SwarmTaskStatus.READY:
                continue
            if task.retry_after is not None and task.retry_after > now:
                continue
            ready.append(task)
        return ready

    def get_all_ready_tasks(self) -> list[SwarmTask]:
        """Return ready tasks across *all* waves, sorted by wave then complexity desc."""
        now = time.time()
        ready: list[SwarmTask] = []
        for task in self.tasks.values():
            if task.status != SwarmTaskStatus.READY:
                continue
            if task.retry_after is not None and task.retry_after > now:
                continue
            ready.append(task)
        ready.sort(key=lambda t: (t.wave, -t.complexity))
        return ready

    # ------------------------------------------------------------------
    # Retry timing
    # ------------------------------------------------------------------

    def set_retry_after(self, task_id: str, delay_ms: int) -> None:
        """Set a task's retry-after timestamp."""
        task = self.tasks.get(task_id)
        if task is not None:
            task.retry_after = time.time() + delay_ms / 1000.0

    # ------------------------------------------------------------------
    # Cascade callback
    # ------------------------------------------------------------------

    def set_on_cascade_skip(
        self,
        callback: Callable[[str, list[str]], None] | None,
    ) -> None:
        """Register a callback invoked on cascade-skip events.

        The callback receives ``(failed_task_id, list_of_skipped_ids)``.
        """
        self._on_cascade_skip = callback

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def mark_dispatched(self, task_id: str, model: str) -> None:
        """Transition a task to DISPATCHED."""
        task = self.tasks.get(task_id)
        if task is None:
            return
        task.status = SwarmTaskStatus.DISPATCHED
        task.assigned_model = model
        task.attempts += 1
        task.dispatched_at = time.time()

    def mark_completed(self, task_id: str, result: SwarmTaskResult) -> None:
        """Transition a task to COMPLETED and propagate readiness."""
        task = self.tasks.get(task_id)
        if task is None:
            return
        task.status = SwarmTaskStatus.COMPLETED
        task.result = result
        task.pending_cascade_skip = False
        self._update_ready_status()

    def mark_failed(self, task_id: str, max_retries: int) -> bool:
        """Mark a task as failed, retrying if budget remains.

        Returns ``True`` if the task was reset for retry, ``False`` if it
        exhausted retries and was marked FAILED (triggering cascade skip).
        """
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if task.attempts <= max_retries:
            task.status = SwarmTaskStatus.READY
            return True
        task.status = SwarmTaskStatus.FAILED
        self._cascade_skip(task_id)
        return False

    def mark_failed_without_cascade(self, task_id: str, max_retries: int) -> bool:
        """Same retry logic as :meth:`mark_failed` but without cascade skip.

        The caller is responsible for manually triggering cascade via
        :meth:`trigger_cascade_skip` if needed.
        """
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if task.attempts <= max_retries:
            task.status = SwarmTaskStatus.READY
            return True
        task.status = SwarmTaskStatus.FAILED
        return False

    def trigger_cascade_skip(self, task_id: str) -> None:
        """Manually trigger cascade-skip from *task_id*."""
        self._cascade_skip(task_id)

    # ------------------------------------------------------------------
    # Un-skip & rescue
    # ------------------------------------------------------------------

    def un_skip_dependents(self, task_id: str) -> None:
        """Restore skipped dependents whose deps are now all satisfied."""
        for task in self.tasks.values():
            if task.status != SwarmTaskStatus.SKIPPED:
                continue
            if task_id not in task.dependencies:
                continue
            # Check if *all* deps are now satisfied
            all_met = all(
                self.tasks.get(d) is not None
                and self.tasks[d].status in _DEP_SATISFIED_STATUSES
                for d in task.dependencies
            )
            if all_met:
                task.status = SwarmTaskStatus.READY
                task.dependency_context = self._build_dependency_context(task)

    def rescue_task(self, task_id: str, rescue_context: str = "") -> bool:
        """Rescue a SKIPPED task, making it READY with extra context.

        Returns True if the task was successfully rescued, False otherwise.
        """
        task = self.tasks.get(task_id)
        if task is None:
            return False
        if task.status != SwarmTaskStatus.SKIPPED:
            return False
        task.status = SwarmTaskStatus.READY
        if rescue_context:
            task.rescue_context = rescue_context
        task.dependency_context = self._build_dependency_context(task)
        return True

    # ------------------------------------------------------------------
    # Decomposition / replacement
    # ------------------------------------------------------------------

    def replace_with_subtasks(
        self,
        original_task_id: str,
        subtasks: list[SwarmTask],
    ) -> None:
        """Replace *original_task_id* with finer-grained subtasks."""
        original = self.tasks.get(original_task_id)
        if original is None:
            return

        original.status = SwarmTaskStatus.DECOMPOSED
        original.subtask_ids = [s.id for s in subtasks]

        target_wave = original.wave
        for sub in subtasks:
            sub.wave = target_wave
            sub.parent_task_id = original_task_id
            self.tasks[sub.id] = sub

        # Rewire dependencies: anything depending on the original now depends
        # on *all* subtask IDs.
        subtask_id_set = {s.id for s in subtasks}
        for task in self.tasks.values():
            if original_task_id in task.dependencies:
                task.dependencies.remove(original_task_id)
                task.dependencies.extend(
                    sid for sid in subtask_id_set if sid not in task.dependencies
                )

        self._rebuild_waves()
        self._update_ready_status()

    # ------------------------------------------------------------------
    # Wave management
    # ------------------------------------------------------------------

    def is_current_wave_complete(self) -> bool:
        """Check whether every task in the current wave is terminal."""
        if self.current_wave >= len(self.waves):
            return True
        for tid in self.waves[self.current_wave]:
            task = self.tasks.get(tid)
            if task is not None and task.status not in _TERMINAL_STATUSES:
                return False
        return True

    def advance_wave(self) -> bool:
        """Move to the next wave. Returns ``True`` if there are more waves."""
        self.current_wave += 1
        self._update_ready_status()
        return self.current_wave < len(self.waves)

    def is_complete(self) -> bool:
        """Check whether all tasks are in a terminal state."""
        for task in self.tasks.values():
            if task.status not in _TERMINAL_STATUSES:
                return False
        return True

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> SwarmTask | None:
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> dict[str, SwarmTask]:
        return dict(self.tasks)

    def get_current_wave(self) -> int:
        return self.current_wave

    def get_total_waves(self) -> int:
        return len(self.waves)

    def get_stats(self) -> SwarmQueueStats:
        """Compute queue statistics.  DECOMPOSED counts as completed."""
        stats = SwarmQueueStats(total=len(self.tasks))
        for task in self.tasks.values():
            if task.status == SwarmTaskStatus.READY:
                stats.ready += 1
            elif task.status == SwarmTaskStatus.DISPATCHED:
                stats.running += 1
            elif task.status in (
                SwarmTaskStatus.COMPLETED,
                SwarmTaskStatus.DECOMPOSED,
            ):
                stats.completed += 1
            elif task.status == SwarmTaskStatus.FAILED:
                stats.failed += 1
            elif task.status == SwarmTaskStatus.SKIPPED:
                stats.skipped += 1
        return stats

    def get_conflicts(self) -> list[ResourceConflict]:
        return list(self._conflicts)

    def get_skipped_tasks(self) -> list[SwarmTask]:
        return [t for t in self.tasks.values() if t.status == SwarmTaskStatus.SKIPPED]

    # ------------------------------------------------------------------
    # Checkpoint persistence
    # ------------------------------------------------------------------

    def get_checkpoint_state(self) -> dict[str, Any]:
        """Serialize the queue for persistence."""
        task_states: list[dict[str, Any]] = []
        for task in self.tasks.values():
            state = TaskCheckpointState(
                id=task.id,
                status=task.status.value,
                result=asdict(task.result) if task.result else None,
                attempts=task.attempts,
                wave=task.wave,
                assigned_model=task.assigned_model,
                dispatched_at=task.dispatched_at,
                description=task.description,
                type=task.type.value if isinstance(task.type, SubtaskType) else str(task.type),
                complexity=task.complexity,
                dependencies=list(task.dependencies),
                relevant_files=list(task.relevant_files) if task.relevant_files else None,
                is_foundation=task.is_foundation,
            )
            task_states.append(asdict(state))
        return {
            "tasks": task_states,
            "waves": [list(w) for w in self.waves],
            "current_wave": self.current_wave,
            "partial_dependency_threshold": self.partial_dependency_threshold,
            "artifact_aware_skip": self.artifact_aware_skip,
        }

    def restore_from_checkpoint(self, state: dict[str, Any]) -> None:
        """Restore the queue from a checkpoint dict."""
        self.tasks.clear()
        self.waves.clear()

        self.current_wave = state.get("current_wave", 0)
        self.partial_dependency_threshold = state.get(
            "partial_dependency_threshold", 0.5
        )
        self.artifact_aware_skip = state.get("artifact_aware_skip", True)

        for ts in state.get("tasks", []):
            result_data = ts.get("result")
            result_obj: SwarmTaskResult | None = None
            if result_data is not None:
                result_obj = SwarmTaskResult(
                    success=result_data.get("success", False),
                    output=result_data.get("output", ""),
                    closure_report=result_data.get("closure_report"),
                    quality_score=result_data.get("quality_score"),
                    quality_feedback=result_data.get("quality_feedback"),
                    tokens_used=result_data.get("tokens_used", 0),
                    cost_used=result_data.get("cost_used", 0.0),
                    duration_ms=result_data.get("duration_ms", 0),
                    files_modified=result_data.get("files_modified"),
                    findings=result_data.get("findings"),
                    tool_calls=result_data.get("tool_calls"),
                    model=result_data.get("model", ""),
                    degraded=result_data.get("degraded", False),
                    budget_utilization=result_data.get("budget_utilization"),
                )

            task_type_str = ts.get("type", "implement")
            try:
                task_type = SubtaskType(task_type_str)
            except ValueError:
                task_type = SubtaskType.IMPLEMENT

            task = SwarmTask(
                id=ts["id"],
                description=ts.get("description", ""),
                type=task_type,
                dependencies=ts.get("dependencies", []),
                status=SwarmTaskStatus(ts.get("status", "pending")),
                complexity=ts.get("complexity", 5),
                wave=ts.get("wave", 0),
                assigned_model=ts.get("assigned_model"),
                result=result_obj,
                attempts=ts.get("attempts", 0),
                dispatched_at=ts.get("dispatched_at"),
                relevant_files=ts.get("relevant_files"),
                is_foundation=ts.get("is_foundation", False),
            )
            self.tasks[task.id] = task

        self.waves = [list(w) for w in state.get("waves", [])]

        # Rebuild ready status for non-terminal tasks
        self._update_ready_status()

    # ------------------------------------------------------------------
    # Replan / fixup
    # ------------------------------------------------------------------

    def add_replan_tasks(
        self,
        subtasks: list[SmartSubtask],
        wave: int,
    ) -> list[SwarmTask]:
        """Add re-planned tasks into a specific wave with attempts=1."""
        added: list[SwarmTask] = []
        for sub in subtasks:
            task_type_str = sub.type
            try:
                task_type = SubtaskType(task_type_str)
            except ValueError:
                task_type = SubtaskType.IMPLEMENT

            task = SwarmTask(
                id=sub.id,
                description=sub.description,
                type=task_type,
                dependencies=list(sub.dependencies),
                status=SwarmTaskStatus.READY,
                complexity=sub.complexity,
                wave=wave,
                target_files=list(sub.target_files) if sub.target_files else None,
                read_files=list(sub.read_files) if sub.read_files else None,
                relevant_files=list(sub.relevant_files) if sub.relevant_files else None,
                attempts=1,
                rescue_context="Re-planned task from wave review",
            )
            self.tasks[task.id] = task
            added.append(task)

        self._rebuild_waves()
        self._update_ready_status()
        return added

    def add_fixup_tasks(self, tasks: list[FixupTask]) -> None:
        """Insert fixup tasks into the current wave."""
        for ft in tasks:
            ft.wave = self.current_wave
            ft.status = SwarmTaskStatus.READY
            self.tasks[ft.id] = ft

        self._rebuild_waves()
        self._update_ready_status()

    # ------------------------------------------------------------------
    # Stale dispatch reconciliation
    # ------------------------------------------------------------------

    def reconcile_stale_dispatched(
        self,
        stale_after_ms: int,
        now: float | None = None,
        active_task_ids: set[str] | None = None,
    ) -> list[str]:
        """Recover tasks stuck in DISPATCHED with no active worker.

        Returns a list of recovered task IDs.
        """
        now_ts = now if now is not None else time.time()
        stale_threshold = stale_after_ms / 1000.0
        recovered: list[str] = []

        for task in self.tasks.values():
            if task.status != SwarmTaskStatus.DISPATCHED:
                continue
            # Skip tasks with an active worker
            if active_task_ids and task.id in active_task_ids:
                continue
            # Check staleness
            if task.dispatched_at is None:
                continue
            elapsed = now_ts - task.dispatched_at
            if elapsed >= stale_threshold:
                task.status = SwarmTaskStatus.READY
                task.dispatched_at = None
                recovered.append(task.id)
                logger.info(
                    "Recovered stale task %s (dispatched %.1fs ago)",
                    task.id,
                    elapsed,
                )

        return recovered

    # ------------------------------------------------------------------
    # Private: wave building
    # ------------------------------------------------------------------

    def _rebuild_waves(self) -> None:
        """Rebuild the ``waves`` list from task wave assignments."""
        wave_map: dict[int, list[str]] = {}
        for task in self.tasks.values():
            wave_map.setdefault(task.wave, []).append(task.id)

        if not wave_map:
            self.waves = []
            return

        max_wave = max(wave_map)
        self.waves = [wave_map.get(i, []) for i in range(max_wave + 1)]

    # ------------------------------------------------------------------
    # Private: ready-status propagation
    # ------------------------------------------------------------------

    def _update_ready_status(self) -> None:
        """Promote PENDING tasks whose dependencies are all satisfied to READY."""
        for task in self.tasks.values():
            if task.status != SwarmTaskStatus.PENDING:
                continue
            if not task.dependencies:
                task.status = SwarmTaskStatus.READY
                continue

            all_deps_satisfied = all(
                self.tasks.get(d) is not None
                and self.tasks[d].status in _DEP_SATISFIED_STATUSES
                for d in task.dependencies
            )
            if all_deps_satisfied:
                task.status = SwarmTaskStatus.READY
                task.dependency_context = self._build_dependency_context(task)

    # ------------------------------------------------------------------
    # Private: cascade skip
    # ------------------------------------------------------------------

    def _cascade_skip(self, failed_task_id: str) -> None:
        """Cascade-skip downstream dependents of a failed task.

        Applies several heuristics before actually skipping:
        1. Artifact-aware skip avoidance
        2. Partial-dependency threshold
        3. Timeout lenience
        4. Pending cascade skip for dispatched tasks
        """
        failed_task = self.tasks.get(failed_task_id)
        if failed_task is None:
            return

        # Collect all transitive dependents via DFS
        to_visit: list[str] = [failed_task_id]
        visited: set[str] = set()
        dependents: list[str] = []

        while to_visit:
            current_id = to_visit.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            for task in self.tasks.values():
                if task.id == current_id or task.id in visited:
                    continue
                if task.status in _TERMINAL_STATUSES:
                    continue
                if current_id in task.dependencies:
                    dependents.append(task.id)
                    to_visit.append(task.id)

        skipped_ids: list[str] = []

        for dep_id in dependents:
            dep_task = self.tasks.get(dep_id)
            if dep_task is None or dep_task.status in _TERMINAL_STATUSES:
                continue

            # 1. Artifact-aware skip avoidance: if 50%+ of the failed task's
            #    target_files exist on disk, keep the dependent ready.
            if self.artifact_aware_skip and failed_task.target_files:
                existing = sum(
                    1
                    for f in failed_task.target_files
                    if os.path.isfile(os.path.join(self.working_directory, f))
                )
                if existing >= len(failed_task.target_files) * 0.5:
                    logger.info(
                        "Artifact-aware: keeping %s ready despite %s failure "
                        "(%d/%d target files exist)",
                        dep_id,
                        failed_task_id,
                        existing,
                        len(failed_task.target_files),
                    )
                    continue

            # 2. Partial-dependency threshold: if enough deps succeeded, run
            #    the task with partial context.
            total_deps = len(dep_task.dependencies)
            if total_deps > 1:
                completed_deps = [
                    d
                    for d in dep_task.dependencies
                    if self.tasks.get(d) is not None
                    and self.tasks[d].status in _DEP_SATISFIED_STATUSES
                ]
                failed_deps = [
                    self.tasks[d]
                    for d in dep_task.dependencies
                    if self.tasks.get(d) is not None
                    and self.tasks[d].status == SwarmTaskStatus.FAILED
                ]
                ratio = len(completed_deps) / total_deps
                threshold = get_effective_threshold(
                    failed_deps, self.partial_dependency_threshold
                )
                if ratio >= threshold:
                    dep_task.partial_context = PartialContext(
                        succeeded=[
                            self.tasks[d].description
                            for d in completed_deps
                            if d in [t.id for t in self.tasks.values()]
                        ],
                        failed=[
                            self.tasks[d].description
                            for d in dep_task.dependencies
                            if self.tasks.get(d) is not None
                            and self.tasks[d].status == SwarmTaskStatus.FAILED
                        ],
                        ratio=ratio,
                    )
                    dep_task.dependency_context = self._build_dependency_context(dep_task)
                    if dep_task.status == SwarmTaskStatus.PENDING:
                        dep_task.status = SwarmTaskStatus.READY
                    logger.info(
                        "Partial dep: %s runs with %.0f%% context (threshold %.0f%%)",
                        dep_id,
                        ratio * 100,
                        threshold * 100,
                    )
                    continue

            # 3. Timeout lenience: timeout failures keep dependents ready with
            #    partial context rather than skipping.
            if failed_task.failure_mode == TaskFailureMode.TIMEOUT:
                dep_task.partial_context = PartialContext(
                    succeeded=[],
                    failed=[failed_task.description],
                    ratio=0.0,
                )
                dep_task.dependency_context = self._build_dependency_context(dep_task)
                if dep_task.status == SwarmTaskStatus.PENDING:
                    dep_task.status = SwarmTaskStatus.READY
                logger.info(
                    "Timeout lenience: keeping %s ready despite %s timeout",
                    dep_id,
                    failed_task_id,
                )
                continue

            # 4. Pending cascade skip for already-dispatched tasks
            if dep_task.status == SwarmTaskStatus.DISPATCHED:
                dep_task.pending_cascade_skip = True
                logger.info(
                    "Pending cascade skip set for dispatched task %s",
                    dep_id,
                )
                continue

            # 5. Standard skip
            dep_task.status = SwarmTaskStatus.SKIPPED
            dep_task.failure_mode = TaskFailureMode.CASCADE
            skipped_ids.append(dep_id)
            logger.info(
                "Cascade skip: %s skipped due to %s failure",
                dep_id,
                failed_task_id,
            )

        if skipped_ids and self._on_cascade_skip is not None:
            self._on_cascade_skip(failed_task_id, skipped_ids)

    # ------------------------------------------------------------------
    # Private: dependency context building
    # ------------------------------------------------------------------

    def _build_dependency_context(self, task: SwarmTask) -> str:
        """Aggregate completed dependency outputs into a context string."""
        parts: list[str] = []
        for dep_id in task.dependencies:
            dep = self.tasks.get(dep_id)
            if dep is None:
                continue
            if dep.status not in _DEP_SATISFIED_STATUSES:
                continue
            if dep.result is not None and dep.result.output:
                parts.append(
                    f"=== Dependency [{dep.id}]: {dep.description} ===\n"
                    f"{dep.result.output}"
                )

        # Include partial context note if applicable
        if task.partial_context is not None:
            pc = task.partial_context
            if pc.failed:
                parts.append(
                    f"\n[WARNING] The following dependencies FAILED and their "
                    f"output is unavailable ({pc.ratio:.0%} deps succeeded):\n"
                    + "\n".join(f"  - {d}" for d in pc.failed)
                )

        # Include rescue context if applicable
        if task.rescue_context:
            parts.append(f"\n[RESCUE CONTEXT] {task.rescue_context}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Private: transitive dependency check
    # ------------------------------------------------------------------

    def _depends_on(self, task_id: str, potential_dep_id: str) -> bool:
        """Check whether *task_id* transitively depends on *potential_dep_id*.

        Uses DFS with cycle protection.
        """
        visited: set[str] = set()
        stack: list[str] = [task_id]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            task = self.tasks.get(current)
            if task is None:
                continue
            for dep_id in task.dependencies:
                if dep_id == potential_dep_id:
                    return True
                if dep_id not in visited:
                    stack.append(dep_id)
        return False

    # ------------------------------------------------------------------
    # Private: conflict serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_ast_conflicts(
        subtasks: list[SmartSubtask],
        config: SwarmConfig,
    ) -> list[ResourceConflict]:
        """Use AST service to detect conflicts between subtask file sets.

        If the AST service is available via ``config.codebase_context``,
        check each pair of subtasks in the same wave for symbol-level
        conflicts (both write to files that share symbols).
        """
        ast_svc = None
        if config.codebase_context and hasattr(config.codebase_context, "_ast_service"):
            ast_svc = config.codebase_context._ast_service
        if ast_svc is None or not hasattr(ast_svc, "detect_conflicts"):
            return []

        conflicts: list[ResourceConflict] = []
        try:
            # Check all pairs of subtasks that have target files
            tasks_with_files = [
                (s.id, s.target_files or [])
                for s in subtasks
                if s.target_files
            ]
            for i, (id_a, files_a) in enumerate(tasks_with_files):
                for id_b, files_b in tasks_with_files[i + 1:]:
                    detected = ast_svc.detect_conflicts(files_a, files_b)
                    for c in detected:
                        conflicts.append(ResourceConflict(
                            file_path=c.get("file", ""),
                            task_ids=[id_a, id_b],
                            conflict_type=c.get("type", "symbol-overlap"),
                        ))
        except Exception:
            pass  # Non-fatal — fall through to default conflict detection

        return conflicts

    @staticmethod
    def _serialize_conflicts(
        result: SmartDecompositionResult,
        conflicts: list[ResourceConflict],
    ) -> None:
        """Adjust parallel groups to serialise conflicting tasks.

        For each conflict, ensure that no two conflicting task IDs appear in
        the same parallel group.  Move later tasks to subsequent groups.
        """
        groups = result.dependency_graph.parallel_groups
        if not groups:
            return

        for conflict in conflicts:
            conflict_ids = set(conflict.task_ids)
            for group_idx, group in enumerate(groups):
                in_group = [tid for tid in group if tid in conflict_ids]
                if len(in_group) <= 1:
                    continue
                # Keep the first, move the rest to the next group
                to_move = in_group[1:]
                for tid in to_move:
                    group.remove(tid)
                    next_idx = group_idx + 1
                    if next_idx >= len(groups):
                        groups.append([])
                    groups[next_idx].append(tid)
