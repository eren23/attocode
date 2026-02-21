"""ProductionAgent - the main orchestrator for agent execution."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

from attocode.agent.context import AgentContext, EventHandler
from attocode.agent.message_builder import build_initial_messages
from attocode.providers.base import LLMProvider
from attocode.tools.registry import ToolRegistry
from attocode.types.agent import AgentConfig, AgentMetrics, AgentResult, AgentStatus
from attocode.types.budget import ExecutionBudget, STANDARD_BUDGET
from attocode.types.events import AgentEvent, EventType

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
        self._file_change_tracker: Any = None  # Persists across runs for /diff, /undo
        self._extension_handler: BudgetExtensionHandler | None = None
        self._run_count: int = 0
        self._total_tokens_all_runs: int = 0
        self._total_cost_all_runs: float = 0.0
        self._subagent_registry: dict[str, Any] = {}
        self._swarm_orchestrator: Any = None
        self._thread_manager: Any = None

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

    def get_context_usage(self) -> float:
        """Get context window usage as a fraction (0.0 to 1.0)."""
        if not self._ctx:
            return 0.0
        total_chars = sum(
            len(getattr(m, "content", "") or "")
            for m in self._ctx.messages
        )
        estimated_tokens = total_chars // 4
        max_context = 200_000  # Default context window
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

    async def run(self, prompt: str) -> AgentResult:
        """Run the agent with the given prompt.

        This is the main entry point for agent execution.
        Builds context, initializes messages, and runs the execution loop.
        """
        if self._status == AgentStatus.RUNNING:
            return AgentResult(
                success=False,
                response="",
                error="Agent is already running",
            )

        self._status = AgentStatus.RUNNING

        # Build context
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
            goal=prompt[:500],  # Store goal for recitation
        )

        # Wire extension handler into context
        if self._extension_handler:
            ctx.extension_handler = self._extension_handler  # type: ignore[attr-defined]

        # Wire additional integrations
        if self._safety_manager:
            ctx.safety_manager = self._safety_manager  # type: ignore[attr-defined]
        if self._task_manager:
            ctx.task_manager = self._task_manager  # type: ignore[attr-defined]
        if self._interactive_planner:
            ctx.interactive_planner = self._interactive_planner  # type: ignore[attr-defined]
        if self._codebase_context:
            ctx.codebase_context = self._codebase_context  # type: ignore[attr-defined]
        if self._multi_agent_manager:
            ctx.multi_agent_manager = self._multi_agent_manager  # type: ignore[attr-defined]
        if self._cancellation_manager:
            ctx.cancellation_manager = self._cancellation_manager  # type: ignore[attr-defined]

        # Register event handlers
        for handler in self._event_handlers:
            ctx.on_event(handler)

        self._ctx = ctx

        # Check if swarm mode is enabled
        if getattr(self._config, 'swarm_enabled', False):
            return await self._run_with_swarm(prompt)

        # Initialize session persistence
        session_id = None
        session_store = None
        if self._session_dir:
            try:
                from attocode.integrations.persistence.store import SessionStore
                from pathlib import Path
                db_path = Path(self._session_dir) / "sessions.db"
                session_store = SessionStore(db_path)
                await session_store.initialize()
                session_id = str(uuid.uuid4())[:8]
                await session_store.create_session(
                    session_id,
                    prompt[:200],
                    model=self._config.model or "",
                )
                ctx.session_store = session_store
                ctx.session_id = session_id
            except Exception:
                session_store = None  # Non-fatal

        # Reuse file change tracker across runs so /diff and /undo show cumulative history
        if self._file_change_tracker is None:
            try:
                from attocode.integrations.utilities.undo import FileChangeTracker
                self._file_change_tracker = FileChangeTracker()
            except Exception:
                pass
        if self._file_change_tracker is not None:
            ctx.file_change_tracker = self._file_change_tracker

        # Initialize optional features (file tracking, mode manager, etc.)
        try:
            from attocode.agent.feature_initializer import initialize_features
            await initialize_features(ctx, working_dir=self._working_dir)
        except Exception:
            pass  # Non-fatal — features degrade gracefully

        # Load skills
        loaded_skills = None
        if self._working_dir:
            try:
                from attocode.integrations.skills.loader import SkillLoader
                loader = SkillLoader(self._working_dir)
                loader.load()
                all_skills = loader.list_skills()
                if all_skills:
                    loaded_skills = all_skills
            except Exception:
                pass  # Skills are optional

        # Connect MCP servers and register their tools
        mcp_clients: list[Any] = []
        if self._mcp_server_configs:
            mcp_clients = await self._connect_mcp_servers()

        # Inject learnings into context if available
        learning_context = ""
        if self._learning_store:
            try:
                learning_context = self._learning_store.get_learning_context(
                    query=prompt[:200],
                    max_learnings=5,
                )
            except Exception:
                pass

        # Build initial messages
        messages = build_initial_messages(
            prompt,
            system_prompt=self._system_prompt,
            working_dir=self._working_dir,
            skills=loaded_skills,
            learning_context=learning_context,
        )
        ctx.add_messages(messages)

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

            # Update session
            if session_store and session_id:
                try:
                    await session_store.update_session(
                        session_id,
                        status="completed" if result.success else "failed",
                        total_tokens=ctx.metrics.total_tokens,
                        total_cost=ctx.metrics.estimated_cost,
                        iterations=ctx.iteration,
                    )
                except Exception:
                    pass

            return result

        except Exception as e:
            self._status = AgentStatus.FAILED
            return AgentResult(
                success=False,
                response="",
                error=str(e),
                metrics=ctx.metrics,
            )
        finally:
            # Disconnect MCP servers
            for client in mcp_clients:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            if session_store:
                try:
                    await session_store.close()
                except Exception:
                    pass
            # NOTE: Do NOT close provider or null _ctx here.
            # The provider must stay alive for TUI session reuse.
            # _ctx is kept so slash commands (/diff, /status, /budget, etc.)
            # can read agent state between prompts.

    async def _connect_mcp_servers(self) -> list[Any]:
        """Connect to MCP servers and register their tools."""
        from attocode.integrations.mcp.client import MCPClient
        from attocode.tools.base import Tool, ToolSpec
        from attocode.types.messages import DangerLevel

        clients: list[Any] = []
        for mcp_cfg in self._mcp_server_configs:
            try:
                client = MCPClient(
                    server_command=mcp_cfg["command"],
                    server_args=mcp_cfg.get("args", []),
                    server_name=mcp_cfg.get("name", ""),
                    env=mcp_cfg.get("env"),
                )
                await client.connect()
                clients.append(client)
                # Register discovered tools in the registry
                for mcp_tool in client.tools:
                    def _make_executor(c: MCPClient, name: str):
                        async def _exec(args: dict) -> Any:
                            r = await c.call_tool(name, args)
                            return r.result if r.success else f"Error: {r.error}"
                        return _exec
                    tool_name = (
                        f"mcp__{client.server_name}__{mcp_tool.name}"
                        if client.server_name else mcp_tool.name
                    )
                    self._registry.register(Tool(
                        spec=ToolSpec(
                            name=tool_name,
                            description=mcp_tool.description,
                            parameters=mcp_tool.input_schema,
                            danger_level=DangerLevel.MODERATE,
                        ),
                        execute=_make_executor(client, mcp_tool.name),
                        tags=["mcp", client.server_name],
                    ))
            except Exception:
                pass  # MCP connection failures are non-fatal
        return clients

    def cancel(self) -> None:
        """Cancel the current agent execution."""
        if self._ctx:
            self._ctx.cancel()
            self._status = AgentStatus.CANCELLED
        if self._cancellation_manager:
            try:
                self._cancellation_manager.cancel()
            except Exception:
                pass

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
                self._budget = ExecutionBudget(
                    max_tokens=self._budget.max_tokens + additional_tokens,
                    max_iterations=self._budget.max_iterations,
                    soft_ratio=self._budget.soft_ratio,
                    enforcement_mode=self._budget.enforcement_mode,
                )
                if self._ctx and self._ctx.economics:
                    self._ctx.economics.budget = self._budget
            return bool(granted)
        except Exception:
            return False

    # --- Swarm / multi-agent execution ---

    async def _run_with_swarm(self, prompt: str) -> AgentResult:
        """Delegate execution to the swarm orchestrator for parallel multi-agent work."""
        try:
            from attocode.integrations.swarm.orchestrator import (
                SwarmConfig,
                SwarmOrchestrator,
            )
            from attocode.integrations.swarm.types import SwarmExecutionResult

            # Build swarm configuration from agent config
            swarm_cfg = SwarmConfig(
                max_workers=getattr(self._config, "swarm_max_workers", 3),
                max_concurrency=getattr(self._config, "swarm_max_concurrency", 2),
                quality_gates=getattr(self._config, "swarm_quality_gates", True),
                orchestrator_model=self._config.model or "",
                worker_models=getattr(self._config, "swarm_worker_models", []),
                budget=self._budget,
            )

            # Create or reuse orchestrator
            if self._swarm_orchestrator is None:
                self._swarm_orchestrator = SwarmOrchestrator(
                    config=swarm_cfg,
                    provider=self._provider,
                    registry=self._registry,
                    working_dir=self._working_dir,
                )

            # Execute the swarm
            swarm_result: SwarmExecutionResult = await self._swarm_orchestrator.execute(
                prompt
            )

            # Convert SwarmExecutionResult to AgentResult
            return AgentResult(
                success=swarm_result.success,
                response=swarm_result.final_output or "",
                error=swarm_result.error if not swarm_result.success else None,
                metrics=AgentMetrics(
                    total_tokens=swarm_result.total_tokens,
                    estimated_cost=swarm_result.total_cost,
                    llm_calls=swarm_result.total_llm_calls,
                    tool_calls=swarm_result.total_tool_calls,
                    duration_seconds=swarm_result.duration_seconds,
                ),
            )

        except ImportError:
            return AgentResult(
                success=False,
                response="",
                error="Swarm module not available. Install swarm dependencies.",
            )
        except Exception as e:
            return AgentResult(
                success=False,
                response="",
                error=f"Swarm execution failed: {e}",
            )

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
        try:
            from attocode.integrations.agents.async_subagent import AsyncSubagentSpawner

            # Calculate budget allocation
            allocated_tokens = int(self._budget.max_tokens * budget_fraction)
            allocated_iterations = max(
                5, int(self._budget.max_iterations * budget_fraction)
            )
            subagent_budget = ExecutionBudget(
                max_tokens=allocated_tokens,
                max_iterations=allocated_iterations,
                enforcement_mode=self._budget.enforcement_mode,
            )

            spawner = AsyncSubagentSpawner(
                provider=self._provider,
                registry=self._registry,
                working_dir=self._working_dir,
                budget=subagent_budget,
                model=model or self._config.model or "",
                timeout_seconds=timeout_seconds,
            )

            spawn_result = await spawner.spawn(agent_name=agent_name, task=task)

            result: dict[str, Any] = {
                "success": spawn_result.get("success", False),
                "response": spawn_result.get("response", ""),
                "tokens_used": spawn_result.get("tokens_used", 0),
                "agent_name": agent_name,
            }

            # Track in registry
            self._subagent_registry[agent_name] = {
                **result,
                "task": task,
                "timestamp": time.time(),
            }

            return result

        except Exception as e:
            err = "Subagent module not available" if isinstance(e, ImportError) else str(e)
            return {"success": False, "response": "", "tokens_used": 0,
                    "agent_name": agent_name, "error": err}

    async def spawn_agents_parallel(
        self,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Spawn multiple subagents concurrently via asyncio.gather.

        Each task dict must have 'agent' and 'task' keys. Optional:
        'model', 'budget_fraction', 'timeout_seconds'.
        """
        if not tasks:
            return []

        # Calculate per-agent budget fraction so total does not exceed 80%
        default_fraction = min(0.8 / max(len(tasks), 1), 0.3)

        coros = []
        for task_spec in tasks:
            agent_name = task_spec.get("agent", f"agent-{uuid.uuid4().hex[:6]}")
            task_desc = task_spec.get("task", "")
            coros.append(
                self.spawn_agent(
                    agent_name=agent_name,
                    task=task_desc,
                    model=task_spec.get("model"),
                    budget_fraction=task_spec.get("budget_fraction", default_fraction),
                    timeout_seconds=task_spec.get("timeout_seconds", 120.0),
                )
            )

        results = await asyncio.gather(*coros, return_exceptions=True)

        # Convert exceptions to error dicts
        final: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                agent_name = tasks[i].get("agent", f"agent-{i}")
                final.append({
                    "success": False,
                    "response": "",
                    "tokens_used": 0,
                    "agent_name": agent_name,
                    "error": str(result),
                })
            else:
                final.append(result)  # type: ignore[arg-type]
        return final

    async def suggest_agent_for_task(self, task: str) -> dict[str, Any]:
        """Suggest the best agent for a task using registry or keyword heuristics.

        Returns dict with: suggestions (list), should_delegate (bool),
        delegate_agent (str | None).
        """
        suggestions: list[dict[str, Any]] = []
        should_delegate = False
        delegate_agent: str | None = None

        # Try multi-agent manager first
        if self._multi_agent_manager:
            try:
                agents = self._multi_agent_manager.list_agents()
                for agent_def in agents:
                    name = getattr(agent_def, "name", str(agent_def))
                    description = getattr(agent_def, "description", "")
                    # Simple keyword overlap scoring
                    task_words = set(task.lower().split())
                    desc_words = set(description.lower().split())
                    overlap = len(task_words & desc_words)
                    score = overlap / max(len(task_words), 1)
                    suggestions.append({"agent": name, "score": round(score, 3)})

                suggestions.sort(key=lambda s: s["score"], reverse=True)

                if suggestions and suggestions[0]["score"] > 0.15:
                    should_delegate = True
                    delegate_agent = suggestions[0]["agent"]

                # Attempt LLM-based classification for better accuracy
                if self._provider and suggestions:
                    try:
                        agent_list_str = ", ".join(
                            f"{s['agent']} (score={s['score']})" for s in suggestions[:5]
                        )
                        classification_prompt = (
                            f"Given the task: '{task[:300]}'\n"
                            f"Available agents: {agent_list_str}\n"
                            f"Which agent is the best fit? Reply with just the agent name, "
                            f"or 'none' if the task should be handled by the main agent."
                        )
                        from attocode.types.messages import Message

                        llm_messages = [Message(role="user", content=classification_prompt)]
                        llm_response = await self._provider.chat(llm_messages, model=self._config.model)
                        chosen = (llm_response.content or "").strip().lower()

                        agent_names_lower = {s["agent"].lower(): s["agent"] for s in suggestions}
                        if chosen in agent_names_lower:
                            delegate_agent = agent_names_lower[chosen]
                            should_delegate = True
                        elif chosen == "none":
                            should_delegate = False
                            delegate_agent = None
                    except Exception:
                        pass  # LLM classification is best-effort
            except Exception:
                pass

        # Fallback: keyword heuristic when no multi-agent manager
        if not suggestions:
            keyword_agents: dict[str, list[str]] = {
                "test-writer": ["test", "spec", "coverage", "assert", "unittest"],
                "refactorer": ["refactor", "clean", "extract", "rename", "simplify"],
                "documenter": ["document", "readme", "docstring", "jsdoc", "comment"],
                "debugger": ["debug", "fix", "error", "bug", "crash", "trace"],
                "reviewer": ["review", "audit", "check", "lint", "quality"],
            }
            task_lower = task.lower()
            for agent_name, keywords in keyword_agents.items():
                matches = sum(1 for kw in keywords if kw in task_lower)
                if matches > 0:
                    score = matches / len(keywords)
                    suggestions.append({"agent": agent_name, "score": round(score, 3)})

            suggestions.sort(key=lambda s: s["score"], reverse=True)
            if suggestions and suggestions[0]["score"] > 0.2:
                should_delegate = True
                delegate_agent = suggestions[0]["agent"]

        return {
            "suggestions": suggestions[:5],
            "should_delegate": should_delegate,
            "delegate_agent": delegate_agent,
        }

    # --- Checkpoint management ---

    async def create_checkpoint(self, label: str = "") -> dict[str, Any]:
        """Create a checkpoint of the current conversation state for later restore."""
        checkpoint_id = f"cp-{uuid.uuid4().hex[:8]}"
        timestamp = time.time()
        message_count = len(self._ctx.messages) if self._ctx else 0

        # Persist to session store if available
        if self._ctx and hasattr(self._ctx, "session_store") and self._ctx.session_store:
            try:
                session_id = getattr(self._ctx, "session_id", "")
                await self._ctx.session_store.create_checkpoint(
                    session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    label=label,
                    messages=self._ctx.messages,
                )
            except Exception:
                pass  # Checkpoint persistence is best-effort

        return {
            "checkpoint_id": checkpoint_id,
            "label": label or f"Checkpoint at iteration {self._ctx.iteration if self._ctx else 0}",
            "message_count": message_count,
            "timestamp": timestamp,
        }

    async def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """Restore conversation state from a previously created checkpoint."""
        if not self._ctx:
            return False

        if not hasattr(self._ctx, "session_store") or not self._ctx.session_store:
            return False

        try:
            session_id = getattr(self._ctx, "session_id", "")
            checkpoint_data = await self._ctx.session_store.load_checkpoint(
                session_id=session_id,
                checkpoint_id=checkpoint_id,
            )
            if checkpoint_data and "messages" in checkpoint_data:
                self._ctx.messages.clear()
                self._ctx.messages.extend(checkpoint_data["messages"])
                return True
        except Exception:
            pass

        return False

    # --- File change tracking and undo ---

    def track_file_change(
        self,
        path: str,
        action: str,
        content_before: str = "",
        content_after: str = "",
    ) -> None:
        """Record a file change for /diff review and /undo capability."""
        if self._file_change_tracker is not None:
            try:
                self._file_change_tracker.record(
                    path=path,
                    action=action,
                    content_before=content_before,
                    content_after=content_after,
                )
            except Exception:
                pass  # Tracking failure should not block execution

    def undo_last_change(self) -> dict[str, Any] | None:
        """Undo the most recent file change, restoring previous content."""
        if self._file_change_tracker is None:
            return None
        try:
            undo_result = self._file_change_tracker.undo()
            if undo_result is None:
                return None
            return {
                "path": undo_result.get("path", ""),
                "action": undo_result.get("action", ""),
                "success": undo_result.get("success", False),
            }
        except Exception:
            return None

    # --- Codebase analysis ---

    async def analyze_codebase(self, root: str = "") -> None:
        """Trigger codebase context analysis from root (or working dir)."""
        target = root or self._working_dir
        if self._codebase_context:
            try:
                await self._codebase_context.analyze(target)
            except Exception:
                pass  # Analysis failure is non-fatal

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
