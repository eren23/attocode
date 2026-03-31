"""Core execution engine."""

from attocode.core.agent_state_machine import (
    AgentLifecycleState,
    AgentStateMachine,
    InvalidTransitionError,
)
from attocode.core.completion import CompletionAnalysis, analyze_completion
from attocode.core.autonomous import AutonomousPipeline, PipelineConfig, PipelinePhase
from attocode.core.dual_model import DualModelConfig, DualModelWorkflow
from attocode.core.loop import (
    BudgetPreflightResult,
    CompactionResult,
    DefaultLoopDeps,
    LoopDeps,
    LoopResult,
    apply_context_overflow_guard,
    check_iteration_budget,
    handle_auto_compaction,
    handle_fresh_context_refresh,
    loop_result_to_agent_result,
    run_execution_loop,
)
from attocode.core.orchestrator import Orchestrator, OrchestratorPlan, Subtask
from attocode.core.parallel_agents import ParallelAgentManager, ParallelConfig
from attocode.core.response_handler import call_llm
from attocode.core.subagent_spawner import (
    ClosureReport,
    SpawnResult,
    SubagentBudget,
    SubagentSpawner,
    get_subagent_budget,
    parse_closure_report,
)
from attocode.core.tool_executor import (
    ToolExecutionStats,
    build_tool_result_messages,
    execute_single_tool,
    execute_tool_calls,
    execute_tool_calls_batched,
)

__all__ = [
    # State machine
    "AgentLifecycleState",
    "AgentStateMachine",
    "InvalidTransitionError",
    # Completion
    "CompletionAnalysis",
    "analyze_completion",
    # Autonomous pipeline
    "AutonomousPipeline",
    "PipelineConfig",
    "PipelinePhase",
    # Dual model
    "DualModelConfig",
    "DualModelWorkflow",
    # Loop
    "BudgetPreflightResult",
    "CompactionResult",
    "DefaultLoopDeps",
    "LoopDeps",
    "LoopResult",
    "apply_context_overflow_guard",
    "check_iteration_budget",
    "handle_auto_compaction",
    "handle_fresh_context_refresh",
    "loop_result_to_agent_result",
    "run_execution_loop",
    # Orchestrator
    "Orchestrator",
    "OrchestratorPlan",
    "Subtask",
    # Parallel agents
    "ParallelAgentManager",
    "ParallelConfig",
    # Response
    "call_llm",
    # Subagent
    "ClosureReport",
    "SpawnResult",
    "SubagentBudget",
    "SubagentSpawner",
    "get_subagent_budget",
    "parse_closure_report",
    # Tool executor
    "ToolExecutionStats",
    "build_tool_result_messages",
    "execute_single_tool",
    "execute_tool_calls",
    "execute_tool_calls_batched",
]
