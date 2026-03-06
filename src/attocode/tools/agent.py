"""Spawn agent tool — allows the LLM to delegate subtasks to subagents."""

from __future__ import annotations

from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


async def execute_spawn_agent(
    args: dict[str, Any],
    *,
    parent_working_dir: str | None = None,
    provider_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """Spawn a subagent to handle a subtask.

    Creates a fresh AgentBuilder, runs the subtask, and returns the result.
    """
    task = args.get("task", "")
    if not task:
        return "Error: 'task' argument is required"

    subagent_model = args.get("model") or model
    max_iterations = args.get("max_iterations", 30)

    try:
        from attocode.agent.builder import AgentBuilder
        from attocode.types.budget import SUBAGENT_BUDGET

        builder = AgentBuilder()

        if provider_name:
            builder = builder.with_provider(provider_name, api_key=api_key)
        if subagent_model:
            builder = builder.with_model(subagent_model)
        if parent_working_dir:
            builder = builder.with_working_dir(parent_working_dir)

        builder = (
            builder
            .with_budget(SUBAGENT_BUDGET)
            .with_max_iterations(max_iterations)
            .with_economics(True)
            .with_compaction(False)  # Subagents are short-lived
        )

        agent = builder.build()
        result = await agent.run(task)

        if result.success:
            return result.response or "(no output)"
        return f"Subagent failed: {result.error or 'unknown error'}"

    except Exception as e:
        return f"Error spawning subagent: {e}"


def create_spawn_agent_tool(
    working_dir: str | None = None,
    provider_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> Tool:
    """Create the spawn_agent tool."""

    async def _execute(args: dict[str, Any]) -> Any:
        return await execute_spawn_agent(
            args,
            parent_working_dir=working_dir,
            provider_name=provider_name,
            api_key=api_key,
            model=model,
        )

    return Tool(
        spec=ToolSpec(
            name="spawn_agent",
            description=(
                "Spawn a subagent to handle a subtask autonomously. "
                "The subagent gets its own tool set and budget. "
                "Use this to delegate independent work like research, "
                "code generation, or testing. The subagent's response "
                "is returned as the tool result."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task for the subagent to accomplish",
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional model override for the subagent",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum iterations for the subagent (default: 30)",
                        "default": 30,
                    },
                },
                "required": ["task"],
            },
            danger_level=DangerLevel.MODERATE,
        ),
        execute=_execute,
        tags=["agent", "delegation"],
    )
