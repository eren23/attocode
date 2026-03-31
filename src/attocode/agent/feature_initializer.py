"""Feature initializer - wires all integrations into the agent context.

This is the Python equivalent of the TS feature-initializer.ts.
It initializes economics, compaction, hooks, rules, ignore patterns,
recitation, failure tracking, and other optional integrations.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from attocode.types.budget import BudgetEnforcementMode

if TYPE_CHECKING:
    from attocode.agent.context import AgentContext

logger = logging.getLogger(__name__)


@dataclass(slots=True)
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
    enable_lsp: bool = True  # Lazy init = no cost until first LSP tool call
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
    enable_tool_recommendation: bool = True
    enable_thread_manager: bool = True
    enable_semantic_search_reindex: bool = True  # Auto-reindex on file change
    enable_diverse_serialization: bool = False  # Off by default
    enable_project_state: bool = True
    enable_dynamic_tools: bool = True
    enable_trajectory: bool = True

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


def initialize_features(
    ctx: AgentContext,
    *,
    config: FeatureConfig | None = None,
    project_root: str = "",
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
            logger.warning("feature_init_failed", extra={"feature": "economics"}, exc_info=True)
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
            logger.warning("feature_init_failed", extra={"feature": "compaction"}, exc_info=True)
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
            logger.warning("feature_init_failed", extra={"feature": "recitation"}, exc_info=True)
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
            logger.warning("feature_init_failed", extra={"feature": "failure_tracking"}, exc_info=True)
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
            logger.warning("feature_init_failed", extra={"feature": "learning"}, exc_info=True)
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
            logger.warning("feature_init_failed", extra={"feature": "auto_checkpoint"}, exc_info=True)
            results["auto_checkpoint"] = False

    # 7. Rules
    resource_root = project_root or working_dir

    if cfg.enable_rules and resource_root:
        try:
            from attocode.integrations.utilities.rules import RulesManager
            rules_mgr = RulesManager(resource_root)
            rules = rules_mgr.rules
            if rules:
                # Rules are added to system prompt via message_builder
                ctx._loaded_rules = rules
            results["rules"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "rules"}, exc_info=True)
            results["rules"] = False

    # 8. Ignore patterns
    if cfg.enable_ignore and working_dir:
        try:
            from attocode.integrations.utilities.ignore import IgnoreManager
            ignore_mgr = IgnoreManager(working_dir)
            ignore_mgr.load()
            ctx._ignore_manager = ignore_mgr
            results["ignore"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "ignore"}, exc_info=True)
            results["ignore"] = False

    # 9. Hooks
    if cfg.enable_hooks and working_dir:
        try:
            from attocode.integrations.utilities.hooks import HookManager
            hooks_mgr = HookManager(working_dir)
            hooks_mgr.load()
            ctx._hook_manager = hooks_mgr
            results["hooks"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "hooks"}, exc_info=True)
            results["hooks"] = False

    # 10. Mode manager
    if cfg.enable_mode_manager and ctx.mode_manager is None:
        try:
            from attocode.integrations.utilities.mode_manager import ModeManager
            ctx.mode_manager = ModeManager()
            results["mode_manager"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "mode_manager"}, exc_info=True)
            results["mode_manager"] = False

    # 11. File change tracker (for undo)
    if cfg.enable_file_tracking and ctx.file_change_tracker is None:
        try:
            from attocode.integrations.utilities.undo import FileChangeTracker
            ctx.file_change_tracker = FileChangeTracker()
            results["file_tracking"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "file_tracking"}, exc_info=True)
            results["file_tracking"] = False

    # 12. Safety manager (policy engine + execution policy)
    if cfg.enable_safety and not getattr(ctx, "safety_manager", None):
        try:
            from attocode.integrations.safety.execution_policy import ExecutionPolicy

            from attocode.integrations.safety.policy_engine import PolicyEngine

            policy_engine = PolicyEngine()
            exec_policy = ExecutionPolicy()
            # Store on context for the execution loop to use
            ctx._safety_policy_engine = policy_engine
            ctx._execution_policy = exec_policy
            results["safety"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "safety"}, exc_info=True)
            results["safety"] = False

    # 13. Planning manager
    if cfg.enable_planning and not getattr(ctx, "_planning_manager", None):
        try:
            from attocode.integrations.tasks.planning import PlanningManager
            ctx._planning_manager = PlanningManager()
            results["planning"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "planning"}, exc_info=True)
            results["planning"] = False

    # 14. Task manager
    if cfg.enable_task_manager and not getattr(ctx, "task_manager", None):
        try:
            from attocode.integrations.tasks.task_manager import TaskManager
            ctx.task_manager = TaskManager()
            results["task_manager"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "task_manager"}, exc_info=True)
            results["task_manager"] = False

    # --- Yield to event loop (keep TUI responsive during init) ---
    # (yield point removed — function is now sync, runs in thread)

    # 15. Codebase context
    if cfg.enable_codebase_context and working_dir and not getattr(ctx, "codebase_context", None):
        try:
            from attocode.integrations.context.codebase_context import CodebaseContextManager
            ctx.codebase_context = CodebaseContextManager(
                root_dir=working_dir,
            )
            results["codebase_context"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "codebase_context"}, exc_info=True)
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
            logger.warning("feature_init_failed", extra={"feature": "codebase_overview_tool"}, exc_info=True)
            results["codebase_overview_tool"] = False

    # 16. Interactive planner
    if cfg.enable_interactive_planner and not getattr(ctx, "interactive_planner", None):
        try:
            from attocode.integrations.tasks.interactive_planning import InteractivePlanner
            ctx.interactive_planner = InteractivePlanner()
            results["interactive_planner"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "interactive_planner"}, exc_info=True)
            results["interactive_planner"] = False

    # 17. LSP manager (opt-in)
    if cfg.enable_lsp and working_dir and not getattr(ctx, "_lsp_manager", None):
        try:
            from attocode.integrations.lsp.client import LSPConfig, LSPManager
            lsp_config = LSPConfig(
                enabled=True,
                root_uri=f"file://{os.path.abspath(working_dir)}",
            )
            lsp = LSPManager(config=lsp_config)
            ctx._lsp_manager = lsp
            results["lsp"] = True
        except Exception:
            logger.debug("feature_init_failed", extra={"feature": "lsp"}, exc_info=True)
            results["lsp"] = False

    # 17b. Register LSP tools (requires lsp_manager and registry)
    lsp = getattr(ctx, "_lsp_manager", None)
    if lsp and hasattr(ctx, "registry") and ctx.registry is not None:
        try:
            from attocode.tools.lsp import create_lsp_tools
            for tool in create_lsp_tools(lsp):
                ctx.registry.register(tool)
            results["lsp_tools"] = True
        except Exception:
            logger.debug("feature_init_failed", extra={"feature": "lsp_tools"}, exc_info=True)
            results["lsp_tools"] = False

    # 15c. Register hierarchical explorer tool (requires codebase context)
    if cbc and hasattr(ctx, "registry") and ctx.registry is not None:
        try:
            from attocode.integrations.context.ast_service import ASTService
            from attocode.integrations.context.hierarchical_explorer import HierarchicalExplorer
            from attocode.tools.explore import create_explore_tool

            ast_svc = None
            try:
                ast_svc = ASTService.get_instance(working_dir) if working_dir else None
            except Exception:
                pass

            if ast_svc:
                ctx._ast_service = ast_svc
            explorer = HierarchicalExplorer(cbc, ast_service=ast_svc)
            ctx._hierarchical_explorer = explorer
            explore_tool = create_explore_tool(explorer)
            ctx.registry.register(explore_tool)
            results["hierarchical_explorer"] = True
        except Exception:
            logger.debug("feature_init_failed", extra={"feature": "hierarchical_explorer"}, exc_info=True)
            results["hierarchical_explorer"] = False

    # --- Yield to event loop (keep TUI responsive) ---
    # (yield point removed — function is now sync, runs in thread)

    # 18. Cancellation manager
    if cfg.enable_cancellation and not getattr(ctx, "cancellation_manager", None):
        try:
            from attocode.integrations.budget.cancellation import CancellationManager
            ctx.cancellation_manager = CancellationManager()
            results["cancellation"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "cancellation"}, exc_info=True)
            results["cancellation"] = False

    # 19. Dead letter queue
    if cfg.enable_dead_letter_queue and not getattr(ctx, "_dead_letter_queue", None):
        try:
            from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
            ctx._dead_letter_queue = DeadLetterQueue()
            results["dead_letter_queue"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "dead_letter_queue"}, exc_info=True)
            results["dead_letter_queue"] = False

    # 20. Self-improvement
    if cfg.enable_self_improvement and not getattr(ctx, "_self_improvement", None):
        try:
            from attocode.integrations.quality.self_improvement import SelfImprovementProtocol
            ctx._self_improvement = SelfImprovementProtocol()
            results["self_improvement"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "self_improvement"}, exc_info=True)
            results["self_improvement"] = False

    # 21. Tool recommendation engine
    if cfg.enable_tool_recommendation and not getattr(ctx, "_tool_recommender", None):
        try:
            from attocode.integrations.quality.tool_recommendation import ToolRecommendationEngine
            ctx._tool_recommender = ToolRecommendationEngine()
            results["tool_recommendation"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "tool_recommendation"}, exc_info=True)
            results["tool_recommendation"] = False

    # 22. Health check
    if cfg.enable_health_check and not getattr(ctx, "_health_check", None):
        try:
            from attocode.integrations.quality.health_check import HealthChecker
            ctx._health_check = HealthChecker()
            results["health_check"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "health_check"}, exc_info=True)
            results["health_check"] = False

    # 23. Injection budget manager
    if cfg.enable_injection_budget and not getattr(ctx, "_injection_budget", None):
        try:
            from attocode.integrations.budget.injection_budget import InjectionBudgetManager
            ctx._injection_budget = InjectionBudgetManager()
            results["injection_budget"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "injection_budget"}, exc_info=True)
            results["injection_budget"] = False

    # 24. State machine
    if cfg.enable_state_machine and not getattr(ctx, '_state_machine', None):
        try:
            from attocode.integrations.utilities.state_machine import AgentStateMachine
            ctx._state_machine = AgentStateMachine()
            results["state_machine"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "state_machine"}, exc_info=True)
            results["state_machine"] = False

    # 25. Semantic cache
    if cfg.enable_semantic_cache and not getattr(ctx, '_semantic_cache', None):
        try:
            from attocode.integrations.context.semantic_cache import (
                SemanticCacheConfig,
                SemanticCacheManager,
            )
            cache_config = SemanticCacheConfig(
                enabled=True,
                max_size=cfg.semantic_cache_max_entries,
                ttl=int(cfg.semantic_cache_ttl_seconds),
                threshold=cfg.semantic_cache_similarity_threshold,
            )
            ctx._semantic_cache = SemanticCacheManager(config=cache_config)
            results["semantic_cache"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "semantic_cache"}, exc_info=True)
            results["semantic_cache"] = False

    # 26. Context engineering manager
    if cfg.enable_context_engineering and not getattr(ctx, '_context_engineering', None):
        try:
            from attocode.integrations.context.context_engineering import ContextEngineeringManager
            ce_kwargs: dict[str, Any] = {}
            if cfg.enable_diverse_serialization:
                try:
                    from attocode.tricks.serialization_diversity import DiverseSerializer
                    ce_kwargs["serializer"] = DiverseSerializer()
                except Exception:
                    logger.debug("feature_init_failed", extra={"feature": "diverse_serialization"}, exc_info=True)
            ctx._context_engineering = ContextEngineeringManager(**ce_kwargs)
            results["context_engineering"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "context_engineering"}, exc_info=True)
            results["context_engineering"] = False

    # 27. Skill manager (full lifecycle)
    if cfg.enable_skill_manager and resource_root and not getattr(ctx, '_skill_manager', None):
        try:
            from attocode.integrations.skills.dependency_graph import SkillDependencyGraph
            from attocode.integrations.skills.executor import SkillExecutor
            from attocode.integrations.skills.loader import SkillLoader
            from attocode.integrations.skills.state import SkillStateStore

            loader = SkillLoader(resource_root)
            # Search additional directories
            search_dirs = [working_dir]
            if cfg.skill_search_dirs:
                search_dirs.extend(cfg.skill_search_dirs)
            # Add user-level skills
            home_skill_dir = os.path.expanduser("~/.attocode/skills")
            if os.path.isdir(home_skill_dir):
                search_dirs.append(home_skill_dir)

            loader.load()

            # Wire state store for long-running skill persistence
            state_store = SkillStateStore(session_dir=session_dir) if session_dir else None

            # Build dependency graph from loaded skills
            dep_graph = SkillDependencyGraph()
            for skill in loader.list_skills():
                dep_graph.add_skill(skill)

            executor = SkillExecutor(
                loader=loader,
                state_store=state_store,
                dependency_graph=dep_graph,
            )

            ctx._skill_manager = {
                "loader": loader,
                "executor": executor,
                "dependency_graph": dep_graph,
                "skills": loader.list_skills(),
            }
            results["skill_manager"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "skill_manager"}, exc_info=True)
            results["skill_manager"] = False

    # 28. Work log
    if cfg.enable_work_log and not getattr(ctx, '_work_log', None):
        try:
            from attocode.integrations.tasks.work_log import WorkLog
            ctx._work_log = WorkLog()
            results["work_log"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "work_log"}, exc_info=True)
            results["work_log"] = False

    # 29. Pending plan manager
    if cfg.enable_pending_plan and not getattr(ctx, '_pending_plan', None):
        try:
            from attocode.integrations.tasks.pending_plan import PendingPlanManager
            ctx._pending_plan = PendingPlanManager()
            results["pending_plan"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "pending_plan"}, exc_info=True)
            results["pending_plan"] = False

    # 30. Security scanner
    if working_dir and hasattr(ctx, "registry") and ctx.registry is not None:
        try:
            from attocode.integrations.security.scanner import SecurityScanner
            from attocode.tools.security import create_security_scan_tool

            scanner = SecurityScanner(root_dir=working_dir)
            ctx._security_scanner = scanner
            sec_tool = create_security_scan_tool(scanner)
            ctx.registry.register(sec_tool)
            results["security_scanner"] = True
        except Exception:
            logger.debug("feature_init_failed", extra={"feature": "security_scanner"}, exc_info=True)
            results["security_scanner"] = False

    # --- Yield to event loop (keep TUI responsive) ---
    # (yield point removed — function is now sync, runs in thread)

    # 31. Semantic search (optional — degrades gracefully if no embedding provider)
    if working_dir and hasattr(ctx, "registry") and ctx.registry is not None:
        try:
            from attocode.integrations.context.semantic_search import SemanticSearchManager
            from attocode.tools.semantic_search import create_semantic_search_tool

            sem_mgr = SemanticSearchManager(root_dir=working_dir)
            ctx._semantic_search = sem_mgr
            sem_tool = create_semantic_search_tool(sem_mgr)
            ctx.registry.register(sem_tool)
            results["semantic_search"] = True
            logger.info("Semantic search: provider=%s", sem_mgr.provider_name)
        except Exception:
            logger.debug("feature_init_failed", extra={"feature": "semantic_search"}, exc_info=True)
            results["semantic_search"] = False

    # 32. Thread manager
    if cfg.enable_thread_manager and not getattr(ctx, "thread_manager", None):
        try:
            from attocode.integrations.utilities.thread_manager import ThreadManager
            sid = getattr(ctx, "session_id", "") or ""
            ctx.thread_manager = ThreadManager(session_id=sid)
            results["thread_manager"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "thread_manager"}, exc_info=True)
            results["thread_manager"] = False

    # 33. Background semantic search reindex (stale files on startup)
    sem_search = getattr(ctx, "_semantic_search", None)
    if cfg.enable_semantic_search_reindex and sem_search and getattr(sem_search, "is_available", False):
        try:
            import threading

            def _bg_reindex() -> None:
                try:
                    count = sem_search.reindex_stale_files()
                    if count > 0:
                        logger.info("Background reindex: %d chunks refreshed", count)
                except Exception:
                    logger.debug("background_reindex_failed", exc_info=True)

            t = threading.Thread(target=_bg_reindex, daemon=True, name="semantic-reindex")
            t.start()
            results["semantic_reindex_bg"] = True
        except Exception:
            logger.debug("feature_init_failed", extra={"feature": "semantic_reindex_bg"}, exc_info=True)
            results["semantic_reindex_bg"] = False

    # 34. Project state (file-driven)
    if cfg.enable_project_state and not getattr(ctx, "project_state", None):
        try:
            from pathlib import Path

            from attocode.integrations.persistence.project_state import ProjectStateManager

            pr = project_root or getattr(ctx, "project_root", "")
            if pr:
                ctx.project_state = ProjectStateManager(Path(pr))
                ctx.project_state.load()
                results["project_state"] = True
            else:
                results["project_state"] = False
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "project_state"}, exc_info=True)
            results["project_state"] = False

    # 35. Dynamic tool registry
    if cfg.enable_dynamic_tools and not getattr(ctx, "dynamic_tools", None):
        try:
            from pathlib import Path

            from attocode.tools.dynamic import DynamicToolRegistry

            pr = project_root or getattr(ctx, "project_root", "")
            persist_dir = Path(pr) / ".attocode" / "tools" if pr else None
            ctx.dynamic_tools = DynamicToolRegistry(persist_dir=persist_dir)
            if persist_dir:
                ctx.dynamic_tools.load_persisted()
            results["dynamic_tools"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "dynamic_tools"}, exc_info=True)
            results["dynamic_tools"] = False

    # 36. Trajectory analysis
    if cfg.enable_trajectory and not getattr(ctx, "trajectory_tracker", None):
        try:
            from attocode.integrations.quality.trajectory import TrajectoryTracker

            ctx.trajectory_tracker = TrajectoryTracker()
            results["trajectory"] = True
        except Exception:
            logger.warning("feature_init_failed", extra={"feature": "trajectory"}, exc_info=True)
            results["trajectory"] = False

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
    if results.get("economics") and results.get("compaction") and ctx.economics and ctx.compaction_manager:
        try:
            ctx.compaction_manager.economics = ctx.economics
        except Exception:
            logger.warning("cross_ref_failed", extra={"ref": "economics->compaction"}, exc_info=True)

    # Wire failure tracker into learning store for failure-based learnings
    if results.get("failure_tracking") and results.get("learning") and ctx.failure_tracker and ctx.learning_store:
        try:
            ctx.learning_store.failure_tracker = ctx.failure_tracker
        except Exception:
            logger.warning("cross_ref_failed", extra={"ref": "failure->learning"}, exc_info=True)

    # Wire work log into economics for progress tracking
    if results.get("work_log") and results.get("economics"):
        work_log = getattr(ctx, '_work_log', None)
        if work_log and ctx.economics:
            try:
                ctx.economics._progress_source = work_log  # type: ignore[attr-defined]
            except Exception:
                logger.warning("cross_ref_failed", extra={"ref": "work_log->economics"}, exc_info=True)

    # Wire semantic cache into context engineering
    if results.get("semantic_cache") and results.get("context_engineering"):
        cache = getattr(ctx, '_semantic_cache', None)
        ce = getattr(ctx, '_context_engineering', None)
        if cache and ce:
            try:
                ce.semantic_cache = cache
            except Exception:
                logger.warning("cross_ref_failed", extra={"ref": "semantic_cache->context_engineering"}, exc_info=True)

    # Wire task manager into interactive planner
    if results.get("task_manager") and results.get("interactive_planner"):
        task_mgr = getattr(ctx, 'task_manager', None)
        planner = getattr(ctx, 'interactive_planner', None)
        if task_mgr and planner:
            try:
                planner.task_manager = task_mgr
            except Exception:
                logger.warning("cross_ref_failed", extra={"ref": "task_manager->interactive_planner"}, exc_info=True)
