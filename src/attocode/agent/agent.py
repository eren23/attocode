"""ProductionAgent - the main orchestrator for agent execution."""

from __future__ import annotations

import logging
from typing import Any, Callable

from attocode.agent.context import AgentContext, EventHandler
from attocode.providers.base import LLMProvider, get_model_context_window
from attocode.tools.registry import ToolRegistry
from attocode.types.agent import AgentConfig, AgentMetrics, AgentResult, AgentStatus
from attocode.types.budget import ExecutionBudget, STANDARD_BUDGET
from attocode.types.events import EventType
from attocode.types.messages import Message

logger = logging.getLogger(__name__)

# Type alias for budget extension handler: receives request dict, returns bool (granted)
BudgetExtensionHandler = Callable[[dict[str, Any]], Any]


class ProductionAgent:
    """Main agent orchestrator.

    Coordinates the LLM provider, tool registry, budget, and execution loop
    to run an AI coding agent that can use tools to accomplish tasks.
    """

    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        *,
        config: AgentConfig | None = None,
        budget: ExecutionBudget | None = None,
        system_prompt: str | None = None,
        working_dir: str = "",
        policy_engine: Any = None,
        approval_callback: Any = None,
        economics: Any = None,
        compaction_manager: Any = None,
        session_dir: str | None = None,
        mcp_server_configs: list[dict[str, Any]] | None = None,
        learning_store: Any = None,
        auto_checkpoint: Any = None,
        recitation_manager: Any = None,
        failure_tracker: Any = None,
        safety_manager: Any = None,
        task_manager: Any = None,
        interactive_planner: Any = None,
        codebase_context: Any = None,
        multi_agent_manager: Any = None,
        cancellation_manager: Any = None,
        recording_config: Any = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._config = config or AgentConfig()
        self._budget = budget or STANDARD_BUDGET
        self._system_prompt = system_prompt
        self._working_dir = working_dir
        self._status = AgentStatus.IDLE
        self._event_handlers: list[EventHandler] = []
        self._ctx: AgentContext | None = None
        self._policy_engine = policy_engine
        self._approval_callback = approval_callback
        self._economics = economics
        self._compaction_manager = compaction_manager
        self._session_dir = session_dir
        self._mcp_server_configs = mcp_server_configs
        self._learning_store = learning_store
        self._auto_checkpoint = auto_checkpoint
        self._recitation_manager = recitation_manager
        self._failure_tracker = failure_tracker
        self._safety_manager = safety_manager
        self._task_manager = task_manager
        self._interactive_planner = interactive_planner
        self._codebase_context = codebase_context
        self._multi_agent_manager = multi_agent_manager
        self._cancellation_manager = cancellation_manager
        self._recording_config = recording_config
        self._recorder: Any = None  # RecordingSessionManager instance
        self._file_change_tracker: Any = None  # Persists across runs for /diff, /undo
        self._mode_manager: Any = None  # Persists across runs for /mode, /plan
        self._extension_handler: BudgetExtensionHandler | None = None
        self._run_count: int = 0
        self._total_tokens_all_runs: int = 0
        self._total_cost_all_runs: float = 0.0
        self._subagent_registry: dict[str, Any] = {}
        self._mcp_client_manager: Any = None  # MCPClientManager, set during _connect_mcp_servers()
        self._swarm_orchestrator: Any = None
        self._event_bridge: Any = None
        self._tui_swarm_callback: Callable[[dict], None] | None = None
        self._ast_server: Any = None
        self._thread_manager: Any = None
        self._trace_collector: Any = None
        self._session_store: Any = None       # Persists across runs for /goals, /audit, /grants, etc.
        self._session_id: str | None = None   # Current session ID
        self._conversation_messages: list[Message] = []  # Persists across TUI runs
        self._last_image_warning: str | None = None  # Warning when images are dropped

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def budget(self) -> ExecutionBudget:
        return self._budget

    @property
    def working_dir(self) -> str:
        return self._working_dir

    @property
    def context(self) -> AgentContext | None:
        """The current execution context, if running."""
        return self._ctx

    @property
    def event_bridge(self) -> Any:
        """The swarm event bridge, if swarm mode is active."""
        return self._event_bridge

    @property
    def swarm_orchestrator(self) -> Any:
        """The swarm orchestrator, if swarm mode is active."""
        return self._swarm_orchestrator

    def set_tui_swarm_callback(self, cb: Callable[[dict], None] | None) -> None:
        """Set a callback that receives swarm events for TUI rendering."""
        self._tui_swarm_callback = cb

    @property
    def session_store(self) -> Any:
        """The session store, if configured."""
        return self._session_store

    @property
    def session_id(self) -> str | None:
        """The current session ID."""
        return self._session_id

    async def persist_grant(
        self,
        tool_name: str,
        pattern: str = "*",
        perm_type: str = "allow",
    ) -> bool:
        """Persist a tool permission grant to the session store.

        Returns True if the grant was persisted, False otherwise.
        """
        if not self._session_store or not self._session_id:
            return False
        try:
            await self._session_store.grant_permission(
                self._session_id, tool_name, pattern, perm_type,
            )
            return True
        except Exception:
            logger.debug("grant_permission failed", exc_info=True)
            return False

    def on_event(self, handler: EventHandler) -> None:
        """Register an event handler."""
        self._event_handlers.append(handler)

    def set_extension_handler(self, handler: BudgetExtensionHandler) -> None:
        """Set a handler for budget extension requests.

        The handler is called when the agent approaches budget limits
        and wants to request more tokens. Used by TUI to show budget
        extension dialog.
        """
        self._extension_handler = handler

    async def ensure_session_store(self) -> Any:
        """Ensure session persistence store is initialized and return it."""
        if self._session_store is not None:
            return self._session_store
        if not self._session_dir:
            return None
        try:
            from pathlib import Path
            from attocode.integrations.persistence.store import SessionStore

            db_path = Path(self._session_dir) / "sessions.db"
            self._session_store = SessionStore(db_path)
            await self._session_store.initialize()
            return self._session_store
        except Exception:
            logger.warning("session_store_init_failed", exc_info=True)
            self._session_store = None
            return None

    async def ensure_command_context(self) -> AgentContext:
        """Ensure a lightweight context exists for slash commands before first run."""
        if self._ctx is not None:
            return self._ctx

        ctx = AgentContext(
            provider=self._provider,
            registry=self._registry,
            config=self._config,
            budget=self._budget,
            working_dir=self._working_dir,
            system_prompt=self._system_prompt,
            policy_engine=self._policy_engine,
            approval_callback=self._approval_callback,
            economics=self._economics,
            compaction_manager=self._compaction_manager,
            recitation_manager=self._recitation_manager,
            failure_tracker=self._failure_tracker,
            learning_store=self._learning_store,
            auto_checkpoint=self._auto_checkpoint,
            mcp_server_configs=self._mcp_server_configs or [],
        )

        # Reuse persistent command-related managers when available.
        if self._mode_manager is not None:
            ctx.mode_manager = self._mode_manager
        if self._file_change_tracker is not None:
            ctx.file_change_tracker = self._file_change_tracker
        if self._thread_manager is not None:
            ctx.thread_manager = self._thread_manager

        # Create command-critical managers if missing.
        if ctx.mode_manager is None:
            try:
                from attocode.integrations.utilities.mode_manager import ModeManager
                ctx.mode_manager = ModeManager()
            except Exception:
                logger.debug("mode_manager_init_failed", exc_info=True)
        if ctx.file_change_tracker is None:
            try:
                from attocode.integrations.utilities.undo import FileChangeTracker
                ctx.file_change_tracker = FileChangeTracker()
            except Exception:
                logger.debug("file_change_tracker_init_failed", exc_info=True)
        if ctx.thread_manager is None:
            try:
                from attocode.integrations.utilities.thread_manager import ThreadManager
                sid = self._session_id or ""
                ctx.thread_manager = ThreadManager(session_id=sid)
            except Exception:
                logger.debug("thread_manager_init_failed", exc_info=True)

        # Persist manager instances for future runs.
        if ctx.mode_manager is not None:
            self._mode_manager = ctx.mode_manager
        if ctx.file_change_tracker is not None:
            self._file_change_tracker = ctx.file_change_tracker
        if ctx.thread_manager is not None:
            self._thread_manager = ctx.thread_manager

        self._ctx = ctx
        return ctx

    def apply_budget_extension(self, additional_tokens: int) -> int:
        """Extend token budget and sync agent/context/economics references.

        Returns the new max token budget.
        """
        if additional_tokens <= 0:
            return self._budget.max_tokens

        old_budget = self._budget
        new_max = old_budget.max_tokens + additional_tokens
        new_soft: int | None = None
        if old_budget.soft_token_limit is not None and old_budget.max_tokens > 0:
            ratio = old_budget.soft_token_limit / old_budget.max_tokens
            new_soft = int(new_max * ratio)

        new_budget = ExecutionBudget(
            max_tokens=new_max,
            soft_token_limit=new_soft,
            max_cost=old_budget.max_cost,
            max_duration_seconds=old_budget.max_duration_seconds,
            max_iterations=old_budget.max_iterations,
            enforcement_mode=old_budget.enforcement_mode,
        )
        self._budget = new_budget
        if self._ctx:
            self._ctx.budget = new_budget
            if self._ctx.economics:
                self._ctx.economics.budget = new_budget
        return new_max

    # --- Integration getters ---

    def get_economics(self) -> Any:
        """Get the economics manager (if initialized)."""
        if self._ctx and self._ctx.economics:
            return self._ctx.economics
        return self._economics

    def get_learning_store(self) -> Any:
        """Get the learning store."""
        if self._ctx and self._ctx.learning_store:
            return self._ctx.learning_store
        return self._learning_store

    def get_interactive_planner(self) -> Any:
        """Get the interactive planner."""
        return self._interactive_planner

    def get_task_manager(self) -> Any:
        """Get the task manager."""
        return self._task_manager

    def get_safety_manager(self) -> Any:
        """Get the safety manager."""
        return self._safety_manager

    def get_codebase_context(self) -> Any:
        """Get the codebase context manager."""
        return self._codebase_context

    def get_multi_agent_manager(self) -> Any:
        """Get the multi-agent manager."""
        return self._multi_agent_manager

    @property
    def recorder(self) -> Any:
        """Get the recording session manager (if active)."""
        return self._recorder

    def get_context_usage(self) -> float:
        """Get context window usage as a fraction (0.0 to 1.0)."""
        if not self._ctx:
            return 0.0
        total_chars = sum(
            len(getattr(m, "content", "") or "")
            for m in self._ctx.messages
        )
        estimated_tokens = total_chars // 4
        max_context = get_model_context_window(self._config.model or "")
        return min(estimated_tokens / max_context, 1.0)

    def get_metrics(self) -> AgentMetrics:
        """Get current metrics (works across runs)."""
        if self._ctx:
            return self._ctx.metrics
        return AgentMetrics()

    def get_run_count(self) -> int:
        """Get the number of runs completed."""
        return self._run_count

    def pause(self) -> None:
        """Pause duration tracking (for approval waits, etc.)."""
        if self._ctx and self._ctx.economics:
            self._ctx.economics.pause_duration()

    def resume(self) -> None:
        """Resume duration tracking."""
        if self._ctx and self._ctx.economics:
            self._ctx.economics.resume_duration()

    async def run(self, prompt: str, *, images: list[str] | None = None) -> AgentResult:
        """Run the agent with the given prompt.

        This is the main entry point for agent execution.
        Builds context, initializes messages, and runs the execution loop.

        Args:
            prompt: The user's text prompt.
            images: Optional list of image file paths to include inline.
        """
        # Check vision capability — strip images early with user-facing warning
        if images:
            provider_name = getattr(self._provider, "name", "unknown")
            # Level 1: provider doesn't support vision at all
            # getattr used because providers implement LLMProvider via structural
            # typing (Protocol), not subclass — attribute may not exist on all impls.
            if not getattr(self._provider, "supports_vision", True):
                warning = (
                    f"Images not sent — the {provider_name} provider does not "
                    f"support inline images currently."
                )
                logger.warning(warning)
                self._last_image_warning = warning
                images = None
            else:
                # Level 2: specific model doesn't support vision
                from attocode.providers.model_cache import is_vision_capable

                model = self._config.model if self._config else ""
                if model and not is_vision_capable(model):
                    warning = (
                        f"Images not sent — model {model} does not support "
                        f"vision input."
                    )
                    logger.warning(warning)
                    self._last_image_warning = warning
                    images = None

        if self._status == AgentStatus.RUNNING:
            return AgentResult(
                success=False,
                response="",
                error="Agent is already running",
            )

        self._status = AgentStatus.RUNNING

        # Check if swarm mode is enabled (needs minimal context setup first)
        if getattr(self._config, 'swarm_enabled', False):
            # Swarm path: the swarm runner only needs _ctx set with event
            # handlers + integrations. We set up a minimal context here.
            ctx = AgentContext(
                provider=self._provider,
                registry=self._registry,
                config=self._config,
                budget=self._budget,
                working_dir=self._working_dir,
                system_prompt=self._system_prompt,
                policy_engine=self._policy_engine,
                approval_callback=self._approval_callback,
                economics=self._economics,
                compaction_manager=self._compaction_manager,
                recitation_manager=self._recitation_manager,
                failure_tracker=self._failure_tracker,
                learning_store=self._learning_store,
                auto_checkpoint=self._auto_checkpoint,
                mcp_server_configs=self._mcp_server_configs or [],
                goal=prompt[:500],
            )
            if self._extension_handler:
                ctx.extension_handler = self._extension_handler  # type: ignore[attr-defined]
            for handler in self._event_handlers:
                ctx.on_event(handler)
            self._ctx = ctx
            return await self._run_with_swarm(prompt)

        # Build context, wire integrations, load skills, connect MCP, build messages
        from attocode.agent.run_context_builder import build_run_context
        ctx, mcp_clients = await build_run_context(self, prompt, images=images)

        try:
            # Lazy import to break circular dependency:
            # agent/__init__ → agent.agent → core.loop → agent.context → agent/__init__
            from attocode.core.loop import loop_result_to_agent_result, run_execution_loop

            # Run the execution loop
            loop_result = await run_execution_loop(ctx)

            # Convert to AgentResult
            result = loop_result_to_agent_result(loop_result, ctx)

            self._status = (
                AgentStatus.COMPLETED if result.success
                else AgentStatus.FAILED
            )

            # Accumulate cross-run stats
            self._run_count += 1
            self._total_tokens_all_runs += ctx.metrics.total_tokens
            self._total_cost_all_runs += ctx.metrics.estimated_cost

            # Persist conversation messages for next run
            self._conversation_messages = list(ctx.messages)

            # Update session
            if self._session_store and self._session_id:
                try:
                    await self._session_store.update_session(
                        self._session_id,
                        status="completed" if result.success else "failed",
                        total_tokens=ctx.metrics.total_tokens,
                        total_cost=ctx.metrics.estimated_cost,
                        iterations=ctx.iteration,
                    )
                except Exception:
                    logger.debug("session_update_failed", exc_info=True)

            return result

        except Exception as e:
            logger.error("agent_run_failed", exc_info=True)
            self._status = AgentStatus.FAILED
            return AgentResult(
                success=False,
                response="",
                error=str(e),
                metrics=ctx.metrics,
            )
        finally:
            # Safety: reset status if still RUNNING (unhandled exception path)
            if self._status == AgentStatus.RUNNING:
                self._status = AgentStatus.FAILED

            # Stop recording and export gallery
            if self._recorder is not None and self._recorder.is_recording:
                try:
                    self._recorder.stop()
                    self._recorder.export("html")
                except Exception:
                    logger.debug("recorder_export_failed", exc_info=True)

            # Disconnect MCP servers
            for client in mcp_clients:
                try:
                    await client.disconnect()
                except Exception:
                    logger.debug("mcp_disconnect_failed", exc_info=True)
            # NOTE: Do NOT close provider or null _ctx here.
            # The provider must stay alive for TUI session reuse.
            # _ctx is kept so slash commands (/diff, /status, /budget, etc.)
            # can read agent state between prompts.

    async def _connect_mcp_servers(self) -> list[Any]:
        """Connect to MCP servers and register their tools."""
        from attocode.agent.mcp_connector import connect_mcp_servers
        return await connect_mcp_servers(self)

    def cancel(self) -> None:
        """Cancel the current agent execution."""
        if self._ctx:
            self._ctx.cancel()
            self._status = AgentStatus.CANCELLED
        if self._cancellation_manager:
            try:
                self._cancellation_manager.cancel()
            except Exception:
                logger.debug("cancellation_failed", exc_info=True)

    async def close(self) -> None:
        """Close persistent resources (session store, etc.)."""
        if self._session_store:
            try:
                await self._session_store.close()
            except Exception:
                logger.debug("session_store_close_failed", exc_info=True)
            self._session_store = None

    def reset_conversation(self) -> None:
        """Reset conversation history for a fresh start (/clear)."""
        self._conversation_messages = []

    def pop_image_warning(self) -> str | None:
        """Return and clear the last image warning, if any."""
        warning = self._last_image_warning
        self._last_image_warning = None
        return warning

    def get_budget_usage(self) -> float:
        """Get the current budget usage as a fraction (0.0 to 1.0).

        Prefers economics manager if available (more accurate with
        baseline accounting), otherwise falls back to raw token ratio.
        """
        econ = self.get_economics()
        if econ:
            return econ.usage_fraction
        if not self._ctx:
            return 0.0
        if self._budget.max_tokens <= 0:
            return 0.0
        return min(self._ctx.metrics.total_tokens / self._budget.max_tokens, 1.0)

    def get_budget_details(self) -> dict[str, Any]:
        """Get detailed budget information."""
        econ = self.get_economics()
        if econ:
            return {
                "usage_fraction": econ.usage_fraction,
                "total_tokens": econ.total_tokens,
                "incremental_tokens": econ.incremental_tokens,
                "estimated_cost": econ.estimated_cost,
                "llm_calls": econ.llm_calls,
                "elapsed_seconds": econ.elapsed_seconds,
                "max_tokens": self._budget.max_tokens,
                "max_iterations": self._budget.max_iterations,
                "enforcement_mode": str(self._budget.enforcement_mode),
            }
        return {
            "usage_fraction": self.get_budget_usage(),
            "total_tokens": self._ctx.metrics.total_tokens if self._ctx else 0,
            "max_tokens": self._budget.max_tokens,
        }

    def get_cumulative_stats(self) -> dict[str, Any]:
        """Get stats across all runs in this session."""
        return {
            "run_count": self._run_count,
            "total_tokens": self._total_tokens_all_runs,
            "total_cost": self._total_cost_all_runs,
        }

    async def request_budget_extension(
        self,
        additional_tokens: int = 100_000,
        reason: str = "",
    ) -> bool:
        """Request a budget extension via the extension handler.

        Returns True if the extension was granted.
        """
        if not self._extension_handler:
            return False
        try:
            if self._ctx:
                self._ctx.emit_simple(
                    EventType.BUDGET_EXTENSION_REQUESTED,
                    metadata={
                        "requested_additional": additional_tokens,
                        "reason": reason,
                        "current_tokens": self._ctx.metrics.total_tokens,
                        "max_tokens": self._budget.max_tokens,
                    },
                )
            result = self._extension_handler({
                "current_tokens": self._ctx.metrics.total_tokens if self._ctx else 0,
                "max_tokens": self._budget.max_tokens,
                "requested_additional": additional_tokens,
                "reason": reason,
                "usage_fraction": self.get_budget_usage(),
            })
            if hasattr(result, "__await__"):
                granted = await result
            else:
                granted = result
            if granted:
                new_max = self.apply_budget_extension(additional_tokens)
                if self._ctx:
                    self._ctx.emit_simple(
                        EventType.BUDGET_EXTENSION_GRANTED,
                        metadata={
                            "requested_additional": additional_tokens,
                            "new_max_tokens": new_max,
                            "usage_fraction": self.get_budget_usage(),
                        },
                    )
            elif self._ctx:
                self._ctx.emit_simple(
                    EventType.BUDGET_EXTENSION_DENIED,
                    metadata={
                        "requested_additional": additional_tokens,
                        "usage_fraction": self.get_budget_usage(),
                    },
                )
            return bool(granted)
        except Exception:
            logger.warning("budget_extension_failed", exc_info=True)
            return False

    # --- Swarm / multi-agent execution ---

    async def _run_with_swarm(self, prompt: str) -> AgentResult:
        """Delegate execution to the swarm orchestrator for parallel multi-agent work."""
        from attocode.agent.swarm_runner import run_with_swarm
        return await run_with_swarm(self, prompt)

    def _build_worker_specs(self, orchestrator_model: str) -> list:
        """Build SwarmWorkerSpec list from agent config or defaults."""
        from attocode.agent.swarm_runner import build_worker_specs
        return build_worker_specs(self, orchestrator_model)

    async def spawn_agent(
        self,
        agent_name: str,
        task: str,
        *,
        model: str | None = None,
        budget_fraction: float = 0.2,
        timeout_seconds: float = 120.0,
    ) -> dict[str, Any]:
        """Spawn a subagent with its own budget to handle a delegated task."""
        from attocode.agent.subagent_api import spawn_agent
        return await spawn_agent(
            self, agent_name, task,
            model=model, budget_fraction=budget_fraction,
            timeout_seconds=timeout_seconds,
        )

    async def spawn_agents_parallel(
        self,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Spawn multiple subagents concurrently via asyncio.gather."""
        from attocode.agent.subagent_api import spawn_agents_parallel
        return await spawn_agents_parallel(self, tasks)

    async def suggest_agent_for_task(self, task: str) -> dict[str, Any]:
        """Suggest the best agent for a task using registry or keyword heuristics."""
        from attocode.agent.subagent_api import suggest_agent_for_task
        return await suggest_agent_for_task(self, task)

    # --- Checkpoint management ---

    async def create_checkpoint(self, label: str = "") -> dict[str, Any]:
        """Create a checkpoint of the current conversation state for later restore."""
        from attocode.agent.checkpoint_api import create_checkpoint
        return await create_checkpoint(self, label)

    async def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """Restore conversation state from a previously created checkpoint."""
        from attocode.agent.checkpoint_api import restore_checkpoint
        return await restore_checkpoint(self, checkpoint_id)

    # --- File change tracking and undo ---

    def track_file_change(
        self,
        path: str,
        action: str,
        content_before: str = "",
        content_after: str = "",
    ) -> None:
        """Record a file change for /diff review and /undo capability."""
        from attocode.agent.checkpoint_api import track_file_change
        track_file_change(self, path, action, content_before, content_after)

    def undo_last_change(self) -> dict[str, Any] | None:
        """Undo the most recent file change, restoring previous content."""
        from attocode.agent.checkpoint_api import undo_last_change
        return undo_last_change(self)

    # --- Codebase analysis ---

    async def analyze_codebase(self, root: str = "") -> None:
        """Trigger codebase context analysis from root (or working dir)."""
        target = root or self._working_dir
        if self._codebase_context:
            try:
                if target != self._codebase_context.root_dir:
                    self._codebase_context.root_dir = target
                    self._codebase_context._files = []
                    self._codebase_context._repo_map = None
                    self._codebase_context._dep_graph = None
                self._codebase_context.discover_files()
            except Exception:
                logger.debug("codebase_analysis_failed", exc_info=True)

    # --- Task complexity classification ---

    def classify_complexity(self, task: str) -> dict[str, Any]:
        """Classify task complexity as simple/moderate/complex/deep_research.

        Returns dict with: level, confidence (float), suggested_strategy.
        """
        task_lower = task.lower()
        task_len = len(task)
        word_count = len(task.split())

        # Heuristic signals
        question_marks = task.count("?")
        code_refs = sum(
            1 for marker in ["```", "`", "def ", "class ", "function ", "import "]
            if marker in task
        )
        complexity_keywords = [
            "refactor", "architect", "redesign", "migrate", "rewrite",
            "optimize", "scale", "integrate", "overhaul",
        ]
        research_keywords = [
            "investigate", "analyze", "compare", "evaluate", "research",
            "explore", "understand", "study", "audit",
        ]
        simple_keywords = [
            "fix typo", "rename", "add comment", "update version",
            "change color", "add import", "remove unused",
        ]

        complexity_hits = sum(1 for kw in complexity_keywords if kw in task_lower)
        research_hits = sum(1 for kw in research_keywords if kw in task_lower)
        simple_hits = sum(1 for kw in simple_keywords if kw in task_lower)

        # Scoring
        score = 0.0
        score += min(task_len / 500, 1.0) * 0.2  # Longer tasks tend to be more complex
        score += min(word_count / 50, 1.0) * 0.15
        score += min(question_marks / 3, 1.0) * 0.1
        score += min(code_refs / 3, 1.0) * 0.1
        score += min(complexity_hits / 2, 1.0) * 0.25
        score += min(research_hits / 2, 1.0) * 0.2

        # Simple keyword bonus reduces score
        if simple_hits > 0:
            score *= 0.5

        # Determine level
        if score < 0.2:
            level = "simple"
            strategy = "direct_edit"
            confidence = 1.0 - score * 2
        elif score < 0.45:
            level = "moderate"
            strategy = "plan_then_edit"
            confidence = 0.7 + (0.45 - score) * 0.5
        elif score < 0.7:
            level = "complex"
            strategy = "decompose_and_delegate"
            confidence = 0.6 + (score - 0.45) * 0.5
        else:
            level = "deep_research"
            strategy = "explore_then_plan"
            confidence = 0.5 + (score - 0.7) * 1.0

        confidence = round(max(0.3, min(confidence, 0.95)), 2)

        return {
            "level": level,
            "confidence": confidence,
            "suggested_strategy": strategy,
        }
