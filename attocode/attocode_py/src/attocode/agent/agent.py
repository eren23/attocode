"""ProductionAgent - the main orchestrator for agent execution."""

from __future__ import annotations

import time
import uuid
from typing import Any

from attocode.agent.context import AgentContext, EventHandler
from attocode.agent.message_builder import build_initial_messages
from attocode.providers.base import LLMProvider
from attocode.tools.registry import ToolRegistry
from attocode.types.agent import AgentConfig, AgentMetrics, AgentResult, AgentStatus
from attocode.types.budget import ExecutionBudget, STANDARD_BUDGET
from attocode.types.events import AgentEvent, EventType


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
        self._file_change_tracker: Any = None  # Persists across runs for /diff, /undo

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
    def context(self) -> AgentContext | None:
        """The current execution context, if running."""
        return self._ctx

    def on_event(self, handler: EventHandler) -> None:
        """Register an event handler."""
        self._event_handlers.append(handler)

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

        # Register event handlers
        for handler in self._event_handlers:
            ctx.on_event(handler)

        self._ctx = ctx

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

    def get_budget_usage(self) -> float:
        """Get the current budget usage as a fraction (0.0 to 1.0)."""
        if not self._ctx:
            return 0.0
        if self._budget.max_tokens <= 0:
            return 0.0
        return min(self._ctx.metrics.total_tokens / self._budget.max_tokens, 1.0)
