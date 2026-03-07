"""Swarm orchestration execution.

Extracted from agent.py.  Contains the swarm-mode entry point
(_run_with_swarm) and worker spec builder (_build_worker_specs).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attocode.agent.agent import ProductionAgent

from attocode.types.agent import AgentMetrics, AgentResult

logger = logging.getLogger(__name__)


async def run_with_swarm(agent: ProductionAgent, prompt: str) -> AgentResult:
    """Delegate execution to the swarm orchestrator for parallel multi-agent work."""
    try:
        from attocode.integrations.swarm.cc_spawner import create_cc_spawn_fn
        from attocode.integrations.swarm.event_bridge import SwarmEventBridge
        from attocode.integrations.swarm.model_selector import get_fallback_workers  # noqa: F401
        from attocode.integrations.swarm.orchestrator import SwarmOrchestrator
        from attocode.integrations.swarm.types import (
            SwarmConfig,
            SwarmExecutionResult,
            SwarmWorkerSpec,  # noqa: F401
            WorkerCapability,  # noqa: F401
        )

        # Build swarm configuration from agent config
        orchestrator_model = agent._config.model or "claude-sonnet-4-20250514"

        # Build worker specs from config or defaults
        workers = build_worker_specs(agent, orchestrator_model)

        swarm_cfg = SwarmConfig(
            orchestrator_model=orchestrator_model,
            workers=workers,
            max_concurrency=getattr(agent._config, "swarm_max_concurrency", 2),
            quality_gates=getattr(agent._config, "swarm_quality_gates", True),
            total_budget=agent._budget.max_tokens * 10,  # workers get their own budgets
            max_cost=10.0,
            worker_max_iterations=agent._budget.max_iterations,
        )

        # Create spawn function using CC CLI subprocess
        spawn_fn = create_cc_spawn_fn(
            working_dir=agent._working_dir,
            default_model=orchestrator_model,
            max_iterations=swarm_cfg.worker_max_iterations,
        )

        # Create or reuse orchestrator
        if agent._swarm_orchestrator is None:
            agent._swarm_orchestrator = SwarmOrchestrator(
                config=swarm_cfg,
                provider=agent._provider,
                spawn_agent_fn=spawn_fn,
            )

        # Attach event bridge for TUI consumption -- create fresh each run
        # to avoid duplicate listeners from repeated swarm executions
        if agent._event_bridge is not None:
            agent._event_bridge.close()
            agent._event_bridge = None
        agent._event_bridge = SwarmEventBridge(
            output_dir=os.path.join(
                agent._session_dir or ".agent", "swarm-live"
            ),
        )
        agent._event_bridge.attach(agent._swarm_orchestrator)

        # Wire TUI callback if set
        if agent._tui_swarm_callback:
            agent._event_bridge.set_tui_callback(agent._tui_swarm_callback)

        # Start AST server for external CC instances
        if agent._ast_server is None and agent._working_dir:
            try:
                from attocode.integrations.context.ast_server import ASTServer
                from attocode.integrations.context.ast_service import ASTService
                from attocode.tools.ast_query import create_ast_query_tool

                ast_svc = ASTService.get_instance(agent._working_dir)
                if not ast_svc.initialized:
                    ast_svc.initialize()

                # Start socket server
                agent._ast_server = ASTServer(ast_svc)
                await agent._ast_server.start()

                # Register AST query tool for workers
                if not agent._registry.has("codebase_ast_query"):
                    agent._registry.register(create_ast_query_tool(ast_svc))
            except Exception:
                logger.debug("ast_server_init_failed", exc_info=True)

        # Execute the swarm
        swarm_result: SwarmExecutionResult = await agent._swarm_orchestrator.execute(
            prompt
        )

        # Stop AST server after swarm completes
        if agent._ast_server:
            try:
                await agent._ast_server.stop()
            except Exception:
                logger.debug("ast_server_stop_failed", exc_info=True)
            agent._ast_server = None

        # Close event bridge
        if agent._event_bridge:
            agent._event_bridge.close()

        # Convert SwarmExecutionResult to AgentResult
        stats = swarm_result.stats
        return AgentResult(
            success=swarm_result.success,
            response=swarm_result.summary or "",
            error=None if swarm_result.success else (
                swarm_result.errors[0].get("message", "Swarm failed")
                if swarm_result.errors else "Swarm execution failed"
            ),
            metrics=AgentMetrics(
                total_tokens=stats.total_tokens,
                estimated_cost=stats.total_cost,
                llm_calls=stats.orchestrator_tokens,
                tool_calls=stats.completed_tasks,
                duration_ms=float(stats.total_duration_ms),
            ),
        )

    except ImportError as ie:
        return AgentResult(
            success=False,
            response="",
            error=f"Swarm module not available: {ie}",
        )
    except Exception as e:
        logger.error("swarm_execution_failed", exc_info=True)
        return AgentResult(
            success=False,
            response="",
            error=f"Swarm execution failed: {e}",
        )


def build_worker_specs(agent: ProductionAgent, orchestrator_model: str) -> list:
    """Build SwarmWorkerSpec list from agent config or defaults."""
    from attocode.integrations.swarm.types import (
        SwarmWorkerSpec,
        WorkerCapability,
        WorkerRole,
    )

    # Check if config has explicit worker specs
    configured_workers = getattr(agent._config, "swarm_workers", None)
    if configured_workers:
        return configured_workers

    # Check for swarm worker models list (e.g., from CLI)
    worker_models = getattr(agent._config, "swarm_worker_models", None)
    if worker_models:
        specs = []
        for i, model in enumerate(worker_models):
            specs.append(SwarmWorkerSpec(
                name=f"worker-{i}",
                model=model,
                capabilities=[WorkerCapability.CODE, WorkerCapability.TEST],
            ))
        return specs

    # Default: use orchestrator model for 2 builder workers + 1 reviewer
    return [
        SwarmWorkerSpec(
            name="builder-0",
            model=orchestrator_model,
            capabilities=[WorkerCapability.CODE, WorkerCapability.TEST],
        ),
        SwarmWorkerSpec(
            name="builder-1",
            model=orchestrator_model,
            capabilities=[WorkerCapability.CODE, WorkerCapability.TEST],
        ),
        SwarmWorkerSpec(
            name="reviewer",
            model=orchestrator_model,
            capabilities=[WorkerCapability.REVIEW, WorkerCapability.RESEARCH],
            role=WorkerRole.EXECUTOR,
            allowed_tools=["Read", "Glob", "Grep"],
        ),
    ]
