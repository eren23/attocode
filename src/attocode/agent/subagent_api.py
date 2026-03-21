"""Subagent spawning and task delegation.

Extracted from agent.py.  Provides standalone async functions for
spawning subagents and suggesting the best agent for a given task.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.agent.agent import ProductionAgent
    from attocode.types.agent import AgentResult
    from attocode.types.budget import ExecutionBudget

logger = logging.getLogger(__name__)


async def spawn_agent(
    agent: ProductionAgent,
    agent_name: str,
    task: str,
    *,
    model: str | None = None,
    budget_fraction: float = 0.2,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Spawn a subagent with its own budget to handle a delegated task."""
    try:
        from attocode.agent.builder import AgentBuilder
        from attocode.core.subagent_spawner import SubagentSpawner

        async def _run_subagent(sub_budget: ExecutionBudget, _subagent_id: str) -> AgentResult:
            builder = (
                AgentBuilder()
                .with_provider(provider=agent._provider)
                .with_model(model or agent._config.model or "")
                .with_working_dir(agent._working_dir)
                .with_project_root(agent._project_root)
                .with_rules(list(agent._config.rules))
                .with_budget(sub_budget)
                .with_compaction(False)
                .with_spawn_agent(False)
            )
            subagent = builder.build()
            try:
                return await subagent.run(task)
            finally:
                await subagent.close()

        parent_used = 0
        if agent._ctx is not None:
            parent_used = agent._ctx.metrics.total_tokens

        spawner = SubagentSpawner(
            parent_budget=agent._budget,
            parent_tokens_used=parent_used,
            hard_timeout_seconds=timeout_seconds,
        )
        spawn_result = await spawner.spawn(
            _run_subagent,
            task_description=task,
            budget_fraction=budget_fraction,
            timeout=timeout_seconds,
        )

        result: dict[str, Any] = {
            "success": spawn_result.success,
            "response": spawn_result.response,
            "tokens_used": spawn_result.tokens_used,
            "agent_name": agent_name,
        }
        if spawn_result.error:
            result["error"] = spawn_result.error

        # Track in registry
        agent._subagent_registry[agent_name] = {
            **result,
            "task": task,
            "timestamp": time.time(),
        }

        return result

    except Exception as e:
        logger.warning("subagent_spawn_failed", exc_info=True)
        err = "Subagent module not available" if isinstance(e, ImportError) else str(e)
        return {"success": False, "response": "", "tokens_used": 0,
                "agent_name": agent_name, "error": err}


async def spawn_agents_parallel(
    agent: ProductionAgent,
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
            spawn_agent(
                agent,
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


async def suggest_agent_for_task(
    agent: ProductionAgent,
    task: str,
) -> dict[str, Any]:
    """Suggest the best agent for a task using registry or keyword heuristics.

    Returns dict with: suggestions (list), should_delegate (bool),
    delegate_agent (str | None).
    """
    suggestions: list[dict[str, Any]] = []
    should_delegate = False
    delegate_agent: str | None = None

    # Try multi-agent manager first
    if agent._multi_agent_manager:
        try:
            agents = agent._multi_agent_manager.list_agents()
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
            if agent._provider and suggestions:
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
                    llm_response = await agent._provider.chat(
                        llm_messages, model=agent._config.model,
                    )
                    chosen = (llm_response.content or "").strip().lower()

                    agent_names_lower = {s["agent"].lower(): s["agent"] for s in suggestions}
                    if chosen in agent_names_lower:
                        delegate_agent = agent_names_lower[chosen]
                        should_delegate = True
                    elif chosen == "none":
                        should_delegate = False
                        delegate_agent = None
                except Exception:
                    logger.debug("llm_classification_failed", exc_info=True)
        except Exception:
            logger.debug("agent_suggestion_failed", exc_info=True)

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
        for a_name, keywords in keyword_agents.items():
            matches = sum(1 for kw in keywords if kw in task_lower)
            if matches > 0:
                score = matches / len(keywords)
                suggestions.append({"agent": a_name, "score": round(score, 3)})

        suggestions.sort(key=lambda s: s["score"], reverse=True)
        if suggestions and suggestions[0]["score"] > 0.2:
            should_delegate = True
            delegate_agent = suggestions[0]["agent"]

    return {
        "suggestions": suggestions[:5],
        "should_delegate": should_delegate,
        "delegate_agent": delegate_agent,
    }
