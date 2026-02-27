"""SwarmOrchestrator — AoT-based shared-workspace orchestration.

Replaces HybridCoordinator for ``workspace_mode: shared``.  The old
``HybridCoordinator`` in ``loop.py`` is preserved for backward-compat
(``workspace_mode: worktree``).

Hierarchy:
    Level 0: CLI entry (cli.py)
    Level 1: SwarmOrchestrator — owns AoT DAG, AST Service, File Ledger, Budget
    Level 2: SubagentManager — semaphore-gated batch execution
    Level 3: Workers — scoped to specific files, writes through OCC
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from attoswarm.config.schema import SwarmYamlConfig
from attoswarm.coordinator.aot_graph import AoTGraph, AoTNode
from attoswarm.coordinator.budget import BudgetCounter
from attoswarm.coordinator.event_bus import EventBus, SwarmEvent
from attoswarm.coordinator.subagent_manager import SubagentManager, TaskResult
from attoswarm.protocol.io import write_json_atomic
from attoswarm.protocol.models import (
    SwarmManifest,
    SwarmState,
    TaskSpec,
    default_run_layout,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class SwarmOrchestrator:
    """AoT-based orchestrator using shared workspace + OCC.

    Main loop:
    1. Initialize AST service (full scan).
    2. Decompose goal into AoT DAG (LLM + AST annotation).
    3. For each DAG level:
       a. Get ready batch.
       b. Check parallel safety (AST conflicts).
       c. Execute batch via SubagentManager.
       d. Post-level: update AST, reconcile, advance DAG.
    4. Synthesize final result.
    """

    def __init__(
        self,
        config: SwarmYamlConfig,
        goal: str,
        *,
        resume: bool = False,
        decompose_fn: Callable[..., Any] | None = None,
        spawn_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._goal = goal
        self._resume = resume
        self._decompose_fn = decompose_fn

        # Unique run ID
        self._run_id = str(uuid.uuid4())[:8]
        wd = config.run.working_dir or "."
        self._root_dir = os.path.abspath(wd)
        self._run_dir = Path(config.run.run_dir)
        self._internal_dir = self._run_dir / f"run-{self._run_id}"
        self._layout = default_run_layout(self._run_dir)

        # Core components (lazy-initialized in run())
        self._ast_service: Any = None
        self._file_ledger: Any = None
        self._aot_graph = AoTGraph()
        self._reconciler: Any = None
        self._event_bus = EventBus(
            persist_path=str(self._layout["events"]),
        )
        self._budget = BudgetCounter(
            max_tokens=config.budget.max_tokens,
            max_cost_usd=config.budget.max_cost_usd,
        )
        self._subagent_mgr = SubagentManager(
            max_concurrency=config.workspace.max_concurrent_writers,
            spawn_fn=spawn_fn,
        )

        # State
        self._phase = "init"
        self._start_time = 0.0
        self._state_seq = 0
        self._manifest: SwarmManifest | None = None
        self._tasks: dict[str, TaskSpec] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def budget(self) -> BudgetCounter:
        return self._budget

    @property
    def aot_graph(self) -> AoTGraph:
        return self._aot_graph

    async def run(self) -> int:
        """Execute the full orchestration loop.

        Returns the number of successfully completed tasks.
        """
        self._start_time = time.time()
        self._setup_directories()
        self._phase = "initializing"

        # 1. Initialize AST service
        self._emit("info", message="Initializing AST service...")
        self._init_ast_service()

        # 2. Initialize File Ledger
        self._init_file_ledger()

        # Wire ledger + AST into subagent manager
        self._subagent_mgr._file_ledger = self._file_ledger
        self._subagent_mgr._ast_service = self._ast_service

        # 3. Decompose goal into tasks
        self._phase = "decomposing"
        self._emit("info", message=f"Decomposing goal: {self._goal[:100]}")
        tasks = await self._decompose_goal()
        if not tasks:
            self._emit("fail", message="Decomposition produced no tasks")
            return 0

        # Build AoT DAG
        for task in tasks:
            self._tasks[task.task_id] = task
            self._aot_graph.add_task(AoTNode(
                task_id=task.task_id,
                depends_on=list(task.deps),
                target_files=list(task.target_files),
                symbol_scope=list(task.symbol_scope),
            ))
        self._aot_graph.compute_levels()
        execution_order = self._aot_graph.get_execution_order()

        self._emit("info", message=f"DAG: {len(tasks)} tasks, {len(execution_order)} levels")

        # Build manifest
        self._manifest = SwarmManifest(
            run_id=self._run_id,
            goal=self._goal,
            tasks=list(self._tasks.values()),
        )
        self._persist_state()

        # 4. Execute levels
        self._phase = "executing"
        completed = 0
        for level_idx, batch_ids in enumerate(execution_order):
            self._emit(
                "info",
                message=f"Level {level_idx}: {len(batch_ids)} tasks",
            )

            # Get ready tasks
            ready = self._aot_graph.get_ready_batch()
            if not ready:
                self._emit("info", message=f"Level {level_idx}: no ready tasks, skipping")
                continue

            # Check parallel safety
            conflicts = self._aot_graph.check_parallel_safety(ready, self._ast_service)
            parallel, serialized = self._split_by_conflicts(ready, conflicts)

            # Snapshot files for parallel tasks
            for tid in parallel:
                task = self._tasks.get(tid)
                if task and self._file_ledger:
                    for f in task.target_files:
                        abs_path = os.path.join(self._root_dir, f)
                        if Path(abs_path).exists():
                            try:
                                ver = await self._file_ledger.snapshot_file(f, f"agent-{tid}")
                                task.file_version_snapshot[f] = ver.version_hash
                            except Exception:
                                pass

            # Execute parallel batch
            if parallel:
                for tid in parallel:
                    self._aot_graph.mark_running(tid)
                    self._emit("spawn", task_id=tid, message=f"Spawning worker for {tid}")
                self._persist_state()

                batch_tasks = [self._task_to_dict(tid) for tid in parallel]
                results = await self._subagent_mgr.execute_batch(batch_tasks)

                for result in results:
                    completed += self._handle_result(result)
                self._persist_state()

            # Execute serialized tasks one by one
            for tid in serialized:
                self._aot_graph.mark_running(tid)
                self._emit("spawn", task_id=tid, message=f"Spawning worker for {tid} (serialized)")
                self._persist_state()

                task_dict = self._task_to_dict(tid)
                result = await self._subagent_mgr.execute_single(task_dict)
                completed += self._handle_result(result)
                self._persist_state()

            # Post-level: refresh AST index
            if self._ast_service:
                try:
                    self._ast_service.refresh()
                except Exception:
                    pass

        # 5. Finalize
        self._phase = "completed"
        elapsed = time.time() - self._start_time
        summary = self._aot_graph.summary()
        self._emit(
            "complete",
            message=f"Swarm complete: {completed}/{len(tasks)} tasks in {elapsed:.1f}s",
            data=summary,
        )
        self._persist_state()

        return completed

    def get_state(self) -> dict[str, Any]:
        """Return a state snapshot for TUI consumption."""
        return {
            "run_id": self._run_id,
            "phase": self._phase,
            "goal": self._goal,
            "tasks": {
                tid: {
                    "title": t.title,
                    "status": self._aot_graph.get_node(tid).status if self._aot_graph.get_node(tid) else t.status,
                    "target_files": t.target_files,
                }
                for tid, t in self._tasks.items()
            },
            "dag_summary": self._aot_graph.summary(),
            "budget": {
                "tokens_used": self._budget.tokens_used,
                "cost_usd": self._budget.cost_used,
            },
            "elapsed_s": time.time() - self._start_time if self._start_time else 0,
            "active_agents": [
                {"agent_id": a.agent_id, "task_id": a.task_id, "status": a.status}
                for a in self._subagent_mgr.get_all_agents()
            ],
            "events": [
                {"type": e.event_type, "message": e.message, "timestamp": e.timestamp}
                for e in self._event_bus.recent(20)
            ],
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _persist_state(self) -> None:
        """Write state snapshot to disk for TUI consumption."""
        self._state_seq += 1

        # Build dag edges from task deps
        dag_edges: list[list[str]] = []
        for tid, task in self._tasks.items():
            for dep in task.deps:
                dag_edges.append([dep, tid])

        # Build dag nodes with status from AoT graph
        dag_nodes: list[dict[str, Any]] = []
        for tid, task in self._tasks.items():
            node = self._aot_graph.get_node(tid)
            status = node.status if node else task.status
            dag_nodes.append({
                "task_id": tid,
                "title": task.title,
                "status": status,
            })

        # All agents from subagent manager (not just running)
        active_agents: list[dict[str, Any]] = [
            {
                "agent_id": a.agent_id,
                "task_id": a.task_id,
                "status": a.status,
                "tokens_used": a.tokens_used,
                "started_at_epoch": a.started_at,
            }
            for a in self._subagent_mgr.get_all_agents()
        ]

        state: dict[str, Any] = {
            "run_id": self._run_id,
            "phase": self._phase,
            "updated_at": utc_now_iso(),
            "dag": {"nodes": dag_nodes, "edges": dag_edges},
            "active_agents": active_agents,
            "budget": self._budget.as_dict(),
            "dag_summary": self._aot_graph.summary(),
            "elapsed_s": time.time() - self._start_time if self._start_time else 0,
            "state_seq": self._state_seq,
            "merge_queue": {},
            "attempts": {},
        }

        try:
            write_json_atomic(self._layout["state"], state)
        except Exception as exc:
            logger.warning("Failed to persist state: %s", exc)

    def _setup_directories(self) -> None:
        for key, path in self._layout.items():
            if key in ("manifest", "state", "events"):
                path.parent.mkdir(parents=True, exist_ok=True)
            else:
                path.mkdir(parents=True, exist_ok=True)
        # Internal dir for ledger persistence etc.
        self._internal_dir.mkdir(parents=True, exist_ok=True)

    def _init_ast_service(self) -> None:
        try:
            from attocode.integrations.context.ast_service import ASTService
            self._ast_service = ASTService.get_instance(self._root_dir)
            if not self._ast_service.initialized:
                self._ast_service.initialize()
        except Exception as exc:
            logger.warning("AST service init failed: %s", exc)
            self._ast_service = None

    def _init_file_ledger(self) -> None:
        try:
            from attoswarm.workspace.file_ledger import FileLedger
            persist_dir = str(self._internal_dir / "ledger")
            self._file_ledger = FileLedger(
                root_dir=self._root_dir,
                ast_service=self._ast_service,
                persist_dir=persist_dir,
            )
        except Exception as exc:
            logger.warning("File ledger init failed: %s", exc)
            self._file_ledger = None

    async def _decompose_goal(self) -> list[TaskSpec]:
        """Decompose the goal into tasks.

        Uses the provided ``decompose_fn`` or falls back to a single task.
        """
        if self._decompose_fn:
            try:
                result = await self._decompose_fn(
                    self._goal,
                    ast_service=self._ast_service,
                    config=self._config,
                )
                if isinstance(result, list):
                    return result
            except Exception as exc:
                logger.warning("Decomposition failed: %s", exc)
                self._emit(
                    "warning",
                    message=f"LLM decomposition failed ({exc}), falling back to single task",
                )

        # Fallback: single task
        self._emit("info", message="Using single-task fallback (no LLM decomposer available)")
        return [TaskSpec(
            task_id="task-1",
            title=self._goal[:100],
            description=self._goal,
            target_files=[],
        )]

    def _task_to_dict(self, task_id: str) -> dict[str, Any]:
        """Convert a TaskSpec to a dict for SubagentManager."""
        task = self._tasks[task_id]
        return {
            "task_id": task.task_id,
            "title": task.title,
            "description": task.description,
            "target_files": task.target_files,
            "read_files": task.read_files,
            "file_version_snapshot": task.file_version_snapshot,
            "symbol_scope": task.symbol_scope,
            "role_hint": task.role_hint,
            "task_kind": task.task_kind,
        }

    def _handle_result(self, result: TaskResult) -> int:
        """Process a task result.  Returns 1 if successful, 0 otherwise."""
        task = self._tasks.get(result.task_id)
        if task:
            task.files_modified = result.files_modified
            task.result_summary = result.result_summary

        if result.success:
            self._aot_graph.mark_complete(result.task_id)
            self._emit("complete", task_id=result.task_id,
                        message=f"Task {result.task_id} completed",
                        data={"files_modified": result.files_modified})
            return 1
        else:
            skipped = self._aot_graph.mark_failed(result.task_id)
            self._emit("fail", task_id=result.task_id,
                        message=f"Task {result.task_id} failed: {result.error}",
                        data={"skipped": skipped})
            if skipped:
                self._emit("skip", message=f"Cascade-skipped: {skipped}")
            return 0

    def _split_by_conflicts(
        self,
        batch: list[str],
        conflicts: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        """Split a batch into parallel-safe and must-serialize sets."""
        if not conflicts:
            return batch, []

        # Collect task IDs involved in conflicts
        conflicting: set[str] = set()
        for c in conflicts:
            if "task_a" in c:
                conflicting.add(c["task_a"])
            if "task_b" in c:
                conflicting.add(c["task_b"])

        parallel = [tid for tid in batch if tid not in conflicting]
        serialized = [tid for tid in batch if tid in conflicting]
        return parallel, serialized

    def _emit(
        self,
        event_type: str,
        task_id: str = "",
        agent_id: str = "",
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        self._event_bus.emit(SwarmEvent(
            event_type=event_type,
            task_id=task_id,
            agent_id=agent_id,
            message=message,
            data=data or {},
        ))
