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

import asyncio
import logging
import os
import signal
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from attoswarm.coordinator.aot_graph import AoTGraph, AoTNode
from attoswarm.coordinator.budget import BudgetCounter
from attoswarm.coordinator.event_bus import EventBus, SwarmEvent
from attoswarm.coordinator.subagent_manager import SubagentManager, TaskResult
from attoswarm.protocol.io import write_json_atomic, write_json_fast
from attoswarm.protocol.models import (
    SwarmManifest,
    TaskSpec,
    default_run_layout,
    utc_now_iso,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from attoswarm.config.schema import SwarmYamlConfig

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
        trace_collector: Any = None,
        approval_mode: str = "auto",
    ) -> None:
        self._config = config
        self._goal = goal
        self._resume = resume
        self._decompose_fn = decompose_fn
        self._trace_collector = trace_collector
        self._approval_mode = approval_mode  # "auto" | "preview" | "dry_run"
        self._approved = False

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

        # Git safety + change manifest
        self._git_safety: Any = None
        self._change_manifest: Any = None

        # Code-intel (lazy-initialized)
        self._code_intel: Any = None
        self._learning_bridge: Any = None

        # Budget projection
        self._budget_projector: Any = None
        self._per_task_costs: list[float] = []

        # Trace bridge (EventBus → TraceCollector)
        self._trace_bridge: Any = None

        # Decision log (Workstream 2.4)
        self._decisions: list[dict[str, Any]] = []

        # Error tracking (Fix S1)
        self._errors: list[dict[str, Any]] = []

        # Task transition log (Fix S2)
        self._transition_log: list[dict[str, Any]] = []

        # Shutdown / pause
        self._shutdown_requested = False
        self._paused = False

        # State
        self._phase = "init"
        self._start_time = 0.0
        self._state_seq = 0
        self._manifest: SwarmManifest | None = None
        self._tasks: dict[str, TaskSpec] = {}
        self._task_attempts: dict[str, int] = {}
        self._task_attempt_history: dict[str, list[dict[str, Any]]] = {}
        self._control_cursor: int = 0  # line offset into control.jsonl

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

    def _request_shutdown(self) -> None:
        """Signal handler callback — request graceful shutdown."""
        self._shutdown_requested = True
        logger.info("Shutdown requested")

    async def run(self) -> int:
        """Execute the full orchestration loop.

        Returns the number of successfully completed tasks.
        """
        self._start_time = time.time()
        self._setup_directories()

        if not self._resume:
            self._archive_previous_run()

        self._phase = "initializing"
        self._persist_state()  # Early write — lets TUI detect subprocess start

        # Install signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._request_shutdown)
            except (NotImplementedError, OSError):
                pass  # Windows or non-main thread

        # 1. Initialize AST service
        self._emit("info", message="Initializing AST service...")
        self._init_ast_service()

        # 1b. Initialize code-intel service
        self._init_code_intel()

        # 1c. Initialize budget projector
        self._init_budget_projector()

        # 1d. Wire EventBus → TraceCollector bridge if collector available
        self._init_trace_bridge()

        # 2. Initialize File Ledger
        self._init_file_ledger()

        # Wire ledger + AST + trace dir into subagent manager
        self._subagent_mgr._file_ledger = self._file_ledger
        self._subagent_mgr._ast_service = self._ast_service
        self._subagent_mgr._trace_dir = str(self._layout["agents"])

        # 2b. Git safety config — deferred to after approval gate
        ws_cfg = getattr(self._config, 'workspace', None)

        # 2c. Initialize change manifest
        if ws_cfg and ws_cfg.change_manifest:
            try:
                from attoswarm.workspace.change_manifest import ChangeManifest
                self._change_manifest = ChangeManifest(str(self._run_dir))
            except Exception as exc:
                logger.warning("Change manifest init failed: %s", exc)

        # 2d. Bootstrap codebase context before decomposition
        bootstrap_ctx = self._bootstrap_context()

        # 3. Decompose goal into tasks
        self._phase = "decomposing"
        self._emit("info", message=f"Decomposing goal: {self._goal[:100]}")
        self._persist_state()  # Update phase to "decomposing" for TUI
        tasks = await self._decompose_goal(codebase_context=bootstrap_ctx)
        if not tasks:
            self._emit("fail", message="Decomposition produced no tasks")
            return 0
        self._record_decision("decomposing", "decomposition_complete",
                              f"Produced {len(tasks)} tasks", f"Goal complexity drove task count")

        # 3b. Enrich tasks with code-intel impact analysis
        tasks = self._enrich_tasks_with_impact(tasks)

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

        # Restore task states on resume
        if self._resume:
            self._restore_state()

        # Build and persist manifest
        self._manifest = SwarmManifest(
            run_id=self._run_id,
            goal=self._goal,
            tasks=list(self._tasks.values()),
        )
        self._persist_manifest()
        self._persist_state()

        # ── Approval gate ──
        # Skip approval on resume if execution had already started
        if self._resume:
            from attoswarm.protocol.io import read_json as _read_json
            prev_state = _read_json(self._layout["state"], default={})
            prev_phase = prev_state.get("phase", "")
            if prev_phase in ("executing", "completed", "shutdown"):
                self._approved = True

        if self._approval_mode == "dry_run":
            self._phase = "preview"
            self._emit("info", message=f"Dry run: {len(tasks)} tasks decomposed")
            self._persist_state()
            return 0

        if self._approval_mode == "preview":
            self._phase = "awaiting_approval"
            self._emit("info", message=f"Awaiting approval for {len(tasks)} tasks")
            self._persist_state()

            approval_timeout = 1800  # 30 min max wait
            approval_start = time.time()
            while not self._shutdown_requested and not self._approved:
                self._check_control_messages()
                await asyncio.sleep(1.0)
                if time.time() - approval_start > approval_timeout:
                    self._emit("warning", message="Approval timeout — shutting down")
                    self._request_shutdown()
                    break

            if self._shutdown_requested and not self._approved:
                self._phase = "rejected"
                self._emit("info", message="Execution rejected")
                self._persist_state()
                return 0
            self._emit("info", message="Execution approved — starting")

        # 3c. Initialize git safety net — deferred to after approval gate
        # so no branch is created for dry_run or rejected previews.
        if ws_cfg and ws_cfg.git_safety:
            try:
                from attoswarm.workspace.git_safety import GitSafetyNet
                self._git_safety = GitSafetyNet(self._root_dir, self._run_id, str(self._run_dir))
                git_state = await self._git_safety.setup()
                if git_state.is_git_repo:
                    self._emit("info", message=f"Git safety: branch={git_state.swarm_branch}, stash={'yes' if git_state.stash_ref else 'no'}")
            except Exception as exc:
                logger.warning("Git safety init failed: %s", exc)
                self._git_safety = None

        # 4. Execute batches (progress-based loop)
        #
        # A while loop replaces the old ``for level_idx, batch_ids in
        # enumerate(execution_order)`` loop which was bounded by the number
        # of DAG levels.  Retried tasks (reset to "pending") consumed a
        # level iteration, causing later levels to be silently skipped.
        #
        # The while loop keeps executing as long as get_ready_batch()
        # returns tasks.  A safety bound prevents infinite loops.
        self._phase = "executing"
        completed = 0
        batch_num = 0
        max_retries = getattr(getattr(self._config, 'retries', None), 'max_task_attempts', 2)
        max_batches = len(tasks) * (max_retries + 1)

        # Start background control polling
        control_poll_task = asyncio.create_task(self._control_poll_loop())

        try:
            while batch_num < max_batches:
                if self._shutdown_requested:
                    self._emit("info", message="Shutdown requested — stopping dispatch")
                    break

                # Check pause
                await self._check_pause()

                ready = self._aot_graph.get_ready_batch()
                if not ready:
                    break  # No more tasks can run

                batch_num += 1
                self._emit(
                    "info",
                    message=f"Batch {batch_num}: {len(ready)} tasks",
                )

                # Check parallel safety
                conflicts = self._aot_graph.check_parallel_safety(ready, self._ast_service)
                parallel, serialized = self._split_by_conflicts(ready, conflicts)
                if serialized:
                    self._record_decision("executing", "parallel_safety_split",
                                          f"Serialized {len(serialized)} tasks due to AST conflicts",
                                          f"Parallel: {parallel}, Serialized: {serialized}")

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
                        self._emit("spawn", task_id=tid, agent_id=f"agent-{tid}", message=f"Spawning worker for {tid}")
                    self._persist_state()

                    batch_tasks = [self._task_to_dict(tid) for tid in parallel]
                    # Persist prompts for each task
                    for td in batch_tasks:
                        self._persist_prompt(td["task_id"], td)
                    task_timeout = max(t.get("timeout_seconds", 0) for t in batch_tasks) or 600.0
                    results = await self._subagent_mgr.execute_batch(batch_tasks, timeout=task_timeout)

                    for result in results:
                        completed += self._handle_result(result)
                    self._persist_state()

                # Execute serialized tasks one by one
                for tid in serialized:
                    self._aot_graph.mark_running(tid)
                    self._emit("spawn", task_id=tid, agent_id=f"agent-{tid}", message=f"Spawning worker for {tid} (serialized)")
                    self._persist_state()

                    task_dict = self._task_to_dict(tid)
                    self._persist_prompt(tid, task_dict)
                    task = self._tasks.get(tid)
                    task_timeout = float(task.timeout_seconds) if task and task.timeout_seconds > 0 else 600.0
                    result = await self._subagent_mgr.execute_single(task_dict, timeout=task_timeout)
                    completed += self._handle_result(result)
                    self._persist_state()

                # Post-batch: refresh AST index, check control messages, stall detection
                if self._ast_service:
                    try:
                        self._ast_service.refresh()
                    except Exception:
                        pass
                self._check_control_messages()
                self._check_stale_agents()

            # Warn if tasks remain pending after the loop
            remaining = [tid for tid, n in self._aot_graph.nodes.items() if n.status == "pending"]
            if remaining:
                self._emit("warning", message=f"{len(remaining)} tasks still pending after execution: {remaining}")

        finally:
            # 5. Finalize — guaranteed to run on normal exit, shutdown, or SIGTERM

            # Stop background control polling
            control_poll_task.cancel()
            try:
                await control_poll_task
            except asyncio.CancelledError:
                pass

            self._phase = "completed" if not self._shutdown_requested else "shutdown"
            elapsed = time.time() - self._start_time
            summary = self._aot_graph.summary()
            self._emit(
                "complete",
                message=f"Swarm {'shutdown' if self._shutdown_requested else 'complete'}: {completed}/{len(tasks)} tasks in {elapsed:.1f}s",
                data=summary,
            )

            # Persist change manifest
            if self._change_manifest:
                try:
                    self._change_manifest.persist()
                except Exception:
                    pass

            # Git safety: commit or discard
            if self._git_safety:
                try:
                    if completed > 0:
                        await self._git_safety.create_swarm_commit(
                            f"attoswarm: {completed}/{len(tasks)} tasks completed"
                        )
                    else:
                        await self._git_safety.finalize("discard")
                        self._emit("info", message="Git safety: no tasks completed, restored original branch")
                except Exception as exc:
                    logger.warning("Git safety finalize failed: %s", exc)

            self._persist_state()

            # Kill all remaining subprocesses
            await self._subagent_mgr.shutdown_all()

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
                "tokens_used": self._budget.used_tokens,
                "cost_usd": self._budget.used_cost_usd,
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

    def _persist_manifest(self) -> None:
        """Write manifest JSON for resume / TUI consumption."""
        if not self._manifest:
            return
        data: dict[str, Any] = {
            "run_id": self._manifest.run_id,
            "goal": self._manifest.goal,
            "tasks": [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "description": t.description,
                    "deps": t.deps,
                    "target_files": t.target_files,
                    "task_kind": t.task_kind,
                    "role_hint": t.role_hint or "",
                }
                for t in self._manifest.tasks
            ],
        }
        try:
            write_json_atomic(self._layout["manifest"], data)
        except Exception as exc:
            logger.warning("Failed to persist manifest: %s", exc)

    def _persist_task(self, task_id: str) -> None:
        """Write per-task JSON file for TUI task detail view."""
        task = self._tasks.get(task_id)
        if not task:
            return
        node = self._aot_graph.get_node(task_id)
        data: dict[str, Any] = {
            "task_id": task.task_id,
            "title": task.title,
            "description": task.description,
            "status": node.status if node else task.status,
            "task_kind": task.task_kind,
            "role_hint": task.role_hint or "",
            "deps": task.deps,
            "target_files": task.target_files,
            "read_files": task.read_files,
            "files_modified": task.files_modified,
            "result_summary": task.result_summary,
            "symbol_scope": task.symbol_scope,
            "tokens_used": task.tokens_used,
            "cost_usd": task.cost_usd,
            "attempt_count": self._task_attempts.get(task_id, 0),
            "attempt_history": self._task_attempt_history.get(task_id, []),
            "has_diff": (self._layout["tasks"] / f"task-{task_id}.diff").exists(),
        }
        path = self._layout["tasks"] / f"task-{task_id}.json"
        try:
            write_json_atomic(path, data)
        except Exception:
            pass

    def _persist_state(self) -> None:
        """Write state snapshot to disk for TUI consumption."""
        self._state_seq += 1

        # Build dag edges from task deps
        dag_edges: list[list[str]] = []
        for tid, task in self._tasks.items():
            for dep in task.deps:
                dag_edges.append([dep, tid])

        # Build dag nodes with status from AoT graph (enriched for TUI)
        # Build agent lookup from subagent manager
        agent_for_task: dict[str, str] = {}
        for a in self._subagent_mgr.get_all_agents():
            if a.task_id:
                agent_for_task[a.task_id] = a.agent_id

        dag_nodes: list[dict[str, Any]] = []
        for tid, task in self._tasks.items():
            node = self._aot_graph.get_node(tid)
            status = node.status if node else task.status
            is_foundation = len(node.depended_by) >= 3 if node else False
            dag_nodes.append({
                "task_id": tid,
                "title": task.title,
                "status": status,
                "description": task.description[:200] if task.description else "",
                "task_kind": task.task_kind,
                "role_hint": task.role_hint or "",
                "assigned_agent": agent_for_task.get(tid, ""),
                "target_files": task.target_files[:5],
                "result_summary": task.result_summary[:200] if task.result_summary else "",
                "tokens_used": task.tokens_used,
                "cost_usd": task.cost_usd,
                "attempt_count": self._task_attempts.get(tid, 0),
                "is_foundation": is_foundation,
                "quality_score": getattr(task, 'quality_score', None),
                "depended_by": list(node.depended_by) if node else [],
            })

        # Persist per-task JSON files
        for tid in self._tasks:
            self._persist_task(tid)

        # All agents from subagent manager (not just running)
        active_agents: list[dict[str, Any]] = []
        for a in self._subagent_mgr.get_all_agents():
            task = self._tasks.get(a.task_id)
            active_agents.append({
                "agent_id": a.agent_id,
                "task_id": a.task_id,
                "status": a.status,
                "tokens_used": a.tokens_used,
                "started_at_epoch": a.started_at,
                "model": a.model or self._config.run.default_model or "",
                "task_title": task.title if task else "",
                "activity": a.activity,
                "backend": a.model or self._config.run.default_model or "",
                "cwd": self._root_dir,
                "exit_code": getattr(a, 'exit_code', None),
                "restart_count": getattr(a, 'restart_count', 0),
            })

        state: dict[str, Any] = {
            "run_id": self._run_id,
            "goal": self._goal,
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
            "decisions": self._decisions[-50:],
            "errors": self._errors[-50:],
            "task_transition_log": self._transition_log[-100:],
            "git_branch": (
                self._git_safety.state.swarm_branch
                if self._git_safety and hasattr(self._git_safety, "state")
                else ""
            ),
        }

        try:
            write_json_fast(self._layout["state"], state)
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

    def _archive_previous_run(self) -> None:
        """Move previous run artifacts to history/{run_id}/ and start clean."""
        from attoswarm.coordinator.archive import archive_previous_run

        archive_previous_run(self._layout)

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
            from attoswarm.workspace.reconciler import ASTReconciler

            persist_dir = str(self._internal_dir / "ledger")
            ws_cfg = getattr(self._config, 'workspace', None)
            claim_ttl = ws_cfg.claim_ttl_seconds if ws_cfg else 120.0
            self._file_ledger = FileLedger(
                root_dir=self._root_dir,
                ast_service=self._ast_service,
                persist_dir=persist_dir,
                ttl_seconds=claim_ttl,
            )

            # Wire AST reconciler into the ledger for conflict resolution
            self._reconciler = ASTReconciler(ast_service=self._ast_service)
            self._file_ledger._reconciler = self._reconciler

            # Wire conflict advisor if code-intel available
            ci_cfg = getattr(self._config, 'code_intel', None)
            if self._code_intel and (not ci_cfg or ci_cfg.cross_ref_conflicts):
                try:
                    from attoswarm.workspace.conflict_advisor import ConflictAdvisor
                    self._reconciler._conflict_advisor = ConflictAdvisor(self._code_intel)
                except Exception as exc:
                    logger.debug("Conflict advisor init failed: %s", exc)

            # Wire learning bridge into reconciler for conflict learning
            if self._learning_bridge:
                self._reconciler._learning_bridge = self._learning_bridge

            # Wire conflict event callback for event bus emission
            def _on_conflict(**kwargs: Any) -> None:
                self._emit(
                    "conflict",
                    task_id=kwargs.get("task_id", ""),
                    agent_id=kwargs.get("agent_id", ""),
                    message=f"OCC conflict on {kwargs.get('file_path', '')}",
                    data=kwargs,
                )

            self._file_ledger._event_callback = _on_conflict

            # Wire change manifest into ledger
            if self._change_manifest:
                self._file_ledger._change_manifest = self._change_manifest
        except Exception as exc:
            logger.warning("File ledger init failed: %s", exc)
            self._file_ledger = None

    async def _decompose_goal(self, codebase_context: str = "") -> list[TaskSpec]:
        """Decompose the goal into tasks.

        Checks for a tasks file first (tasks.yaml/yml/md in the run dir),
        then uses the provided ``decompose_fn``, or falls back to a single task.
        """
        # Check for pre-defined tasks file in run dir
        for ext in ("yaml", "yml", "md"):
            tasks_file = self._layout["root"] / f"tasks.{ext}"
            if tasks_file.exists():
                try:
                    from attoswarm.coordinator.task_file_parser import load_tasks_file
                    tasks = load_tasks_file(tasks_file)
                    if tasks:
                        self._emit("info", message=f"Loaded {len(tasks)} tasks from {tasks_file.name}")
                        return tasks
                except Exception as exc:
                    logger.warning("Failed to load tasks file %s: %s", tasks_file, exc)
                    self._emit("warning", message=f"Tasks file {tasks_file.name} failed: {exc}")

        if self._decompose_fn:
            try:
                result = await self._decompose_fn(
                    self._goal,
                    ast_service=self._ast_service,
                    config=self._config,
                    codebase_context=codebase_context,
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
        d: dict[str, Any] = {
            "task_id": task.task_id,
            "title": task.title,
            "description": task.description,
            "target_files": task.target_files,
            "read_files": task.read_files,
            "file_version_snapshot": task.file_version_snapshot,
            "symbol_scope": task.symbol_scope,
            "role_hint": task.role_hint,
            "task_kind": task.task_kind,
            "timeout_seconds": task.timeout_seconds,
        }
        # Inject per-task learning context
        if self._learning_bridge:
            try:
                learning_ctx = self._learning_bridge.recall_for_task(task)
                if learning_ctx:
                    d["learning_context"] = learning_ctx
            except Exception:
                pass
        return d

    def _capture_task_diff(self, task_id: str, files_modified: list[str]) -> None:
        """Capture git diff for files modified by a task (best-effort)."""
        if not files_modified:
            return
        try:
            import subprocess

            result = subprocess.run(
                ["git", "diff", "HEAD", "--"] + files_modified[:20],
                capture_output=True, text=True, timeout=10,
                cwd=self._root_dir,
            )
            if result.stdout.strip():
                diff_path = self._layout["tasks"] / f"task-{task_id}.diff"
                diff_path.write_text(result.stdout, encoding="utf-8")
        except Exception:
            pass

    def _handle_result(self, result: TaskResult) -> int:
        """Process a task result.  Returns 1 if successful, 0 otherwise."""
        task = self._tasks.get(result.task_id)
        if task:
            task.files_modified = result.files_modified
            task.result_summary = result.result_summary
            task.tokens_used = result.tokens_used
            task.cost_usd = result.cost_usd

        # Update budget
        if result.tokens_used or result.cost_usd:
            self._budget.add_usage(
                {"total": result.tokens_used} if result.tokens_used else None,
                result.cost_usd if result.cost_usd else None,
            )

        # Track per-task cost for budget projection
        if result.cost_usd > 0:
            self._per_task_costs.append(result.cost_usd)

        if result.success:
            old_status = self._aot_graph.get_node(result.task_id).status if self._aot_graph.get_node(result.task_id) else "running"
            self._aot_graph.mark_complete(result.task_id)
            self._transition_log.append({
                "timestamp": utc_now_iso(),
                "task_id": result.task_id,
                "from_state": old_status,
                "to_state": "done",
                "reason": "completed successfully",
                "assigned_agent": f"agent-{result.task_id}",
            })
            self._emit("complete", task_id=result.task_id,
                        agent_id=f"agent-{result.task_id}",
                        message=f"Task {result.task_id} completed",
                        data={"files_modified": result.files_modified,
                              "tokens_used": result.tokens_used,
                              "cost_usd": result.cost_usd})
            # Capture git diff for modified files
            self._capture_task_diff(result.task_id, result.files_modified)
            # Record learning from successful task
            if self._learning_bridge:
                try:
                    self._learning_bridge.record_task_outcome(task, result)
                except Exception:
                    pass
            # Budget projection after each result
            self._run_budget_projection()
            return 1

        # Failure analysis
        failure_attr = self._classify_failure(result)

        # Track error (Fix S1)
        self._errors.append({
            "timestamp": utc_now_iso(),
            "message": result.error or "Task failed",
            "phase": self._phase,
            "task_id": result.task_id,
        })

        # Track attempts
        attempts = self._task_attempts.get(result.task_id, 0) + 1
        self._task_attempts[result.task_id] = attempts
        max_retries = getattr(getattr(self._config, 'retries', None), 'max_task_attempts', 2)

        # Record attempt history
        self._task_attempt_history.setdefault(result.task_id, []).append({
            "attempt": attempts,
            "error": (result.error or "")[:500],
            "timestamp": utc_now_iso(),
            "duration_s": result.duration_s,
            "tokens_used": result.tokens_used,
            "failure_cause": failure_attr.get("cause", "") if failure_attr else "",
        })

        if attempts < max_retries:
            # Reset for retry
            node = self._aot_graph.get_node(result.task_id)
            if node:
                node.status = "pending"
            self._transition_log.append({
                "timestamp": utc_now_iso(),
                "task_id": result.task_id,
                "from_state": "running",
                "to_state": "pending",
                "reason": f"retry attempt {attempts}/{max_retries}",
                "assigned_agent": f"agent-{result.task_id}",
            })
            self._record_decision("executing", "retry",
                                  f"Retrying {result.task_id} (attempt {attempts}/{max_retries})",
                                  failure_attr.get("suggestion", "") if failure_attr else "")
            self._emit("retry", task_id=result.task_id,
                        agent_id=f"agent-{result.task_id}",
                        message=f"Task {result.task_id} failed (attempt {attempts}/{max_retries}), retrying")
            # Budget projection after each result
            self._run_budget_projection()
            return 0

        # Max retries exhausted
        self._aot_graph.mark_failed(result.task_id)
        self._transition_log.append({
            "timestamp": utc_now_iso(),
            "task_id": result.task_id,
            "from_state": "running",
            "to_state": "failed",
            "reason": f"max retries exhausted ({attempts}/{max_retries}): {(result.error or '')[:200]}",
            "assigned_agent": f"agent-{result.task_id}",
        })
        skipped = self._aot_graph.cascade_skip_blocked()
        self._record_decision("executing", "task_failed",
                              f"Task {result.task_id} failed permanently",
                              f"Cascade-skipped: {skipped}" if skipped else "No downstream tasks affected")
        self._emit("fail", task_id=result.task_id,
                    agent_id=f"agent-{result.task_id}",
                    message=f"Task {result.task_id} failed: {result.error}",
                    data={"skipped": skipped, "failure": failure_attr or {}})
        if skipped:
            for skip_tid in skipped:
                self._transition_log.append({
                    "timestamp": utc_now_iso(),
                    "task_id": skip_tid,
                    "from_state": "pending",
                    "to_state": "skipped",
                    "reason": f"cascade skip from {result.task_id}",
                    "assigned_agent": "",
                })
            self._emit("skip", message=f"Cascade-skipped: {skipped}")
        # Record learning from failure
        if self._learning_bridge:
            try:
                self._learning_bridge.record_task_outcome(task, result)
            except Exception:
                pass
        # Budget projection after each result
        self._run_budget_projection()
        return 0

    def _restore_state(self) -> None:
        """Restore task states from persisted state file for resume.

        Tasks that were ``done`` stay done; everything else (failed, skipped,
        running) is reset to ``pending`` so they are retried.
        """
        from attoswarm.protocol.io import read_json

        state = read_json(self._layout["state"], default={})
        dag = state.get("dag", {})
        restored = 0
        for node_data in dag.get("nodes", []):
            tid = str(node_data.get("task_id", ""))
            status = str(node_data.get("status", "pending"))
            node = self._aot_graph.get_node(tid)
            if not node:
                continue
            if status == "done":
                node.status = "done"
                restored += 1
            else:
                # Reset failed/skipped/running to pending for retry
                node.status = "pending"
        if restored:
            self._emit("info", message=f"Resumed: {restored} tasks already done, rest reset to pending")

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

    async def _check_pause(self) -> None:
        """If paused, sleep-loop until resumed or shutdown requested."""
        while self._paused and not self._shutdown_requested:
            self._check_control_messages()
            await asyncio.sleep(1.0)

    async def _control_poll_loop(self) -> None:
        """Background task that checks control.jsonl every 5s during execution."""
        while self._phase in ("executing", "paused", "awaiting_approval") and not self._shutdown_requested:
            self._check_control_messages()
            await asyncio.sleep(5.0)

    def _persist_prompt(self, task_id: str, task_dict: dict[str, Any]) -> None:
        """Write the full agent prompt to disk for TUI inspection."""
        parts = [f"# Task: {task_dict.get('title', '')}", "", task_dict.get("description", "")]
        target_files = task_dict.get("target_files", [])
        if target_files:
            parts.append(f"\nTarget files: {', '.join(target_files)}")
        read_files = task_dict.get("read_files", [])
        if read_files:
            parts.append(f"\nReference files: {', '.join(read_files)}")
        prompt_path = self._layout["agents"] / f"agent-{task_id}.prompt.txt"
        try:
            prompt_path.write_text("\n".join(parts), encoding="utf-8")
        except Exception:
            pass

    def _check_control_messages(self) -> None:
        """Poll control.jsonl for user-initiated skip/retry/edit commands."""
        import json as _json

        control_path = self._layout["root"] / "control.jsonl"
        if not control_path.exists():
            return
        try:
            lines = control_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        new_lines = lines[self._control_cursor:]
        self._control_cursor = len(lines)

        for line in new_lines:
            try:
                msg = _json.loads(line)
            except Exception:
                continue
            action = msg.get("action", "")
            task_id = msg.get("task_id", "")

            # Global actions (no task_id required)
            if action == "shutdown":
                self._request_shutdown()
                continue
            if action == "paused":
                self._paused = True
                self._phase = "paused"
                self._emit("info", message="Orchestrator paused by user")
                self._persist_state()
                continue
            if action == "executing":
                self._paused = False
                self._phase = "executing"
                self._emit("info", message="Orchestrator resumed by user")
                self._persist_state()
                continue
            if action == "approve":
                self._approved = True
                self._phase = "executing"
                self._emit("info", message="Execution approved by user")
                self._persist_state()
                continue
            if action == "reject":
                self._request_shutdown()
                self._emit("info", message="Execution rejected by user")
                continue
            if action == "add_task":
                self._handle_add_task(msg)
                continue

            if not task_id:
                continue

            if action == "skip":
                node = self._aot_graph.get_node(task_id)
                if node and node.status not in ("done", "skipped"):
                    self._aot_graph.mark_failed(task_id)
                    skipped = self._aot_graph.cascade_skip_blocked()
                    self._emit("skip", task_id=task_id,
                               message=f"Task {task_id} skipped by user",
                               data={"skipped": skipped})
            elif action == "retry":
                node = self._aot_graph.get_node(task_id)
                if node and node.status in ("failed", "skipped"):
                    node.status = "pending"
                    self._task_attempts.pop(task_id, None)
                    self._emit("retry", task_id=task_id,
                               message=f"Task {task_id} retry requested by user")
            elif action == "edit_task":
                new_desc = msg.get("description", "")
                task = self._tasks.get(task_id)
                if task and new_desc:
                    task.description = new_desc
                    self._persist_task(task_id)
                    self._emit("info", task_id=task_id,
                               message=f"Task {task_id} description updated by user")

    def _handle_add_task(self, msg: dict[str, Any]) -> None:
        """Handle add_task control message — inject a new task into the DAG."""
        new_id = msg.get("task_id", f"user-{uuid.uuid4().hex[:6]}")
        title = msg.get("title", "").strip()
        description = msg.get("description", "").strip()
        deps = msg.get("deps", [])
        target_files = msg.get("target_files", [])
        task_kind = msg.get("task_kind", "implement")

        if not title:
            self._emit("warning", message="add_task rejected: title is required")
            return

        # Validate deps exist
        bad_deps = [d for d in deps if d not in self._tasks]
        if bad_deps:
            self._emit("warning", message=f"add_task rejected: unknown deps {bad_deps}")
            return

        # Check for ID collision
        if new_id in self._tasks:
            new_id = f"user-{uuid.uuid4().hex[:6]}"

        new_task = TaskSpec(
            task_id=new_id,
            title=title,
            description=description or title,
            deps=deps,
            target_files=target_files,
            task_kind=task_kind,
        )
        # Best-effort code-intel enrichment for dynamic tasks
        if self._code_intel:
            try:
                enriched = self._enrich_tasks_with_impact([new_task])
                if enriched:
                    new_task = enriched[0]
            except Exception:
                pass

        self._tasks[new_id] = new_task
        new_node = AoTNode(
            task_id=new_id,
            depends_on=list(deps),
            target_files=list(target_files),
        )
        self._aot_graph.add_task(new_node)

        # Recompute levels (safe — BFS from scratch)
        try:
            self._aot_graph.compute_levels()
        except ValueError as exc:
            # Cycle detected — rollback
            self._aot_graph.remove_task(new_id)
            del self._tasks[new_id]
            self._emit("warning", message=f"add_task rejected: {exc}")
            return

        self._persist_state()
        if self._manifest:
            self._manifest.tasks = list(self._tasks.values())
        self._persist_manifest()
        self._emit("info", task_id=new_id,
                    message=f"User added task: {title}")
        self._transition_log.append({
            "timestamp": utc_now_iso(),
            "task_id": new_id,
            "from_state": "(new)",
            "to_state": "pending",
            "reason": "added by user",
            "assigned_agent": "",
        })

    # ------------------------------------------------------------------
    # Code-intel integration (Workstream 1)
    # ------------------------------------------------------------------

    def _init_code_intel(self) -> None:
        """Initialize CodeIntelService if enabled."""
        ci_cfg = getattr(self._config, 'code_intel', None)
        if ci_cfg and not ci_cfg.enabled:
            return
        try:
            from attocode.code_intel.service import CodeIntelService
            self._code_intel = CodeIntelService.get_instance(self._root_dir)
            self._emit("info", message="Code-intel service initialized")
        except Exception as exc:
            logger.warning("Code-intel init failed: %s", exc)
            self._code_intel = None

        # Initialize learning bridge
        if self._code_intel:
            ci_cfg = getattr(self._config, 'code_intel', None)
            if ci_cfg and ci_cfg.learning_enabled:
                try:
                    from attoswarm.coordinator.learning_bridge import SwarmLearningBridge
                    self._learning_bridge = SwarmLearningBridge(self._code_intel)
                except Exception as exc:
                    logger.warning("Learning bridge init failed: %s", exc)

    def _bootstrap_context(self) -> str:
        """Bootstrap codebase orientation before decomposition."""
        ci_cfg = getattr(self._config, 'code_intel', None)
        if not self._code_intel or (ci_cfg and not ci_cfg.bootstrap_on_start):
            return ""
        parts: list[str] = []
        try:
            max_tokens = ci_cfg.bootstrap_max_tokens if ci_cfg else 4000
            bootstrap = self._code_intel.bootstrap(
                task_hint=self._goal, max_tokens=max_tokens,
            )
            if bootstrap:
                parts.append(str(bootstrap))
        except Exception as exc:
            logger.debug("Bootstrap failed: %s", exc)

        # Recall learnings for this goal
        if self._learning_bridge:
            try:
                learnings = self._learning_bridge.recall_for_goal(self._goal)
                if learnings:
                    parts.append(learnings)
            except Exception:
                pass

        ctx = "\n\n".join(parts)
        if ctx:
            self._emit("info", message=f"Bootstrap context: {len(ctx)} chars")
        return ctx

    def _enrich_tasks_with_impact(self, tasks: list[TaskSpec]) -> list[TaskSpec]:
        """Enrich tasks with code-intel impact analysis data."""
        ci_cfg = getattr(self._config, 'code_intel', None)
        if not self._code_intel or (ci_cfg and not ci_cfg.impact_enrichment):
            return tasks

        max_read = ci_cfg.max_read_files_per_task if ci_cfg else 10
        depth = ci_cfg.impact_depth if ci_cfg else 1

        # Build file -> task mapping for implicit DAG deps
        file_to_task: dict[str, str] = {}
        for task in tasks:
            for f in task.target_files:
                file_to_task[f] = task.task_id

        enriched = 0
        for task in tasks:
            if not task.target_files:
                continue
            try:
                existing_reads = set(task.read_files)
                for tf in task.target_files[:3]:  # cap to avoid slow runs
                    # Impact analysis — find impacted files
                    try:
                        impact = self._code_intel.impact_analysis_data(tf, depth=depth)
                        if isinstance(impact, dict):
                            for f_info in impact.get("impacted_files", [])[:5]:
                                fp = f_info if isinstance(f_info, str) else f_info.get("file", "")
                                if fp and fp not in existing_reads and len(task.read_files) < max_read:
                                    task.read_files.append(fp)
                                    existing_reads.add(fp)
                    except Exception:
                        pass

                    # Related files
                    try:
                        related = self._code_intel.find_related_data(tf, limit=3)
                        if isinstance(related, dict):
                            for r in related.get("related", [])[:3]:
                                fp = r if isinstance(r, str) else r.get("file", "")
                                if fp and fp not in existing_reads and len(task.read_files) < max_read:
                                    task.read_files.append(fp)
                                    existing_reads.add(fp)
                    except Exception:
                        pass

                    # Symbols for scope
                    try:
                        syms = self._code_intel.symbols_data(tf)
                        if isinstance(syms, dict):
                            for s in syms.get("symbols", [])[:10]:
                                name = s if isinstance(s, str) else s.get("name", "")
                                if name and name not in task.symbol_scope:
                                    task.symbol_scope.append(name)
                    except Exception:
                        pass

                    # Implicit deps from imports
                    try:
                        deps_data = self._code_intel.dependencies_data(tf)
                        if isinstance(deps_data, dict):
                            for imp_file in deps_data.get("imports", [])[:10]:
                                fp = imp_file if isinstance(imp_file, str) else imp_file.get("file", "")
                                if fp in file_to_task:
                                    dep_tid = file_to_task[fp]
                                    if dep_tid != task.task_id and dep_tid not in task.deps:
                                        task.deps.append(dep_tid)
                    except Exception:
                        pass

                enriched += 1
            except Exception as exc:
                logger.debug("Impact enrichment failed for %s: %s", task.task_id, exc)

        if enriched:
            self._emit("info", message=f"Enriched {enriched} tasks with code-intel data")
        return tasks

    # ------------------------------------------------------------------
    # Budget projection (Workstream 2.1)
    # ------------------------------------------------------------------

    def _init_budget_projector(self) -> None:
        try:
            from attoswarm.coordinator.budget import BudgetProjector
            self._budget_projector = BudgetProjector()
        except Exception:
            pass

    def _init_trace_bridge(self) -> None:
        """Wire EventBus → TraceCollector bridge if a collector is available."""
        if not self._trace_collector:
            return
        try:
            from attocode.integrations.swarm.trace_bridge import SwarmTraceBridge

            self._trace_bridge = SwarmTraceBridge(self._event_bus, self._trace_collector)
            self._emit("info", message="Trace bridge wired: swarm events → trace collector")
        except Exception as exc:
            logger.debug("Trace bridge init failed: %s", exc)

    def _run_budget_projection(self) -> None:
        """Run budget projection after each task result."""
        if not self._budget_projector:
            return
        try:
            summary = self._aot_graph.summary()
            total_tasks = sum(summary.values())
            completed = summary.get("done", 0) + summary.get("failed", 0) + summary.get("skipped", 0)
            projection = self._budget_projector.project(
                used_cost=self._budget.used_cost_usd,
                max_cost=self._budget.max_cost_usd,
                completed_tasks=completed,
                total_tasks=total_tasks,
                per_task_costs=self._per_task_costs,
            )
            if projection.warning_level in ("warning", "critical", "shutdown"):
                self._emit("budget", message=projection.message,
                           data={"projection": projection.to_dict()})
                self._record_decision("executing", "budget_projection",
                                      projection.message,
                                      f"Level: {projection.warning_level}")
        except Exception as exc:
            logger.debug("Budget projection failed: %s", exc)

    # ------------------------------------------------------------------
    # Failure analysis (Workstream 2.2)
    # ------------------------------------------------------------------

    def _classify_failure(self, result: Any) -> dict[str, Any] | None:
        """Classify a task failure and return attribution data."""
        try:
            from attoswarm.coordinator.failure_analyzer import FailureAnalyzer
            analyzer = FailureAnalyzer()
            attr = analyzer.classify_failure(
                task_id=result.task_id,
                error_str=result.error or "",
                duration_s=result.duration_s,
                tokens_used=result.tokens_used,
            )
            if attr:
                suggestion = analyzer.generate_suggestion(attr)
                return {
                    "cause": attr.cause,
                    "confidence": attr.confidence,
                    "evidence": attr.evidence,
                    "suggestion": suggestion,
                }
        except Exception as exc:
            logger.debug("Failure analysis failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Decision transparency (Workstream 2.4)
    # ------------------------------------------------------------------

    def _record_decision(
        self,
        phase: str,
        decision_type: str,
        decision: str,
        reasoning: str,
    ) -> None:
        """Record a decision for transparency."""
        entry = {
            "timestamp": utc_now_iso(),
            "phase": phase,
            "decision_type": decision_type,
            "decision": decision,
            "reasoning": reasoning,
        }
        self._decisions.append(entry)
        # Keep last 100
        if len(self._decisions) > 100:
            self._decisions = self._decisions[-100:]
        self._emit("decision", message=decision, data=entry)

    def _check_stale_agents(self) -> None:
        """Warn about agents that haven't produced output beyond the configured timeout."""
        timeout = self._config.watchdog.task_silence_timeout_seconds
        now = time.time()
        stale = []
        for a in self._subagent_mgr.get_active_agents():
            if a.started_at and now - a.started_at > timeout:
                stale.append(a.agent_id)
        if stale:
            self._emit("warning", message=f"Stale agents (>{timeout:.0f}s): {stale}")

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
