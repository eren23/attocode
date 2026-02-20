"""AgentBuilder - fluent API for constructing agents."""

from __future__ import annotations

from typing import Any

from attocode.agent.agent import ProductionAgent
from attocode.agent.context import EventHandler
from attocode.providers.base import LLMProvider
from attocode.providers.registry import create_provider
from attocode.tools.registry import ToolRegistry
from attocode.tools.standard import create_standard_registry
from attocode.types.agent import AgentConfig
from attocode.types.budget import ExecutionBudget, STANDARD_BUDGET


class AgentBuilder:
    """Fluent builder for constructing ProductionAgent instances.

    Usage:
        agent = (
            AgentBuilder()
            .with_provider("anthropic", api_key="sk-...")
            .with_model("claude-sonnet-4-20250514")
            .with_budget(max_tokens=500_000)
            .with_working_dir("/path/to/project")
            .build()
        )
    """

    def __init__(self) -> None:
        self._provider: LLMProvider | None = None
        self._registry: ToolRegistry | None = None
        self._config = AgentConfig()
        self._budget = STANDARD_BUDGET
        self._system_prompt: str | None = None
        self._working_dir: str = ""
        self._event_handlers: list[EventHandler] = []
        self._provider_name: str | None = None
        self._provider_kwargs: dict[str, Any] = {}
        self._policy_engine: Any = None
        self._approval_callback: Any = None
        self._sandbox_enabled: bool = False
        self._economics_enabled: bool = True
        self._compaction_enabled: bool = True
        self._session_dir: str | None = None
        self._enable_spawn_agent: bool = True
        self._mcp_server_configs: list[dict[str, Any]] = []
        self._learning_store: Any = None
        self._auto_checkpoint: Any = None
        self._recitation_manager: Any = None
        self._failure_tracker: Any = None

    def with_provider(
        self,
        name: str | None = None,
        *,
        provider: LLMProvider | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> AgentBuilder:
        """Set the LLM provider.

        Either pass a provider instance directly, or a name to auto-create.
        """
        if provider is not None:
            self._provider = provider
        else:
            self._provider_name = name
            if api_key:
                self._provider_kwargs["api_key"] = api_key
            self._provider_kwargs.update(kwargs)
        return self

    def with_model(self, model: str) -> AgentBuilder:
        """Set the LLM model."""
        self._config.model = model
        self._provider_kwargs["model"] = model
        return self

    def with_registry(self, registry: ToolRegistry) -> AgentBuilder:
        """Set a custom tool registry."""
        self._registry = registry
        return self

    def with_config(self, config: AgentConfig) -> AgentBuilder:
        """Set agent configuration."""
        self._config = config
        return self

    def with_budget(
        self,
        budget: ExecutionBudget | None = None,
        *,
        max_tokens: int | None = None,
        max_iterations: int | None = None,
        max_cost: float | None = None,
        max_duration: float | None = None,
    ) -> AgentBuilder:
        """Set execution budget."""
        if budget:
            self._budget = budget
        else:
            self._budget = ExecutionBudget(
                max_tokens=max_tokens or self._budget.max_tokens,
                max_iterations=max_iterations or self._budget.max_iterations,
                max_cost=max_cost or self._budget.max_cost,
                max_duration_seconds=max_duration or self._budget.max_duration_seconds,
            )
        return self

    def with_max_iterations(self, n: int) -> AgentBuilder:
        """Set maximum iterations."""
        self._config.max_iterations = n
        return self

    def with_system_prompt(self, prompt: str) -> AgentBuilder:
        """Set a custom system prompt."""
        self._system_prompt = prompt
        return self

    def with_working_dir(self, path: str) -> AgentBuilder:
        """Set the working directory."""
        self._working_dir = path
        return self

    def with_temperature(self, temp: float) -> AgentBuilder:
        """Set the LLM temperature."""
        self._config.temperature = temp
        return self

    def with_max_tokens(self, tokens: int) -> AgentBuilder:
        """Set the max response tokens."""
        self._config.max_tokens = tokens
        return self

    def on_event(self, handler: EventHandler) -> AgentBuilder:
        """Register an event handler."""
        self._event_handlers.append(handler)
        return self

    def with_debug(self, enabled: bool = True) -> AgentBuilder:
        """Enable/disable debug mode."""
        self._config.debug = enabled
        return self

    def with_policy_engine(self, engine: Any) -> AgentBuilder:
        """Set a custom policy engine."""
        self._policy_engine = engine
        return self

    def with_approval_callback(self, callback: Any) -> AgentBuilder:
        """Set the approval callback for interactive permission prompts."""
        self._approval_callback = callback
        return self

    def with_sandbox(self, enabled: bool = True) -> AgentBuilder:
        """Enable basic sandbox for bash commands."""
        self._sandbox_enabled = enabled
        return self

    def with_economics(self, enabled: bool = True) -> AgentBuilder:
        """Enable/disable economics tracking."""
        self._economics_enabled = enabled
        return self

    def with_compaction(self, enabled: bool = True) -> AgentBuilder:
        """Enable/disable auto-compaction."""
        self._compaction_enabled = enabled
        return self

    def with_session_dir(self, path: str) -> AgentBuilder:
        """Set the session storage directory."""
        self._session_dir = path
        return self

    def with_spawn_agent(self, enabled: bool = True) -> AgentBuilder:
        """Enable the spawn_agent tool for subagent delegation."""
        self._enable_spawn_agent = enabled
        return self

    def with_mcp_servers(self, configs: list[dict[str, Any]]) -> AgentBuilder:
        """Set MCP server configurations.

        Each config dict should have: command, args (optional), name (optional), env (optional).
        """
        self._mcp_server_configs = configs
        return self

    def with_learning_store(self, store: Any) -> AgentBuilder:
        """Set a learning store for persisting agent learnings."""
        self._learning_store = store
        return self

    def with_auto_checkpoint(self, manager: Any) -> AgentBuilder:
        """Set an auto-checkpoint manager."""
        self._auto_checkpoint = manager
        return self

    def with_tricks(
        self,
        recitation: Any = None,
        failure_tracker: Any = None,
    ) -> AgentBuilder:
        """Enable context engineering tricks (recitation, failure tracking)."""
        self._recitation_manager = recitation
        self._failure_tracker = failure_tracker
        return self

    def build(self) -> ProductionAgent:
        """Build and return the configured agent."""
        # Resolve provider
        provider = self._provider
        if provider is None:
            provider = create_provider(
                self._provider_name,
                **self._provider_kwargs,
            )

        # Resolve sandbox
        sandbox = None
        if self._sandbox_enabled:
            from attocode.integrations.safety.sandbox.basic import BasicSandbox
            sandbox = BasicSandbox()

        # Resolve registry — pass sandbox + spawn_agent credentials
        registry = self._registry
        if registry is None:
            registry = create_standard_registry(
                self._working_dir or None,
                sandbox=sandbox,
                enable_spawn_agent=self._enable_spawn_agent,
                provider_name=self._provider_name,
                api_key=self._provider_kwargs.get("api_key"),
                model=self._provider_kwargs.get("model"),
            )

        # Resolve policy engine
        policy_engine = self._policy_engine
        if policy_engine is None and self._sandbox_enabled:
            from attocode.integrations.safety.policy_engine import PolicyEngine
            policy_engine = PolicyEngine()

        # Resolve economics
        economics = None
        if self._economics_enabled:
            from attocode.integrations.budget.economics import ExecutionEconomicsManager
            economics = ExecutionEconomicsManager(
                budget=self._budget,
                enforcement_mode=self._budget.enforcement_mode,
            )

        # Resolve compaction manager
        compaction_manager = None
        if self._compaction_enabled:
            from attocode.integrations.context.auto_compaction import AutoCompactionManager
            max_ctx = 200_000  # default
            compaction_manager = AutoCompactionManager(max_context_tokens=max_ctx)

        # Build agent
        agent = ProductionAgent(
            provider=provider,
            registry=registry,
            config=self._config,
            budget=self._budget,
            system_prompt=self._system_prompt,
            working_dir=self._working_dir,
            policy_engine=policy_engine,
            approval_callback=self._approval_callback,
            economics=economics,
            compaction_manager=compaction_manager,
            session_dir=self._session_dir,
            mcp_server_configs=self._mcp_server_configs,
            learning_store=self._learning_store,
            auto_checkpoint=self._auto_checkpoint,
            recitation_manager=self._recitation_manager,
            failure_tracker=self._failure_tracker,
        )

        # Register event handlers
        for handler in self._event_handlers:
            agent.on_event(handler)

        return agent
