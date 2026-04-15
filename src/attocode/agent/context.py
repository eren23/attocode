"""AgentContext - dependency bundle for the agent execution engine."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from attocode.types.agent import AgentConfig, AgentMetrics
from attocode.types.budget import STANDARD_BUDGET, ExecutionBudget
from attocode.types.events import AgentEvent, EventType

if TYPE_CHECKING:
    from attocode.integrations.safety.execution_policy import ExecutionPolicy
    from attocode.integrations.utilities.state_machine import AgentStateMachine

    from attocode.integrations.budget.cancellation import CancellationManager
    from attocode.integrations.budget.economics import ExecutionEconomicsManager
    from attocode.integrations.budget.injection_budget import InjectionBudgetManager
    from attocode.integrations.context.ast_service import ASTService
    from attocode.integrations.context.auto_compaction import AutoCompactionManager
    from attocode.integrations.context.codebase_context import CodebaseContextManager
    from attocode.integrations.context.context_engineering import ContextEngineeringManager
    from attocode.integrations.context.hierarchical_explorer import HierarchicalExplorer
    from attocode.integrations.context.semantic_cache import SemanticCacheManager
    from attocode.integrations.context.semantic_search import SemanticSearchManager
    from attocode.integrations.lsp.client import LSPManager
    from attocode.integrations.persistence.project_state import ProjectStateManager
    from attocode.integrations.quality.auto_checkpoint import AutoCheckpointManager
    from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
    from attocode.integrations.quality.health_check import HealthChecker
    from attocode.integrations.quality.learning_store import LearningStore
    from attocode.integrations.quality.self_improvement import SelfImprovementProtocol
    from attocode.integrations.quality.tool_recommendation import ToolRecommendationEngine
    from attocode.integrations.quality.trajectory import TrajectoryTracker
    from attocode.integrations.safety.pattern_rules import PatternRuleEngine
    from attocode.integrations.safety.policy_engine import PolicyEngine
    from attocode.integrations.security.scanner import SecurityScanner
    from attocode.integrations.tasks.interactive_planning import InteractivePlanner
    from attocode.integrations.tasks.pending_plan import PendingPlanManager
    from attocode.integrations.tasks.planning import PlanningManager
    from attocode.integrations.tasks.task_manager import TaskManager
    from attocode.integrations.tasks.work_log import WorkLog
    from attocode.integrations.utilities.hooks import HookManager
    from attocode.integrations.utilities.ignore import IgnoreManager
    from attocode.integrations.utilities.mode_manager import ModeManager
    from attocode.integrations.utilities.thread_manager import ThreadManager
    from attocode.integrations.utilities.undo import FileChangeTracker
    from attocode.providers.base import LLMProvider
    from attocode.tools.dynamic import DynamicToolRegistry
    from attocode.tools.registry import ToolRegistry
    from attocode.tricks.failure_evidence import FailureTracker
    from attocode.tricks.recitation import RecitationManager
    from attocode.types.messages import Message, MessageWithStructuredContent

EventHandler = Callable[[AgentEvent], Any]
ApprovalCallback = Callable[..., Any]  # async (tool_name, args, danger, context) -> ApprovalResult

# Type alias for the skill manager dict (not a class — assembled in feature_initializer)
SkillManagerDict = dict[str, Any]


@dataclass
class AgentContext:
    """Bundle of all dependencies needed by the execution engine.

    This is the single object threaded through the execution loop,
    tool executor, response handler, and completion analyzer.
    """

    # Core dependencies
    provider: LLMProvider
    registry: ToolRegistry
    config: AgentConfig = field(default_factory=AgentConfig)
    budget: ExecutionBudget = field(default_factory=lambda: STANDARD_BUDGET)

    # State
    messages: list[Message | MessageWithStructuredContent] = field(default_factory=list)
    metrics: AgentMetrics = field(default_factory=AgentMetrics)
    iteration: int = 0

    # Cancellation
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    # Event system
    _event_handlers: list[EventHandler] = field(default_factory=list, repr=False)

    # System prompt
    system_prompt: str | None = None

    # Working directory
    working_dir: str = ""
    project_root: str = ""

    # Policy engine (optional - if None, all tools are auto-approved)
    policy_engine: PolicyEngine | None = None

    # Approval callback (optional - for TUI/interactive approval)
    approval_callback: ApprovalCallback | None = None

    # Economics manager (optional - for budget tracking)
    economics: ExecutionEconomicsManager | None = None

    # Auto-compaction manager (optional)
    compaction_manager: AutoCompactionManager | None = None

    # Session store (optional)
    session_store: Any = None  # SessionStore — no single class; keep Any
    session_id: str | None = None

    # Context engineering tricks (optional)
    recitation_manager: RecitationManager | None = None
    failure_tracker: FailureTracker | None = None

    # Learning store (optional)
    learning_store: LearningStore | None = None

    # Auto-checkpoint (optional)
    auto_checkpoint: AutoCheckpointManager | None = None

    # MCP server configs (optional)
    mcp_server_configs: list[dict[str, Any]] = field(default_factory=list)

    # Goal (for recitation)
    goal: str | None = None

    # Mode manager (optional - for build/plan/review/debug modes)
    mode_manager: ModeManager | None = None

    # File change tracker (optional - for undo capability)
    file_change_tracker: FileChangeTracker | None = None

    # Thread manager (optional - for conversation forking)
    thread_manager: ThreadManager | None = None

    # Trace collector (optional - for execution tracing)
    trace_collector: Any = None  # TraceCollector — import path varies; keep Any

    # --- Integration slots (initialized by feature_initializer) ---
    cancellation_manager: CancellationManager | None = None
    codebase_context: CodebaseContextManager | None = None
    interactive_planner: InteractivePlanner | None = None
    task_manager: TaskManager | None = None
    _context_engineering: ContextEngineeringManager | None = None
    _dead_letter_queue: DeadLetterQueue | None = None
    _execution_policy: ExecutionPolicy | None = None
    _health_check: HealthChecker | None = None
    _hook_manager: HookManager | None = None
    _ignore_manager: IgnoreManager | None = None
    _injection_budget: InjectionBudgetManager | None = None
    _loaded_rules: list[str] = field(default_factory=list)
    _lsp_manager: LSPManager | None = None
    _pending_plan: PendingPlanManager | None = None
    _planning_manager: PlanningManager | None = None
    _safety_policy_engine: PolicyEngine | None = None
    _self_improvement: SelfImprovementProtocol | None = None
    _tool_recommender: ToolRecommendationEngine | None = None
    _semantic_cache: SemanticCacheManager | None = None
    _skill_manager: SkillManagerDict | None = None
    _state_machine: AgentStateMachine | None = None
    _work_log: WorkLog | None = None
    _semantic_search: SemanticSearchManager | None = None
    _security_scanner: SecurityScanner | None = None

    # --- Slots set by feature_initializer but not in original field list ---
    _pattern_rule_engine: PatternRuleEngine | None = None
    _ast_service: ASTService | None = None
    _hierarchical_explorer: HierarchicalExplorer | None = None
    project_state: ProjectStateManager | None = None
    dynamic_tools: DynamicToolRegistry | None = None
    trajectory_tracker: TrajectoryTracker | None = None

    # --- Slots set by run_context_builder (wired from ProductionAgent) ---
    extension_handler: Any = None  # BudgetExtensionHandler (callable alias)
    safety_manager: Any = None  # Varies by caller; keep Any
    multi_agent_manager: Any = None  # Varies by caller; keep Any

    def on_event(self, handler: EventHandler) -> None:
        """Register an event handler."""
        self._event_handlers.append(handler)

    def emit(self, event: AgentEvent) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception:
                pass  # Event handlers should not break the loop

    def emit_simple(
        self,
        event_type: EventType,
        **kwargs: Any,
    ) -> None:
        """Emit a simple event with keyword arguments."""
        self.emit(AgentEvent(type=event_type, **kwargs))

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()

    def cancel(self) -> None:
        """Request cancellation of the current execution."""
        self.cancelled.set()

    def check_iteration_budget(self) -> bool:
        """Check if we've exceeded the iteration limit.

        Returns True if we should continue, False if we should stop.
        """
        max_iter = self.budget.max_iterations or self.config.max_iterations
        return not (max_iter and self.iteration >= max_iter)

    def check_token_budget(self) -> bool:
        """Check if we've exceeded the token budget.

        Returns True if we should continue, False if we should stop.
        """
        return not (self.budget.max_tokens and self.metrics.total_tokens >= self.budget.max_tokens)

    def add_message(self, message: Message | MessageWithStructuredContent) -> None:
        """Add a message to the conversation history."""
        self.messages.append(message)

    def add_messages(self, messages: list[Message | MessageWithStructuredContent]) -> None:
        """Add multiple messages to the conversation history."""
        self.messages.extend(messages)
