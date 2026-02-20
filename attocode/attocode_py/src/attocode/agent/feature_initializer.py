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

    # Tuning
    compaction_max_tokens: int = 200_000
    compaction_warning_threshold: float = 0.7
    compaction_threshold: float = 0.8
    recitation_interval: int = 10
    checkpoint_interval: int = 5
    max_failures_tracked: int = 20


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
