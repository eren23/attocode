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
import json
import logging
import os
import signal
import time
import uuid
from dataclasses import asdict, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from attoswarm.coordinator.aot_graph import AoTGraph, AoTNode
from attoswarm.coordinator.budget import BudgetCounter
from attoswarm.coordinator.budget_gate import BudgetGate
from attoswarm.coordinator.cache import SwarmCache
from attoswarm.coordinator.causal_analyzer import CausalChainAnalyzer
from attoswarm.coordinator.decompose_validator import DecomposeValidator
from attoswarm.coordinator.event_bus import EventBus, SwarmEvent
from attoswarm.coordinator.health_monitor import HealthMonitor
from attoswarm.coordinator.poison_detector import PoisonDetector
from attoswarm.coordinator.preflight import PreflightValidator
from attoswarm.coordinator.result_pipeline import ResultPipeline
from attoswarm.coordinator.subagent_manager import SubagentManager, TaskResult
from attoswarm.coordinator.trace_context import TraceContext, current_span, start_span
from attoswarm.protocol.io import read_json, write_json_atomic, write_json_fast
from attoswarm.protocol.models import (
    LauncherInfo,
    LineageSpec,
    SwarmManifest,
    TaskSpec,
    default_run_layout,
    utc_now_iso,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from attoswarm.config.schema import SwarmYamlConfig

logger = logging.getLogger(__name__)


class PlanningFailure(RuntimeError):
    """Raised when shared-workspace planning cannot produce runnable tasks."""


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
        lineage: LineageSpec | None = None,
        launcher: LauncherInfo | None = None,
    ) -> None:
        self._config = config
        self._goal = goal
        self._resume = resume
        self._decompose_fn = decompose_fn
        self._trace_collector = trace_collector
        self._approval_mode = approval_mode  # "auto" | "preview" | "dry_run"
        self._approved = False

        # Unique run ID
        wd = config.run.working_dir or "."
        self._root_dir = os.path.abspath(wd)
        self._run_dir = Path(config.run.run_dir)
        resume_meta = self._load_resume_metadata() if resume else {}
        self._run_id = str(
            resume_meta.get("run_id")
            or (lineage.run_id if lineage else "")
            or str(uuid.uuid4())[:8]
        )
        self._lineage = lineage or LineageSpec.from_dict(resume_meta.get("lineage", {}))
        self._launcher = launcher or LauncherInfo.from_dict(resume_meta.get("launcher", {}))
        self._lineage.refresh(self._run_id, self._resume)
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
        adaptive_cfg = getattr(config, 'adaptive', None)
        self._adaptive_cfg = adaptive_cfg
        self._subagent_mgr = SubagentManager(
            max_concurrency=config.workspace.max_concurrent_writers,
            spawn_fn=spawn_fn,
            concurrency_floor=adaptive_cfg.concurrency_floor if adaptive_cfg else 1,
            concurrency_ceiling=adaptive_cfg.concurrency_ceiling if adaptive_cfg else 8,
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

        # Phase 1: Distributed tracing
        tracing_cfg = getattr(config, 'tracing', None)
        self._tracing_enabled = tracing_cfg.enabled if tracing_cfg else True
        self._trace_ctx: TraceContext | None = None
        self._cache = SwarmCache(max_size=256, default_ttl=300.0)
        self._result_pipeline = ResultPipeline()

        # Phase 2: Adaptive systems
        health_threshold = adaptive_cfg.health_threshold if adaptive_cfg else 0.5
        self._health_monitor = HealthMonitor(health_threshold=health_threshold)
        self._budget_gate: BudgetGate | None = None
        self._speculative_enabled = adaptive_cfg.speculative_enabled if adaptive_cfg else False
        self._speculative_executor: Any = None

        # Phase 3: Intelligence layer
        validation_cfg = getattr(config, 'validation', None)
        self._decompose_validation = validation_cfg.decompose_validation if validation_cfg else True
        self._preflight_enabled = validation_cfg.preflight_checks if validation_cfg else True
        self._poison_detection = validation_cfg.poison_detection if validation_cfg else True
        self._poison_detector = PoisonDetector(
            max_varying_failures=validation_cfg.max_varying_failures if validation_cfg else 3,
        )
        self._causal_analyzer: CausalChainAnalyzer | None = None
        self._preflight_validator: PreflightValidator | None = None
        self._validation_result: dict[str, Any] | None = None
        self._poison_reports: list[dict[str, Any]] = []

        # Phase 4: Timing & post-mortem
        self._timing_waterfall: Any = None

        # Decision log (Workstream 2.4)
        self._decisions: list[dict[str, Any]] = []

        # Error tracking (Fix S1)
        self._errors: list[dict[str, Any]] = []

        # Task transition log (Fix S2)
        self._transition_log: list[dict[str, Any]] = []

        # Shutdown / pause
        self._shutdown_requested = False
        self._shutdown_reason: str = ""
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
        self._control_lock: asyncio.Lock | None = None  # initialized in run()
        self._cached_test_command: str | None = None

    def _load_resume_metadata(self) -> dict[str, Any]:
        manifest = read_json(self._run_dir / "swarm.manifest.json", default={})
        if isinstance(manifest, dict) and manifest.get("run_id"):
            return manifest
        state = read_json(self._run_dir / "swarm.state.json", default={})
        return state if isinstance(state, dict) else {}

    def _load_existing_manifest(self) -> bool:
        """Restore tasks and persisted counters from ``swarm.manifest.json``."""
        raw = read_json(self._layout["manifest"], default={})
        if not isinstance(raw, dict):
            return False

        raw_tasks = raw.get("tasks", [])
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return False

        self._tasks = {}
        self._aot_graph = AoTGraph()
        self._task_attempts = {}
        self._task_attempt_history = {}

        restored_tasks: list[TaskSpec] = []
        for item in raw_tasks:
            if not isinstance(item, dict):
                continue
            task = self._task_from_manifest_row(item)
            if not task.task_id:
                continue
            restored_tasks.append(task)
            self._tasks[task.task_id] = task
            self._aot_graph.add_task(AoTNode(
                task_id=task.task_id,
                depends_on=list(task.deps),
                target_files=list(task.target_files),
                symbol_scope=list(task.symbol_scope),
            ))
            task_state = read_json(self._layout["tasks"] / f"task-{task.task_id}.json", default={})
            self._task_attempts[task.task_id] = int(task_state.get("attempt_count", 0))
            history = task_state.get("attempt_history", [])
            self._task_attempt_history[task.task_id] = [h for h in history if isinstance(h, dict)]

        if not restored_tasks:
            return False

        self._aot_graph.compute_levels()
        self._goal = str(raw.get("goal", self._goal))
        state_raw = read_json(self._layout["state"], default={})
        budget_raw = state_raw.get("budget", {}) if isinstance(state_raw.get("budget"), dict) else {}
        self._budget.used_tokens = int(budget_raw.get("tokens_used", 0))
        self._budget.used_cost_usd = float(budget_raw.get("cost_used_usd", 0.0))
        self._state_seq = int(state_raw.get("state_seq", 0))
        self._decisions = [x for x in state_raw.get("decisions", []) if isinstance(x, dict)]
        self._errors = [x for x in state_raw.get("errors", []) if isinstance(x, dict)]
        self._transition_log = [x for x in state_raw.get("task_transition_log", []) if isinstance(x, dict)]
        self._manifest = SwarmManifest(
            run_id=self._run_id,
            goal=self._goal,
            tasks=restored_tasks,
            lineage=self._lineage,
            launcher=self._launcher,
        )
        return True

    def _task_from_manifest_row(self, raw: dict[str, Any]) -> TaskSpec:
        """Build a ``TaskSpec`` from persisted manifest data."""
        allowed = {f.name for f in fields(TaskSpec)}
        payload = {k: v for k, v in raw.items() if k in allowed}
        if "deps" in payload and not isinstance(payload["deps"], list):
            payload["deps"] = []
        for key in (
            "acceptance",
            "artifacts",
            "target_files",
            "read_files",
            "symbol_scope",
            "files_modified",
        ):
            if key in payload and not isinstance(payload[key], list):
                payload[key] = []
        if "file_version_snapshot" in payload and not isinstance(payload["file_version_snapshot"], dict):
            payload["file_version_snapshot"] = {}
        if "status" in payload:
            payload["status"] = str(payload["status"] or "pending")
        return TaskSpec(**payload)

    def _prime_control_cursor(self) -> None:
        """Ignore historical control messages so resume only sees new input."""
        control_path = self._layout["root"] / "control.jsonl"
        if not control_path.exists():
            self._control_cursor = 0
            return
        try:
            self._control_cursor = len(control_path.read_text(encoding="utf-8").splitlines())
        except Exception:
            self._control_cursor = 0

    # ------------------------------------------------------------------
    # Agent activity event callback (wired as event_callback in cli.py)
    # ------------------------------------------------------------------

    def _on_agent_activity(self, event: Any) -> None:
        """Handle a structured ``AgentActivityEvent`` from stream-json parsing.

        Updates AgentStatus in the SubagentManager and emits EventBus events.
        """
        task_id = getattr(event, "task_id", "")
        agent_id = f"agent-{task_id}"
        status = self._subagent_mgr._agent_statuses.get(agent_id)
        if not status:
            return

        kind = getattr(event, "event_kind", "")
        now = getattr(event, "timestamp", 0.0) or __import__("time").time()
        status.last_activity_ts = now

        if kind == "tool_call":
            status.tool_call_count += 1
            status.current_tool = getattr(event, "tool_name", "")
            status.activity = f"{status.current_tool} {getattr(event, 'tool_input_summary', '')[:40]}"
            # Track files touched from tool input
            tool_input = getattr(event, "tool_input_summary", "")
            if status.current_tool in ("Edit", "Write", "Read") and tool_input:
                # Extract likely file path (first token)
                candidate = tool_input.split(",")[0].split('"')[1] if '"' in tool_input else tool_input.split()[0] if tool_input.split() else ""
                if candidate and "/" in candidate and len(status.files_touched) < 50:
                    if candidate not in status.files_touched:
                        status.files_touched.append(candidate)
            self._emit("agent.tool_call", task_id=task_id, agent_id=agent_id,
                        message=f"{status.current_tool}",
                        data={"tool": status.current_tool, "input_summary": getattr(event, "tool_input_summary", "")[:100]})
        elif kind == "text":
            status.llm_turns += 1
            status.activity = getattr(event, "text_preview", "")[:60]
        elif kind == "result":
            status.tokens_used = getattr(event, "tokens_used", 0)
        elif kind == "error":
            status.activity = f"error: {getattr(event, 'text_preview', '')[:40]}"

        # Write trace entry for tool calls
        if kind == "tool_call":
            self._subagent_mgr._write_trace_entry(agent_id, task_id, "tool_call", {
                "tool": getattr(event, "tool_name", ""),
                "input_summary": getattr(event, "tool_input_summary", "")[:200],
            })

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

    def _request_shutdown(self, reason: str = "unknown") -> None:
        """Signal handler callback — request graceful shutdown."""
        if self._shutdown_requested:
            return  # Already shutting down
        self._shutdown_requested = True
        self._shutdown_reason = reason
        logger.warning("SHUTDOWN: reason=%s, phase=%s", reason, self._phase)
        self._emit("info", message=f"Shutdown requested: {reason}",
                   data={"reason": reason, "phase": self._phase})

    async def run(self) -> int:
        """Execute the full orchestration loop.

        Returns the number of successfully completed tasks.
        """
        self._start_time = time.time()
        self._setup_directories()
        resumed_existing_plan = False

        # PID lockfile — detect concurrent orchestrators
        lockfile = self._layout["root"] / ".orchestrator.pid"
        if lockfile.exists():
            try:
                old_pid = int(lockfile.read_text(encoding="utf-8").strip())
                try:
                    os.kill(old_pid, 0)
                    logger.warning("Another orchestrator (PID %d) may be running", old_pid)
                except OSError:
                    pass  # Stale PID
            except (ValueError, OSError):
                pass
        lockfile.write_text(str(os.getpid()), encoding="utf-8")

        # Initialize control lock (requires event loop)
        self._control_lock = asyncio.Lock()

        # Recover from orphaned swarm branch before archive
        ws_cfg_early = getattr(self._config, 'workspace', None)
        if ws_cfg_early and ws_cfg_early.git_safety and not self._resume:
            try:
                from attoswarm.workspace.git_safety import GitSafetyNet
                _recovery_net = GitSafetyNet(self._root_dir, self._run_id, str(self._run_dir))
                await _recovery_net.recover_orphaned_state()
            except Exception as exc:
                logger.warning("Git orphan recovery failed: %s", exc)

        if not self._resume:
            self._archive_previous_run()
        else:
            resumed_existing_plan = self._load_existing_manifest()
            if resumed_existing_plan:
                self._restore_state()

        # Always prime control cursor — defense against stale shutdown commands
        # even when archive fails or is skipped
        self._prime_control_cursor()

        self._phase = "initializing"
        self._persist_state()  # Early write — lets TUI detect subprocess start

        # Install signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda s=sig: self._request_shutdown(f"signal:{s.name}"))
            except (NotImplementedError, OSError):
                pass  # Windows or non-main thread

        # 1. Initialize AST service
        self._emit("info", message="Initializing AST service...")
        self._init_ast_service()

        # 1b. Initialize code-intel service
        if resumed_existing_plan:
            self._emit("info", message="Resume: using persisted task graph; skipping code-intel bootstrap")
        else:
            self._init_code_intel()

        # 1c. Initialize budget projector
        self._init_budget_projector()

        # 1d. Wire EventBus → TraceCollector bridge if collector available
        self._init_trace_bridge()

        # 2. Initialize File Ledger
        self._init_file_ledger()

        # Wire ledger + AST + trace dir + health monitor into subagent manager
        self._subagent_mgr._file_ledger = self._file_ledger
        self._subagent_mgr._ast_service = self._ast_service
        self._subagent_mgr._trace_dir = str(self._layout["agents"])
        self._subagent_mgr._health_monitor = self._health_monitor

        # Wire preflight validator (after file ledger is ready)
        if self._preflight_enabled:
            self._preflight_validator = PreflightValidator(
                root_dir=self._root_dir,
                health_monitor=self._health_monitor,
                budget_gate=self._budget_gate,  # may be None — PreflightValidator handles it
                file_ledger=self._file_ledger,
            )

        # Initialize trace context
        if self._tracing_enabled:
            self._trace_ctx = TraceContext(trace_id=self._run_id)

        # Initialize timing waterfall
        if self._trace_ctx:
            from attoswarm.coordinator.timing import TimingWaterfall
            self._timing_waterfall = TimingWaterfall(trace_id=self._run_id)

        # 2b. Git safety config — deferred to after approval gate
        ws_cfg = getattr(self._config, 'workspace', None)

        # 2c. Initialize change manifest
        if ws_cfg and ws_cfg.change_manifest:
            try:
                from attoswarm.workspace.change_manifest import ChangeManifest
                self._change_manifest = ChangeManifest(str(self._run_dir))
            except Exception as exc:
                logger.warning("Change manifest init failed: %s", exc)

        if resumed_existing_plan:
            tasks = list(self._tasks.values())
            execution_order = self._aot_graph.get_execution_order()
            summary = self._aot_graph.summary()
            self._emit(
                "info",
                message=(
                    f"Resumed existing plan: {summary.get('done', 0)} done, "
                    f"{summary.get('pending', 0)} pending"
                ),
            )
            self._persist_manifest()
            self._persist_state()
        else:
            # 2d. Bootstrap codebase context before decomposition
            bootstrap_ctx = self._bootstrap_context()

            # 3. Decompose goal into tasks
            self._phase = "decomposing"
            self._emit("info", message=f"Decomposing goal: {self._goal[:100]}")
            self._persist_state()  # Update phase to "decomposing" for TUI
            try:
                async with start_span("decompose_goal", trace_id=self._run_id):
                    tasks = await self._decompose_goal(codebase_context=bootstrap_ctx)
            except PlanningFailure as exc:
                self._phase = "planning_failed"
                self._errors.append({
                    "timestamp": utc_now_iso(),
                    "message": str(exc),
                    "phase": self._phase,
                    "task_id": "",
                })
                self._emit("fail", message=f"Planning failed: {exc}")
                self._persist_state()
                return 1
            if not tasks:
                self._phase = "planning_failed"
                self._errors.append({
                    "timestamp": utc_now_iso(),
                    "message": "Decomposition produced no tasks",
                    "phase": self._phase,
                    "task_id": "",
                })
                self._emit("fail", message="Planning failed: decomposition produced no tasks")
                self._persist_state()
                return 1
            self._record_decision("decomposing", "decomposition_complete",
                                  f"Produced {len(tasks)} tasks", f"Goal complexity drove task count")

            # 3b. Validate decomposition (Phase 3)
            if self._decompose_validation:
                try:
                    validator = DecomposeValidator(
                        root_dir=self._root_dir,
                        ast_service=self._ast_service,
                    )
                    vr = validator.validate(tasks)
                    self._validation_result = vr.to_dict()
                    if vr.has_errors:
                        self._emit("warning",
                                   message=f"Decomposition has {vr.error_count} errors, {vr.warning_count} warnings (score: {vr.score:.2f})")
                        # Re-decompose on severe issues in auto mode (1 retry max)
                        if self._approval_mode == "auto" and self._decompose_fn:
                            feedback = "\n".join(
                                f"- [{i.severity}] {i.message}: {i.suggestion}"
                                for i in vr.issues if i.severity == "error"
                            )
                            self._emit("info", message=f"Re-decomposing with {vr.error_count} error feedback items")
                            try:
                                retry_ctx = bootstrap_ctx + f"\n\n## Validation Feedback\n{feedback}"
                                async with start_span("redecompose_goal", trace_id=self._run_id):
                                    tasks = await self._decompose_goal(codebase_context=retry_ctx)
                                # Re-validate after retry
                                vr2 = validator.validate(tasks)
                                self._validation_result = vr2.to_dict()
                                if vr2.has_errors:
                                    self._emit("warning",
                                               message=f"Re-decomposition still has {vr2.error_count} errors (score: {vr2.score:.2f})")
                                else:
                                    self._emit("info",
                                               message=f"Re-decomposition improved (score: {vr2.score:.2f})")
                            except Exception as exc2:
                                logger.debug("Re-decomposition failed: %s", exc2)
                    elif vr.has_warnings:
                        self._emit("info",
                                   message=f"Decomposition validated with {vr.warning_count} warnings (score: {vr.score:.2f})")
                    else:
                        self._emit("info", message=f"Decomposition validated (score: {vr.score:.2f})")
                except Exception as exc:
                    logger.debug("Decomposition validation failed: %s", exc)

            # 3c. Enrich tasks with code-intel impact analysis
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
                lineage=self._lineage,
                launcher=self._launcher,
            )
            self._persist_manifest()
            self._persist_state()

        # Initialize causal analyzer (Phase 3) — after AoT graph is populated (both fresh and resume)
        from attoswarm.coordinator.failure_analyzer import FailureAnalyzer
        self._causal_analyzer = CausalChainAnalyzer(self._aot_graph, FailureAnalyzer())

        # Initialize speculative executor (Phase 2) — after AoT graph is populated
        if self._speculative_enabled:
            from attoswarm.coordinator.speculative import SpeculativeExecutor
            self._speculative_executor = SpeculativeExecutor(
                aot_graph=self._aot_graph,
                health_monitor=self._health_monitor,
                budget_gate=self._budget_gate,
                confidence_threshold=self._adaptive_cfg.speculative_confidence if self._adaptive_cfg else 0.8,
            )

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
                await self._safe_check_control()
                await asyncio.sleep(1.0)
                if time.time() - approval_start > approval_timeout:
                    self._emit("warning", message="Approval timeout — shutting down")
                    self._request_shutdown("approval_timeout")
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
                if self._resume and (self._run_dir / "git_safety.json").exists():
                    self._git_safety.load_state()
                    git_state = await self._git_safety.reattach()
                else:
                    git_state = await self._git_safety.setup(
                        base_ref=self._lineage.base_ref or None,
                        base_commit=self._lineage.base_commit or None,
                    )
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
                    pending = [tid for tid, n in self._aot_graph.nodes.items() if n.status == "pending"]
                    self._emit("info", message=f"No ready tasks (pending={len(pending)}) — loop ending",
                               data={"pending_tasks": pending[:10]})
                    break

                # Budget gate: filter and prioritize (Phase 2)
                if self._budget_gate:
                    ready = self._budget_gate.prioritize_remaining(ready)
                    filtered_ready: list[str] = []
                    estimated = self._budget_gate.estimated_task_cost()
                    for tid in ready:
                        decision = self._budget_gate.can_dispatch(tid, estimated_cost=estimated)
                        if decision.allowed:
                            filtered_ready.append(tid)
                        else:
                            self._emit("budget", task_id=tid,
                                       message=f"Budget gate blocked {tid}: {decision.reason}")
                            self._record_decision("executing", "budget_gate_block",
                                                  f"Blocked {tid}", decision.reason)
                    if not filtered_ready:
                        self._request_shutdown("budget_exhausted")
                        break
                    ready = filtered_ready

                # Pre-flight checks (Phase 3)
                if self._preflight_enabled and self._preflight_validator:
                    preflight_ready: list[str] = []
                    for tid in ready:
                        task = self._tasks.get(tid)
                        if task:
                            try:
                                pf = await self._preflight_validator.check(task)
                                if pf.passed:
                                    preflight_ready.append(tid)
                                else:
                                    # Reset to pending with recorded blocker
                                    self._emit("info", task_id=tid,
                                               message=f"Preflight blocked: {'; '.join(pf.blockers)}")
                            except Exception as exc:
                                logger.debug("Preflight check failed for %s: %s", tid, exc)
                                preflight_ready.append(tid)  # Fail-open
                        else:
                            preflight_ready.append(tid)
                    if not preflight_ready:
                        self._emit("info", message=f"Preflight blocked all {len(ready)} ready tasks — stopping",
                                   data={"blocked_tasks": ready[:10]})
                        break
                    ready = preflight_ready

                batch_num += 1
                self._emit(
                    "info",
                    message=f"Batch {batch_num}: {len(ready)} tasks",
                )

                # Check parallel safety (with cache)
                cache_key = f"conflict:{':'.join(sorted(ready))}"
                cached_conflicts = self._cache.get(cache_key)
                if cached_conflicts is not None:
                    conflicts = cached_conflicts
                else:
                    conflicts = self._aot_graph.check_parallel_safety(ready, self._ast_service)
                    self._cache.put(cache_key, conflicts, ttl=60.0)
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
                                except Exception as exc:
                                    logger.warning("File snapshot failed for %s (task %s): %s", f, tid, exc)
                                    self._emit("warning", task_id=tid,
                                               message=f"File snapshot failed for {f}: {exc}")

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
                    task_timeout = max(self._resolve_task_timeout_from_dict(td) for td in batch_tasks)

                    # Speculative execution: identify candidates BEFORE awaiting
                    # batch results (while deps are still "running")
                    spec_tasks: list[dict[str, Any]] = []
                    if self._speculative_executor:
                        try:
                            default_model = getattr(self._config.run, 'default_model', '') or ''
                            running_models = {tid: default_model for tid in parallel}
                            candidates = self._speculative_executor.get_candidates(running_models)
                            for c in candidates:
                                self._speculative_executor.mark_speculative(c.task_id)
                                self._aot_graph.mark_running(c.task_id)
                                self._emit("spawn", task_id=c.task_id,
                                           message=f"Speculative: {c.task_id} (confidence={c.confidence:.2f})")
                                spec_tasks.append(self._task_to_dict(c.task_id))
                        except Exception as exc:
                            logger.debug("Speculative candidate identification failed: %s", exc)

                    # Launch speculative tasks concurrently with main batch
                    spec_task_future: asyncio.Task[list[TaskResult]] | None = None
                    if spec_tasks:
                        spec_timeout = self._default_task_timeout()
                        spec_task_future = asyncio.create_task(
                            self._subagent_mgr.execute_batch(spec_tasks, timeout=spec_timeout)
                        )

                    async with start_span("execute_batch", trace_id=self._run_id,
                                          attributes={"batch_num": batch_num, "count": len(parallel)}):
                        results = await self._subagent_mgr.execute_batch(batch_tasks, timeout=task_timeout)

                    # Process results through the pipeline (concurrent fan-out)
                    async with start_span("process_batch_results", trace_id=self._run_id,
                                          attributes={"count": len(results)}):
                        pipeline_result = await self._result_pipeline.process_batch(results, self)
                    completed += pipeline_result.completed

                    # Handle speculative cancellation on failures
                    if self._speculative_executor and pipeline_result.failed > 0:
                        for result in results:
                            if not result.success:
                                to_cancel = self._speculative_executor.on_dep_failed(result.task_id)
                                for cancel_tid in to_cancel:
                                    node = self._aot_graph.get_node(cancel_tid)
                                    if node and node.status == "running":
                                        node.status = "pending"
                                        self._emit("info", task_id=cancel_tid,
                                                   message=f"Speculative task cancelled: dep {result.task_id} failed")

                    # Collect speculative results
                    if spec_task_future is not None:
                        try:
                            spec_results = await spec_task_future
                            for sr in spec_results:
                                completed += await self._handle_result(sr)
                        except Exception as exc:
                            logger.debug("Speculative batch execution failed: %s", exc)

                    self._persist_state()

                # Execute serialized tasks one by one
                for tid in serialized:
                    self._aot_graph.mark_running(tid)
                    self._emit("spawn", task_id=tid, agent_id=f"agent-{tid}", message=f"Spawning worker for {tid} (serialized)")
                    self._persist_state()

                    task_dict = self._task_to_dict(tid)
                    self._persist_prompt(tid, task_dict)
                    task = self._tasks.get(tid)
                    task_timeout = self._resolve_task_timeout(task)
                    result = await self._subagent_mgr.execute_single(task_dict, timeout=task_timeout)
                    async with start_span("handle_result", trace_id=self._run_id,
                                          attributes={"task_id": result.task_id}):
                        completed += await self._handle_result(result)
                    self._persist_state()

                # Post-batch: refresh AST index, check control messages, stall detection
                if self._ast_service:
                    try:
                        async with start_span("ast_refresh", trace_id=self._run_id):
                            self._ast_service.refresh()
                        # Invalidate conflict cache after AST changes
                        self._cache.invalidate_prefix("conflict:")
                    except Exception as exc:
                        logger.debug("AST index refresh failed: %s", exc)
                await self._safe_check_control()
                self._check_stale_agents()

            # Diagnostic: why did the loop end?
            if batch_num >= max_batches:
                self._emit("warning", message=f"Batch safety bound reached: {batch_num}/{max_batches}")

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

            if self._phase != "planning_failed":
                self._phase = "completed" if not self._shutdown_requested else "shutdown"
            elapsed = time.time() - self._start_time
            summary = self._aot_graph.summary()
            self._emit(
                "complete",
                message=f"Swarm {self._phase.replace('_', ' ')}: {completed}/{len(tasks)} tasks in {elapsed:.1f}s",
                data=summary,
            )
            # Persist immediately so TUI sees phase transition before git/post-mortem
            self._persist_state()

            # Persist change manifest
            if self._change_manifest:
                try:
                    self._change_manifest.persist()
                except Exception as exc:
                    logger.warning("Change manifest persist failed: %s", exc)

            # Git safety: commit or discard
            if self._git_safety:
                try:
                    if completed > 0:
                        await self._git_safety.create_swarm_commit(
                            f"attoswarm: {completed}/{len(tasks)} tasks completed"
                        )
                        await self._git_safety.finalize("keep")
                    else:
                        await self._git_safety.finalize("discard")
                        self._emit("info", message="Git safety: no tasks completed, restored original branch")
                except Exception as exc:
                    logger.warning("Git safety finalize failed: %s", exc)

            # Generate post-mortem report (Phase 4)
            try:
                from attoswarm.coordinator.decompose_metrics import DecomposeMetrics
                from attoswarm.coordinator.postmortem import PostMortemGenerator
                from attoswarm.coordinator.trace_query import TraceQueryEngine

                query_engine = TraceQueryEngine(run_dir=self._run_dir)
                query_engine.load()
                pm_gen = PostMortemGenerator(
                    query_engine=query_engine,
                    causal_analyzer=self._causal_analyzer,
                    decompose_metrics=DecomposeMetrics(),
                )
                concurrency_stats = self._subagent_mgr._concurrency.stats.to_dict()
                report = pm_gen.generate(
                    dag_summary=summary,
                    budget_data=self._budget.as_dict(),
                    wall_clock_s=elapsed,
                    critical_path=self._aot_graph.get_critical_path(),
                    max_concurrency=self._config.workspace.max_concurrent_writers,
                    validation_result=self._validation_result,
                    poison_reports=self._poison_reports,
                    concurrency_stats=concurrency_stats,
                )
                pm_gen.persist(report, self._run_dir)
                self._emit("info", message=f"Post-mortem: {report.outcome}, "
                           f"score={report.decomposition_score:.2f}, "
                           f"efficiency={report.parallel_efficiency:.0%}")
            except Exception as exc:
                logger.debug("Post-mortem generation failed: %s", exc)

            self._persist_state()

            # Cleanup trace context and timing waterfall
            if self._trace_ctx:
                self._trace_ctx.cleanup()
            if self._timing_waterfall:
                self._timing_waterfall.cleanup()

            # Kill all remaining subprocesses
            await self._subagent_mgr.shutdown_all()

            # Clean up PID lockfile
            try:
                lockfile = self._layout["root"] / ".orchestrator.pid"
                if lockfile.exists() and lockfile.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    lockfile.unlink(missing_ok=True)
            except Exception:
                pass

        return completed

    def get_state(self) -> dict[str, Any]:
        """Return a state snapshot for TUI consumption."""
        return {
            "run_id": self._run_id,
            "phase": self._phase,
            "goal": self._goal,
            "lineage": asdict(self._lineage),
            "launcher": asdict(self._launcher),
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
            "lineage": asdict(self._lineage),
            "launcher": asdict(self._launcher),
            "tasks": [],
        }
        for task in self._manifest.tasks:
            row = asdict(task)
            node = self._aot_graph.get_node(task.task_id)
            row["status"] = node.status if node else task.status
            data["tasks"].append(row)
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
        except Exception as exc:
            logger.debug("Failed to persist task %s: %s", task_id, exc)

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
                "tool_call_count": a.tool_call_count,
                "current_tool": a.current_tool,
                "files_touched": a.files_touched[:10],
                "llm_turns": a.llm_turns,
            })

        state: dict[str, Any] = {
            "run_id": self._run_id,
            "goal": self._goal,
            "phase": self._phase,
            "shutdown_reason": self._shutdown_reason,
            "working_dir": self._root_dir,
            "lineage": asdict(self._lineage),
            "launcher": asdict(self._launcher),
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
            "timing": self._timing_waterfall.to_dict() if self._timing_waterfall else {},
            "health_monitor": self._health_monitor.to_dict() if self._health_monitor else {},
            "cache_stats": self._cache.stats.to_dict() if self._cache else {},
            "causal_chains": (
                self._causal_analyzer.to_dict()
                if self._causal_analyzer and self._causal_analyzer.chains
                else {}
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
        from attoswarm.coordinator.archive import archive_previous_run, ensure_clean_slate

        try:
            archive_previous_run(self._layout)
        except Exception as exc:
            logger.warning("Archive failed (will clean slate anyway): %s", exc)

        cleaned = ensure_clean_slate(self._layout)
        self._emit("info", message=f"Clean slate: {cleaned} stale items removed" if cleaned else "Clean slate: verified clean")

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
        then uses the provided ``decompose_fn``.
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
                raise PlanningFailure(f"LLM decomposition failed ({exc})") from exc

        raise PlanningFailure("No LLM decomposer available for shared-workspace planning")

    def _default_task_timeout(self) -> float:
        watchdog = getattr(self._config, "watchdog", None)
        configured = float(getattr(watchdog, "task_max_duration_seconds", 0.0) or 0.0)
        return configured if configured > 0 else 600.0

    def _resolve_task_timeout(self, task: TaskSpec | None) -> float:
        explicit = float(task.timeout_seconds) if task and task.timeout_seconds > 0 else 0.0
        return explicit or self._default_task_timeout()

    def _resolve_task_timeout_from_dict(self, task: dict[str, Any]) -> float:
        raw = task.get("timeout_seconds", 0)
        try:
            explicit = float(raw or 0)
        except (TypeError, ValueError):
            explicit = 0.0
        return explicit if explicit > 0 else self._default_task_timeout()

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
        # Health-aware model selection
        if not d.get("model") and self._health_monitor:
            default_model = getattr(self._config.run, 'default_model', '') or ''
            if default_model:
                d["model"] = self._health_monitor.get_best_model([default_model])

        # Inject per-task learning context (with cache)
        if self._learning_bridge:
            cache_key = f"learning:{hash(task.title + ':'.join(task.target_files[:3]))}"
            cached = self._cache.get(cache_key) if self._cache else None
            if cached is not None:
                d["learning_context"] = cached
            else:
                try:
                    learning_ctx = self._learning_bridge.recall_for_task(task)
                    if learning_ctx:
                        d["learning_context"] = learning_ctx
                        if self._cache:
                            self._cache.put(cache_key, learning_ctx, ttl=120.0)
                except Exception as exc:
                    logger.debug("Learning recall for task %s failed: %s", task.task_id, exc)

        # Test file discovery for prompt injection
        try:
            if self._cached_test_command is None:
                from attoswarm.coordinator.test_verifier import detect_test_command
                self._cached_test_command = detect_test_command(self._root_dir) or ""
            d["test_command"] = self._cached_test_command

            from attoswarm.coordinator.test_verifier import discover_related_test_files
            d["test_files"] = discover_related_test_files(task.target_files, self._root_dir)
        except Exception as exc:
            logger.debug("Test file discovery for task %s failed: %s", task.task_id, exc)

        return d

    # ------------------------------------------------------------------
    # PipelineHandlers protocol implementation (Fix 2)
    # ------------------------------------------------------------------

    async def pipeline_update_budget(self, result: TaskResult) -> None:
        """Sequential budget update for the result pipeline."""
        task = self._tasks.get(result.task_id)
        if task:
            task.files_modified = result.files_modified
            task.result_summary = result.result_summary
            task.tokens_used = result.tokens_used
            task.cost_usd = result.cost_usd
        if result.tokens_used or result.cost_usd:
            self._budget.add_usage(
                {"total": result.tokens_used} if result.tokens_used else None,
                result.cost_usd if result.cost_usd else None,
            )
        if result.cost_usd > 0:
            self._per_task_costs.append(result.cost_usd)

    async def pipeline_test_verify(self, result: TaskResult) -> bool:
        """Run test verification gate. Returns True if passed."""
        task = self._tasks.get(result.task_id)
        tv_cfg = getattr(self._config, 'test_verification', None)
        if not (
            tv_cfg and tv_cfg.enabled
            and task and task.task_kind in tv_cfg.applicable_task_kinds
            and result.files_modified
        ):
            return result.success
        verification = await self._run_test_verification(result)
        if not verification.passed:
            result.error = (
                f"Tests failed: {verification.tests_failed}/{verification.tests_total} "
                f"(pass rate {verification.pass_rate:.0%} < threshold {tv_cfg.pass_rate_threshold:.0%})"
            )
            if verification.error:
                result.error += f" — {verification.error}"
            self._emit("test_verify_fail", task_id=result.task_id,
                        agent_id=f"agent-{result.task_id}",
                        message=f"Test verification failed for {result.task_id}",
                        data={"pass_rate": verification.pass_rate,
                              "tests_passed": verification.tests_passed,
                              "tests_failed": verification.tests_failed,
                              "duration_s": verification.duration_s})
            return False
        self._emit("test_verify_pass", task_id=result.task_id,
                    agent_id=f"agent-{result.task_id}",
                    message=f"Test verification passed for {result.task_id}",
                    data={"pass_rate": verification.pass_rate,
                          "tests_total": verification.tests_total,
                          "duration_s": verification.duration_s})
        return True

    async def pipeline_syntax_verify(self, result: TaskResult) -> bool:
        """Check modified files parse correctly. Returns True if all pass."""
        import ast as _ast

        errors: list[str] = []
        for f in result.files_modified or []:
            fpath = Path(self._root_dir) / f
            if not fpath.exists():
                continue
            ext = fpath.suffix
            if ext == ".py":
                try:
                    source = fpath.read_text(encoding="utf-8")
                    _ast.parse(source, filename=str(fpath))
                except SyntaxError as exc:
                    errors.append(f"{f}:{exc.lineno}: {exc.msg}")
            elif ext == ".json":
                try:
                    import json as _json
                    _json.loads(fpath.read_text(encoding="utf-8"))
                except (ValueError, _json.JSONDecodeError) as exc:
                    errors.append(f"{f}: {exc}")
        if errors:
            self._emit("warning", message=f"Syntax errors in {result.task_id}",
                       data={"errors": errors})
            result.error = f"Syntax errors: {'; '.join(errors[:5])}"
            return False
        return True

    async def pipeline_record_learning(self, result: TaskResult) -> None:
        """Record learning from task outcome."""
        task = self._tasks.get(result.task_id)
        if self._learning_bridge and task:
            try:
                self._learning_bridge.record_task_outcome(task, result)
            except Exception as exc:
                logger.debug("Learning record failed for %s: %s", result.task_id, exc)

    async def pipeline_capture_diff(self, result: TaskResult) -> None:
        """Capture git diff for modified files."""
        self._capture_task_diff(result.task_id, result.files_modified)

    async def pipeline_git_commit(self, result: TaskResult) -> str | None:
        """Create an atomic git commit for a completed task."""
        if not self._git_safety:
            return None
        commit_hash = await self._git_safety.create_task_commit(
            task_id=result.task_id,
            summary=result.result_summary or result.task_id,
            files=result.files_modified or None,
        )
        if commit_hash:
            self._emit(
                "git_commit",
                task_id=result.task_id,
                message=f"Committed {result.task_id}: {commit_hash[:8]}",
                data={"commit": commit_hash, "files": result.files_modified},
            )
        return commit_hash

    async def pipeline_run_projection(self) -> None:
        """Run budget projection."""
        self._run_budget_projection()

    async def pipeline_update_dag(self, result: TaskResult, success: bool) -> int:
        """Update DAG state and handle failure/retry. Returns 1 if completed."""
        if success:
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
            if self._causal_analyzer and result.cost_usd > 0:
                self._causal_analyzer.record_task_cost(result.task_id, result.cost_usd)
            self._capture_task_diff(result.task_id, result.files_modified)
            # Promote speculative tasks whose deps are now all done
            if self._speculative_executor:
                self._speculative_executor.on_dep_completed(result.task_id)
            return 1

        # Failure path — delegate to the full _handle_result for retry/poison/cascade logic
        # (budget already updated by pipeline_update_budget)
        failure_attr = self._classify_failure(result)

        if self._causal_analyzer:
            try:
                from attoswarm.coordinator.failure_analyzer import FailureAttribution
                attr_obj = None
                if failure_attr:
                    attr_obj = FailureAttribution(
                        task_id=result.task_id,
                        cause=failure_attr.get("cause", ""),
                        confidence=failure_attr.get("confidence", 0.0),
                        evidence=failure_attr.get("evidence", ""),
                    )
                self._causal_analyzer.analyze_failure(result.task_id, attr_obj)
                if result.cost_usd > 0:
                    self._causal_analyzer.record_task_cost(result.task_id, result.cost_usd)
            except Exception as exc:
                logger.debug("Causal analysis failed for %s: %s", result.task_id, exc)

        self._errors.append({
            "timestamp": utc_now_iso(),
            "message": result.error or "Task failed",
            "phase": self._phase,
            "task_id": result.task_id,
        })

        attempts = self._task_attempts.get(result.task_id, 0) + 1
        self._task_attempts[result.task_id] = attempts
        max_retries = getattr(getattr(self._config, 'retries', None), 'max_task_attempts', 2)

        self._task_attempt_history.setdefault(result.task_id, []).append({
            "attempt": attempts,
            "error": (result.error or "")[:500],
            "timestamp": utc_now_iso(),
            "duration_s": result.duration_s,
            "tokens_used": result.tokens_used,
            "failure_cause": failure_attr.get("cause", "") if failure_attr else "",
        })

        # Poison detection
        if self._poison_detection and attempts >= 2:
            try:
                history = self._task_attempt_history.get(result.task_id, [])
                poison_report = self._poison_detector.check(result.task_id, history)
                if poison_report.is_poison:
                    self._poison_reports.append(poison_report.to_dict())
                    self._emit("warning", task_id=result.task_id,
                               message=f"Poison task detected: {poison_report.reason}")
                    self._record_decision("executing", "poison_detected",
                                          f"Task {result.task_id} is poisonous: {poison_report.recommendation}",
                                          poison_report.reason)
                    self._aot_graph.mark_failed(result.task_id)
                    skipped = self._aot_graph.cascade_skip_blocked()
                    self._emit("skip", task_id=result.task_id,
                               message=f"Poison task {result.task_id} skipped",
                               data={"poison": poison_report.to_dict(), "skipped": skipped})
                    if skipped:
                        for skip_tid in skipped:
                            self._transition_log.append({
                                "timestamp": utc_now_iso(),
                                "task_id": skip_tid,
                                "from_state": "pending",
                                "to_state": "skipped",
                                "reason": f"cascade skip from poison {result.task_id}",
                                "assigned_agent": "",
                            })
                    return 0
            except Exception as exc:
                logger.debug("Poison detection failed for %s: %s", result.task_id, exc)

        if attempts < max_retries:
            node = self._aot_graph.get_node(result.task_id)
            if node:
                node.status = "pending"
            self._cache.invalidate_prefix("conflict:")
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
            return 0

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
        return 0

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
        except Exception as exc:
            logger.debug("Failed to capture diff for task %s: %s", task_id, exc)

    async def _handle_result(self, result: TaskResult) -> int:
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

        # ── Test verification gate ────────────────────────────────────
        if result.success:
            tv_cfg = getattr(self._config, 'test_verification', None)
            if (
                tv_cfg and tv_cfg.enabled
                and task and task.task_kind in tv_cfg.applicable_task_kinds
                and result.files_modified
            ):
                verification = await self._run_test_verification(result)
                if not verification.passed:
                    result.success = False
                    result.error = (
                        f"Tests failed: {verification.tests_failed}/{verification.tests_total} "
                        f"(pass rate {verification.pass_rate:.0%} < threshold {tv_cfg.pass_rate_threshold:.0%})"
                    )
                    if verification.error:
                        result.error += f" — {verification.error}"
                    self._emit("test_verify_fail", task_id=result.task_id,
                                agent_id=f"agent-{result.task_id}",
                                message=f"Test verification failed for {result.task_id}",
                                data={"pass_rate": verification.pass_rate,
                                      "tests_passed": verification.tests_passed,
                                      "tests_failed": verification.tests_failed,
                                      "duration_s": verification.duration_s})
                else:
                    self._emit("test_verify_pass", task_id=result.task_id,
                                agent_id=f"agent-{result.task_id}",
                                message=f"Test verification passed for {result.task_id}",
                                data={"pass_rate": verification.pass_rate,
                                      "tests_total": verification.tests_total,
                                      "duration_s": verification.duration_s})

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
            # Record cost to causal analyzer (for accurate wasted-cost)
            if self._causal_analyzer and result.cost_usd > 0:
                self._causal_analyzer.record_task_cost(result.task_id, result.cost_usd)
            # Capture git diff for modified files
            self._capture_task_diff(result.task_id, result.files_modified)
            # Record learning from successful task
            if self._learning_bridge:
                try:
                    self._learning_bridge.record_task_outcome(task, result)
                except Exception as exc:
                    logger.debug("Learning record failed for %s: %s", result.task_id, exc)
            # Budget projection after each result
            self._run_budget_projection()
            return 1

        # Failure analysis
        failure_attr = self._classify_failure(result)

        # Causal chain analysis (Phase 3)
        if self._causal_analyzer:
            try:
                from attoswarm.coordinator.failure_analyzer import FailureAttribution
                attr_obj = None
                if failure_attr:
                    attr_obj = FailureAttribution(
                        task_id=result.task_id,
                        cause=failure_attr.get("cause", ""),
                        confidence=failure_attr.get("confidence", 0.0),
                        evidence=failure_attr.get("evidence", ""),
                    )
                self._causal_analyzer.analyze_failure(result.task_id, attr_obj)
                if result.cost_usd > 0:
                    self._causal_analyzer.record_task_cost(result.task_id, result.cost_usd)
            except Exception as exc:
                logger.debug("Causal analysis failed for %s: %s", result.task_id, exc)

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

        # Poison task detection (Phase 3)
        if self._poison_detection and attempts >= 2:
            try:
                history = self._task_attempt_history.get(result.task_id, [])
                poison_report = self._poison_detector.check(result.task_id, history)
                if poison_report.is_poison:
                    self._poison_reports.append(poison_report.to_dict())
                    self._emit("warning", task_id=result.task_id,
                               message=f"Poison task detected: {poison_report.reason}")
                    self._record_decision("executing", "poison_detected",
                                          f"Task {result.task_id} is poisonous: {poison_report.recommendation}",
                                          poison_report.reason)
                    # Skip immediately
                    self._aot_graph.mark_failed(result.task_id)
                    skipped = self._aot_graph.cascade_skip_blocked()
                    self._emit("skip", task_id=result.task_id,
                               message=f"Poison task {result.task_id} skipped",
                               data={"poison": poison_report.to_dict(), "skipped": skipped})
                    self._run_budget_projection()
                    return 0
            except Exception as exc:
                logger.debug("Poison detection failed for %s: %s", result.task_id, exc)

        if attempts < max_retries:
            # Reset for retry
            node = self._aot_graph.get_node(result.task_id)
            if node:
                node.status = "pending"
            self._cache.invalidate_prefix("conflict:")
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
            except Exception as exc:
                logger.debug("Learning record failed for %s: %s", result.task_id, exc)
        # Budget projection after each result
        self._run_budget_projection()
        return 0

    async def _run_test_verification(self, result: TaskResult) -> Any:
        """Run the test verification gate for a completed task."""
        from attoswarm.coordinator.test_verifier import (
            TestVerificationResult,
            detect_test_command,
            run_test_verification,
        )

        tv_cfg = self._config.test_verification
        test_cmd = tv_cfg.test_command or detect_test_command(self._root_dir)
        if not test_cmd:
            self._emit("info", task_id=result.task_id,
                        message="No test command found, skipping verification")
            return TestVerificationResult(
                passed=True, pass_rate=1.0,
                tests_passed=0, tests_failed=0, tests_total=0,
                raw_output="",
            )

        self._emit("test_verify_start", task_id=result.task_id,
                    message=f"Running: {test_cmd[:80]}")

        verification = await run_test_verification(
            working_dir=self._root_dir,
            test_command=test_cmd,
            timeout=tv_cfg.test_timeout_seconds,
            files_modified=result.files_modified,
            scope=tv_cfg.scope_to_changed_files,
        )

        # No tests collected → pass
        if verification.tests_total == 0:
            verification.passed = True
        else:
            verification.passed = verification.pass_rate >= tv_cfg.pass_rate_threshold

        return verification

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
            await self._safe_check_control()
            await asyncio.sleep(1.0)

    async def _safe_check_control(self) -> None:
        """Check control messages with lock to prevent concurrent mutation."""
        if self._control_lock:
            async with self._control_lock:
                self._check_control_messages()
        else:
            self._check_control_messages()

    async def _control_poll_loop(self) -> None:
        """Background task that checks control.jsonl with low-latency polling."""
        while self._phase in ("executing", "paused", "awaiting_approval") and not self._shutdown_requested:
            await self._safe_check_control()
            await asyncio.sleep(0.5)

    def _persist_prompt(self, task_id: str, task_dict: dict[str, Any]) -> None:
        """Write the full agent prompt to disk for TUI inspection."""
        from attoswarm.cli import build_agent_prompt
        prompt_text = build_agent_prompt(task_dict)
        prompt_path = self._layout["agents"] / f"agent-{task_id}.prompt.txt"
        try:
            prompt_path.write_text(prompt_text, encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to persist prompt for task %s: %s", task_id, exc)

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
                if line.strip():
                    logger.warning("Unparseable control message: %s", line[:200])
                continue
            # Ignore messages from before this run started
            msg_ts = msg.get("timestamp", 0)
            if msg_ts and self._start_time and msg_ts < self._start_time:
                logger.info("Ignoring stale control message: action=%s, ts=%.0f (run started at %.0f)",
                            msg.get("action", ""), msg_ts, self._start_time)
                continue
            action = msg.get("action", "")
            task_id = msg.get("task_id", "")
            self._emit(
                "control.received",
                task_id=task_id,
                message=f"Received control action: {action or 'unknown'}",
                data={"action": action, "task_id": task_id, "raw": msg},
            )

            # Global actions (no task_id required)
            if action == "shutdown":
                self._request_shutdown("control:shutdown")
                self._emit("control.applied", message="Applied control action: shutdown", data={"action": action})
                continue
            if action == "paused":
                self._paused = True
                self._phase = "paused"
                self._emit("info", message="Orchestrator paused by user")
                self._emit("control.applied", message="Applied control action: paused", data={"action": action})
                self._persist_state()
                continue
            if action == "executing":
                self._paused = False
                self._phase = "executing"
                self._emit("info", message="Orchestrator resumed by user")
                self._emit("control.applied", message="Applied control action: executing", data={"action": action})
                self._persist_state()
                continue
            if action == "approve":
                self._approved = True
                self._phase = "executing"
                self._emit("info", message="Execution approved by user")
                self._emit("control.applied", message="Applied control action: approve", data={"action": action})
                self._persist_state()
                continue
            if action == "reject":
                self._request_shutdown("control:reject")
                self._emit("info", message="Execution rejected by user")
                self._emit("control.applied", message="Applied control action: reject", data={"action": action})
                continue
            if action == "add_task":
                self._handle_add_task(msg)
                self._emit(
                    "control.applied",
                    task_id=task_id,
                    message="Applied control action: add_task",
                    data={"action": action, "task_id": task_id},
                )
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
                    self._emit("control.applied", task_id=task_id, message="Applied control action: skip", data={"action": action, "task_id": task_id, "skipped": skipped})
            elif action == "retry":
                node = self._aot_graph.get_node(task_id)
                if node and node.status in ("failed", "skipped"):
                    node.status = "pending"
                    self._task_attempts.pop(task_id, None)
                    self._emit("retry", task_id=task_id,
                               message=f"Task {task_id} retry requested by user")
                    self._emit("control.applied", task_id=task_id, message="Applied control action: retry", data={"action": action, "task_id": task_id})
            elif action == "edit_task":
                new_desc = msg.get("description", "")
                task = self._tasks.get(task_id)
                if task and new_desc:
                    task.description = new_desc
                    self._persist_task(task_id)
                    self._emit("info", task_id=task_id,
                               message=f"Task {task_id} description updated by user")
                    self._emit("control.applied", task_id=task_id, message="Applied control action: edit_task", data={"action": action, "task_id": task_id})

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
            except Exception as exc:
                logger.debug("Code-intel enrichment failed for dynamic task: %s", exc)

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
            if self._lineage.parent_summary:
                return json.dumps({"parent_summary": self._lineage.parent_summary}, indent=2)
            return ""

        # Check cache first
        cache_key = f"bootstrap:{hash(self._goal)}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

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
            except Exception as exc:
                logger.debug("Learning recall for goal failed: %s", exc)

        if self._lineage.parent_summary:
            parts.append(
                "Parent swarm summary:\n"
                + json.dumps(self._lineage.parent_summary, indent=2)
            )

        ctx = "\n\n".join(parts)
        if ctx:
            self._cache.put(cache_key, ctx, ttl=600.0)
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
                    except Exception as exc:
                        logger.debug("Impact analysis failed for %s: %s", tf, exc)

                    # Related files
                    try:
                        related = self._code_intel.find_related_data(tf, limit=3)
                        if isinstance(related, dict):
                            for r in related.get("related", [])[:3]:
                                fp = r if isinstance(r, str) else r.get("file", "")
                                if fp and fp not in existing_reads and len(task.read_files) < max_read:
                                    task.read_files.append(fp)
                                    existing_reads.add(fp)
                    except Exception as exc:
                        logger.debug("Find related failed for %s: %s", tf, exc)

                    # Symbols for scope
                    try:
                        syms = self._code_intel.symbols_data(tf)
                        if isinstance(syms, dict):
                            for s in syms.get("symbols", [])[:10]:
                                name = s if isinstance(s, str) else s.get("name", "")
                                if name and name not in task.symbol_scope:
                                    task.symbol_scope.append(name)
                    except Exception as exc:
                        logger.debug("Symbols lookup failed for %s: %s", tf, exc)

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
                    except Exception as exc:
                        logger.debug("Dependencies lookup failed for %s: %s", tf, exc)

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
            # Wire budget gate
            self._budget_gate = BudgetGate(
                budget=self._budget,
                projector=self._budget_projector,
                aot_graph=self._aot_graph,
            )
        except Exception as exc:
            logger.debug("Budget projector init failed: %s", exc)

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
        # Attach trace context if available
        trace_id = ""
        span_id = ""
        span = current_span()
        if span:
            trace_id = span.trace_id
            span_id = span.span_id
        elif self._trace_ctx:
            trace_id = self._trace_ctx.trace_id

        self._event_bus.emit(SwarmEvent(
            event_type=event_type,
            task_id=task_id,
            agent_id=agent_id,
            message=message,
            data=data or {},
            trace_id=trace_id,
            span_id=span_id,
        ))
