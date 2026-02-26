"""Feature initializer - wires all integrations into the agent context.

This is the Python equivalent of the TS feature-initializer.ts.
It initializes economics, compaction, hooks, rules, ignore patterns,
recitation, failure tracking, and other optional integrations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from attocode.agent.context import AgentContext
from attocode.types.budget import BudgetEnforcementMode, ExecutionBudget


@dataclass
class FeatureConfig:
    """Configuration for which features to initialize."""

    enable_economics: bool = True
    enable_compaction: bool = True
    enable_recitation: bool = True
    enable_failure_tracking: bool = True
    enable_learning: bool = True
    enable_auto_checkpoint: bool = True
    enable_rules: bool = True
    enable_ignore: bool = True
    enable_hooks: bool = True
    enable_mode_manager: bool = True
    enable_file_tracking: bool = True
    enable_safety: bool = True
    enable_planning: bool = True
    enable_task_manager: bool = True
    enable_codebase_context: bool = True
    enable_interactive_planner: bool = True
    enable_lsp: bool = False  # Off by default — heavy dependency
    enable_cancellation: bool = True
    enable_dead_letter_queue: bool = True
    enable_self_improvement: bool = True
    enable_health_check: bool = True
    enable_injection_budget: bool = True
    enable_state_machine: bool = True
    enable_semantic_cache: bool = True
    enable_context_engineering: bool = True
    enable_skill_manager: bool = True
    enable_work_log: bool = True
    enable_pending_plan: bool = True
    enable_diverse_serialization: bool = False  # Off by default

    # Tuning
    compaction_max_tokens: int = 200_000
    compaction_warning_threshold: float = 0.7
    compaction_threshold: float = 0.8
    recitation_interval: int = 10
    checkpoint_interval: int = 5
    max_failures_tracked: int = 20

    # Semantic cache tuning
    semantic_cache_max_entries: int = 1000
    semantic_cache_ttl_seconds: float = 3600.0
    semantic_cache_similarity_threshold: float = 0.85

    # Skill manager tuning
    skill_search_dirs: list[str] | None = None  # Extra dirs to search


async def initialize_features(
    ctx: AgentContext,
    *,
    config: FeatureConfig | None = None,
    working_dir: str = "",
    session_dir: str | None = None,
) -> dict[str, bool]:
    """Initialize all optional features on an AgentContext.

    Returns a dict of feature_name -> initialized_successfully.
    """
    cfg = config or FeatureConfig()
    results: dict[str, bool] = {}

    # 1. Economics
    if cfg.enable_economics and ctx.economics is None:
        try:
            from attocode.integrations.budget.economics import ExecutionEconomicsManager
            enforcement = ctx.budget.enforcement_mode if ctx.budget else BudgetEnforcementMode.STRICT
            ctx.economics = ExecutionEconomicsManager(
                budget=ctx.budget,
                enforcement_mode=enforcement,
            )
            results["economics"] = True
        except Exception:
            results["economics"] = False

    # 2. Auto-compaction
    if cfg.enable_compaction and ctx.compaction_manager is None:
        try:
            from attocode.integrations.context.auto_compaction import AutoCompactionManager
            ctx.compaction_manager = AutoCompactionManager(
                max_context_tokens=cfg.compaction_max_tokens,
                warning_threshold=cfg.compaction_warning_threshold,
                compaction_threshold=cfg.compaction_threshold,
            )
            results["compaction"] = True
        except Exception:
            results["compaction"] = False

    # 3. Recitation manager
    if cfg.enable_recitation and ctx.recitation_manager is None:
        try:
            from attocode.tricks.recitation import RecitationManager
            ctx.recitation_manager = RecitationManager(
                interval=cfg.recitation_interval,
            )
            results["recitation"] = True
        except Exception:
            results["recitation"] = False

    # 4. Failure tracker
    if cfg.enable_failure_tracking and ctx.failure_tracker is None:
        try:
            from attocode.tricks.failure_evidence import FailureTracker
            ctx.failure_tracker = FailureTracker(
                max_failures=cfg.max_failures_tracked,
            )
            results["failure_tracking"] = True
        except Exception:
            results["failure_tracking"] = False

    # 5. Learning store
    if cfg.enable_learning and ctx.learning_store is None:
        try:
            from attocode.integrations.quality.learning_store import LearningStore
            learn_dir = session_dir or working_dir
            if learn_dir:
                store_path = Path(learn_dir) / ".agent" / "learnings.json"
                ctx.learning_store = LearningStore(store_path=str(store_path))
                results["learning"] = True
            else:
                results["learning"] = False
        except Exception:
            results["learning"] = False

    # 6. Auto-checkpoint
    if cfg.enable_auto_checkpoint and ctx.auto_checkpoint is None:
        try:
            from attocode.integrations.quality.auto_checkpoint import AutoCheckpointManager
            ctx.auto_checkpoint = AutoCheckpointManager(
                interval=cfg.checkpoint_interval,
                session_store=ctx.session_store,
                session_id=ctx.session_id,
            )
            results["auto_checkpoint"] = True
        except Exception:
            results["auto_checkpoint"] = False

    # 7. Rules
    if cfg.enable_rules and working_dir:
        try:
            from attocode.integrations.utilities.rules import RulesManager
            rules_mgr = RulesManager(working_dir)
            rules = rules_mgr.load_rules()
            if rules:
                # Rules are added to system prompt via message_builder
                ctx._loaded_rules = rules  # type: ignore[attr-defined]
            results["rules"] = True
        except Exception:
            results["rules"] = False

    # 8. Ignore patterns
    if cfg.enable_ignore and working_dir:
        try:
            from attocode.integrations.utilities.ignore import IgnoreManager
            ignore_mgr = IgnoreManager(working_dir)
            ignore_mgr.load()
            ctx._ignore_manager = ignore_mgr  # type: ignore[attr-defined]
            results["ignore"] = True
        except Exception:
            results["ignore"] = False

    # 9. Hooks
    if cfg.enable_hooks and working_dir:
        try:
            from attocode.integrations.utilities.hooks import HookManager
            hooks_mgr = HookManager(working_dir)
            hooks_mgr.load()
            ctx._hook_manager = hooks_mgr  # type: ignore[attr-defined]
            results["hooks"] = True
        except Exception:
            results["hooks"] = False

    # 10. Mode manager
    if cfg.enable_mode_manager and ctx.mode_manager is None:
        try:
            from attocode.integrations.utilities.mode_manager import ModeManager
            ctx.mode_manager = ModeManager()
            results["mode_manager"] = True
        except Exception:
            results["mode_manager"] = False

    # 11. File change tracker (for undo)
    if cfg.enable_file_tracking and ctx.file_change_tracker is None:
        try:
            from attocode.integrations.utilities.undo import FileChangeTracker
            ctx.file_change_tracker = FileChangeTracker()
            results["file_tracking"] = True
        except Exception:
            results["file_tracking"] = False

    # 12. Safety manager (policy engine + execution policy)
    if cfg.enable_safety and not getattr(ctx, "safety_manager", None):
        try:
            from attocode.integrations.safety.policy_engine import PolicyEngine
            from attocode.integrations.safety.execution_policy import ExecutionPolicy

            policy_engine = PolicyEngine()
            exec_policy = ExecutionPolicy()
            # Store on context for the execution loop to use
            ctx._safety_policy_engine = policy_engine  # type: ignore[attr-defined]
            ctx._execution_policy = exec_policy  # type: ignore[attr-defined]
            results["safety"] = True
        except Exception:
            results["safety"] = False

    # 13. Planning manager
    if cfg.enable_planning and not getattr(ctx, "_planning_manager", None):
        try:
            from attocode.integrations.tasks.planning import PlanningManager
            ctx._planning_manager = PlanningManager()  # type: ignore[attr-defined]
            results["planning"] = True
        except Exception:
            results["planning"] = False

    # 14. Task manager
    if cfg.enable_task_manager and not getattr(ctx, "task_manager", None):
        try:
            from attocode.integrations.tasks.task_manager import TaskManager
            ctx.task_manager = TaskManager()  # type: ignore[attr-defined]
            results["task_manager"] = True
        except Exception:
            results["task_manager"] = False

    # 15. Codebase context
    if cfg.enable_codebase_context and working_dir and not getattr(ctx, "codebase_context", None):
        try:
            from attocode.integrations.context.codebase_context import CodebaseContextManager
            ctx.codebase_context = CodebaseContextManager(  # type: ignore[attr-defined]
                root_dir=working_dir,
            )
            results["codebase_context"] = True
        except Exception:
            results["codebase_context"] = False

    # 15b. Register codebase_overview tool (requires codebase context)
    cbc = getattr(ctx, "codebase_context", None)
    if cbc and hasattr(ctx, "registry") and ctx.registry is not None:
        try:
            from attocode.tools.codebase import create_codebase_overview_tool
            overview_tool = create_codebase_overview_tool(cbc)
            ctx.registry.register(overview_tool)
            results["codebase_overview_tool"] = True
        except Exception:
            results["codebase_overview_tool"] = False

    # 16. Interactive planner
    if cfg.enable_interactive_planner and not getattr(ctx, "interactive_planner", None):
        try:
            from attocode.integrations.tasks.interactive_planning import InteractivePlanner
            ctx.interactive_planner = InteractivePlanner()  # type: ignore[attr-defined]
            results["interactive_planner"] = True
        except Exception:
            results["interactive_planner"] = False

    # 17. LSP manager (opt-in)
    if cfg.enable_lsp and working_dir and not getattr(ctx, "_lsp_manager", None):
        try:
            from attocode.integrations.lsp.client import LSPManager
            lsp = LSPManager(working_dir=working_dir)
            ctx._lsp_manager = lsp  # type: ignore[attr-defined]
            results["lsp"] = True
        except Exception:
            results["lsp"] = False

    # 18. Cancellation manager
    if cfg.enable_cancellation and not getattr(ctx, "cancellation_manager", None):
        try:
            from attocode.integrations.budget.cancellation import CancellationManager
            ctx.cancellation_manager = CancellationManager()  # type: ignore[attr-defined]
            results["cancellation"] = True
        except Exception:
            results["cancellation"] = False

    # 19. Dead letter queue
    if cfg.enable_dead_letter_queue and not getattr(ctx, "_dead_letter_queue", None):
        try:
            from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
            ctx._dead_letter_queue = DeadLetterQueue()  # type: ignore[attr-defined]
            results["dead_letter_queue"] = True
        except Exception:
            results["dead_letter_queue"] = False

    # 20. Self-improvement
    if cfg.enable_self_improvement and not getattr(ctx, "_self_improvement", None):
        try:
            from attocode.integrations.quality.self_improvement import SelfImprovementManager
            ctx._self_improvement = SelfImprovementManager()  # type: ignore[attr-defined]
            results["self_improvement"] = True
        except Exception:
            results["self_improvement"] = False

    # 21. Health check
    if cfg.enable_health_check and not getattr(ctx, "_health_check", None):
        try:
            from attocode.integrations.quality.health_check import HealthCheckManager
            ctx._health_check = HealthCheckManager()  # type: ignore[attr-defined]
            results["health_check"] = True
        except Exception:
            results["health_check"] = False

    # 22. Injection budget manager
    if cfg.enable_injection_budget and not getattr(ctx, "_injection_budget", None):
        try:
            from attocode.integrations.budget.injection_budget import InjectionBudgetManager
            ctx._injection_budget = InjectionBudgetManager()  # type: ignore[attr-defined]
            results["injection_budget"] = True
        except Exception:
            results["injection_budget"] = False

    # 23. State machine
    if cfg.enable_state_machine and not getattr(ctx, '_state_machine', None):
        try:
            from attocode.integrations.utilities.state_machine import AgentStateMachine
            ctx._state_machine = AgentStateMachine()  # type: ignore[attr-defined]
            results["state_machine"] = True
        except Exception:
            results["state_machine"] = False

    # 24. Semantic cache
    if cfg.enable_semantic_cache and not getattr(ctx, '_semantic_cache', None):
        try:
            from attocode.integrations.context.semantic_cache import SemanticCacheManager
            ctx._semantic_cache = SemanticCacheManager(  # type: ignore[attr-defined]
                max_entries=cfg.semantic_cache_max_entries,
                ttl_seconds=cfg.semantic_cache_ttl_seconds,
                similarity_threshold=cfg.semantic_cache_similarity_threshold,
            )
            results["semantic_cache"] = True
        except Exception:
            results["semantic_cache"] = False

    # 25. Context engineering manager
    if cfg.enable_context_engineering and not getattr(ctx, '_context_engineering', None):
        try:
            from attocode.integrations.context.context_engineering import ContextEngineeringManager
            ce_kwargs: dict[str, Any] = {}
            if cfg.enable_diverse_serialization:
                try:
                    from attocode.tricks.serialization_diversity import DiverseSerializer
                    ce_kwargs["serializer"] = DiverseSerializer()
                except Exception:
                    pass
            ctx._context_engineering = ContextEngineeringManager(**ce_kwargs)  # type: ignore[attr-defined]
            results["context_engineering"] = True
        except Exception:
            results["context_engineering"] = False

    # 26. Skill manager (full lifecycle)
    if cfg.enable_skill_manager and working_dir and not getattr(ctx, '_skill_manager', None):
        try:
            from attocode.integrations.skills.loader import SkillLoader
            from attocode.integrations.skills.executor import SkillExecutor

            loader = SkillLoader(working_dir)
            # Search additional directories
            search_dirs = [working_dir]
            if cfg.skill_search_dirs:
                search_dirs.extend(cfg.skill_search_dirs)
            # Add user-level skills
            home_skill_dir = os.path.expanduser("~/.attocode/skills")
            if os.path.isdir(home_skill_dir):
                search_dirs.append(home_skill_dir)

            loader.load()
            executor = SkillExecutor(loader=loader)
            ctx._skill_manager = {  # type: ignore[attr-defined]
                "loader": loader,
                "executor": executor,
                "skills": loader.list_skills(),
            }
            results["skill_manager"] = True
        except Exception:
            results["skill_manager"] = False

    # 27. Work log
    if cfg.enable_work_log and not getattr(ctx, '_work_log', None):
        try:
            from attocode.integrations.tasks.work_log import WorkLog
            ctx._work_log = WorkLog()  # type: ignore[attr-defined]
            results["work_log"] = True
        except Exception:
            results["work_log"] = False

    # 28. Pending plan manager
    if cfg.enable_pending_plan and not getattr(ctx, '_pending_plan', None):
        try:
            from attocode.integrations.tasks.pending_plan import PendingPlanManager
            ctx._pending_plan = PendingPlanManager()  # type: ignore[attr-defined]
            results["pending_plan"] = True
        except Exception:
            results["pending_plan"] = False

    # Wire cross-references between features
    wire_cross_references(ctx, results)

    return results


def get_feature_summary(results: dict[str, bool]) -> str:
    """Generate a human-readable summary of initialized features."""
    enabled = [k for k, v in results.items() if v]
    failed = [k for k, v in results.items() if not v]

    parts = []
    if enabled:
        parts.append(f"Enabled: {', '.join(enabled)}")
    if failed:
        parts.append(f"Failed: {', '.join(failed)}")
    return " | ".join(parts) if parts else "No features initialized"


def wire_cross_references(ctx: AgentContext, results: dict[str, bool]) -> None:
    """Wire cross-references between initialized features.

    Some features need references to other features after all are
    initialized. This function sets up those connections.
    """
    # Wire economics into compaction manager for post-compaction baseline updates
    if results.get("economics") and results.get("compaction"):
        if ctx.economics and ctx.compaction_manager:
            try:
                ctx.compaction_manager.economics = ctx.economics
            except Exception:
                pass

    # Wire failure tracker into learning store for failure-based learnings
    if results.get("failure_tracking") and results.get("learning"):
        if ctx.failure_tracker and ctx.learning_store:
            try:
                ctx.learning_store.failure_tracker = ctx.failure_tracker
            except Exception:
                pass

    # Wire work log into economics for progress tracking
    if results.get("work_log") and results.get("economics"):
        work_log = getattr(ctx, '_work_log', None)
        if work_log and ctx.economics:
            try:
                ctx.economics._progress_source = work_log  # type: ignore[attr-defined]
            except Exception:
                pass

    # Wire semantic cache into context engineering
    if results.get("semantic_cache") and results.get("context_engineering"):
        cache = getattr(ctx, '_semantic_cache', None)
        ce = getattr(ctx, '_context_engineering', None)
        if cache and ce:
            try:
                ce.semantic_cache = cache
            except Exception:
                pass

    # Wire task manager into interactive planner
    if results.get("task_manager") and results.get("interactive_planner"):
        task_mgr = getattr(ctx, 'task_manager', None)
        planner = getattr(ctx, 'interactive_planner', None)
        if task_mgr and planner:
            try:
                planner.task_manager = task_mgr
            except Exception:
                pass
