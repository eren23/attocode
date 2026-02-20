"""Tests for ProductionAgent and AgentBuilder."""

from __future__ import annotations

from typing import Any

import pytest

from attocode.agent.agent import ProductionAgent
from attocode.agent.builder import AgentBuilder
from attocode.agent.message_builder import DEFAULT_SYSTEM_PROMPT, build_initial_messages, build_system_prompt
from attocode.providers.mock import MockProvider
from attocode.tools.base import Tool, ToolSpec
from attocode.tools.registry import ToolRegistry
from attocode.types.agent import AgentConfig, AgentStatus, CompletionReason
from attocode.types.budget import ExecutionBudget
from attocode.types.events import AgentEvent, EventType
from attocode.types.messages import (
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
)


# --- Message Builder Tests ---


class TestBuildSystemPrompt:
    def test_default(self) -> None:
        prompt = build_system_prompt()
        assert "AI coding assistant" in prompt

    def test_custom_base(self) -> None:
        prompt = build_system_prompt(base_prompt="Custom agent")
        assert "Custom agent" in prompt
        assert "AI coding assistant" not in prompt

    def test_with_working_dir(self) -> None:
        prompt = build_system_prompt(working_dir="/home/user/project")
        assert "/home/user/project" in prompt

    def test_with_rules(self) -> None:
        prompt = build_system_prompt(rules=["Be concise", "Use Python 3.12+"])
        assert "Be concise" in prompt
        assert "Rules" in prompt

    def test_with_extra_context(self) -> None:
        prompt = build_system_prompt(extra_context="Project uses Django.")
        assert "Django" in prompt


class TestBuildInitialMessages:
    def test_basic(self) -> None:
        msgs = build_initial_messages("Hello, agent!")
        assert len(msgs) == 2
        assert msgs[0].role == Role.SYSTEM
        assert msgs[1].role == Role.USER
        assert msgs[1].content == "Hello, agent!"

    def test_custom_system_prompt(self) -> None:
        msgs = build_initial_messages("Hi", system_prompt="Custom system")
        assert msgs[0].content == "Custom system"


# --- ProductionAgent Tests ---


class TestProductionAgent:
    @pytest.mark.asyncio
    async def test_simple_run(self) -> None:
        provider = MockProvider()
        provider.add_response(
            content="Task complete!",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        registry = ToolRegistry()
        agent = ProductionAgent(provider=provider, registry=registry)

        result = await agent.run("Do something")
        assert result.success
        assert result.response == "Task complete!"
        assert result.metrics.llm_calls == 1

    @pytest.mark.asyncio
    async def test_status_transitions(self) -> None:
        provider = MockProvider()
        provider.add_response(
            content="Done",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        agent = ProductionAgent(provider=provider, registry=ToolRegistry())

        assert agent.status == AgentStatus.IDLE
        result = await agent.run("test")
        assert agent.status == AgentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failed_status(self) -> None:
        provider = MockProvider()

        async def fail(msgs, opts):
            raise RuntimeError("boom")

        provider.response_fn = fail
        agent = ProductionAgent(provider=provider, registry=ToolRegistry())

        result = await agent.run("test")
        assert not result.success
        assert agent.status == AgentStatus.FAILED

    @pytest.mark.asyncio
    async def test_with_tool_calls(self) -> None:
        async def echo(args: dict[str, Any]) -> str:
            return f"echo: {args.get('text', '')}"

        reg = ToolRegistry()
        reg.register(Tool(
            spec=ToolSpec(name="echo", description="echo", parameters={}),
            execute=echo,
        ))

        provider = MockProvider()
        provider.add_response(
            content="Calling tool",
            tool_calls=[ToolCall(id="tc_1", name="echo", arguments={"text": "hi"})],
            stop_reason=StopReason.TOOL_USE,
            usage=TokenUsage(input_tokens=10, output_tokens=10, total_tokens=20),
        )
        provider.add_response(
            content="Echo result: hi",
            usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30),
        )

        agent = ProductionAgent(provider=provider, registry=reg)
        result = await agent.run("Echo something")

        assert result.success
        assert "hi" in result.response
        assert result.metrics.tool_calls == 1

    @pytest.mark.asyncio
    async def test_event_handlers(self) -> None:
        provider = MockProvider()
        provider.add_response(
            content="Done",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        agent = ProductionAgent(provider=provider, registry=ToolRegistry())

        events: list[AgentEvent] = []
        agent.on_event(events.append)

        await agent.run("test")
        types = [e.type for e in events]
        assert EventType.START in types
        assert EventType.LLM_COMPLETE in types

    @pytest.mark.asyncio
    async def test_cancel(self) -> None:
        provider = MockProvider()
        # Provider will sleep for a while
        async def slow_response(msgs, opts):
            import asyncio
            await asyncio.sleep(10)
            return None

        provider.response_fn = slow_response
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
        )

        # Start the agent in a task, cancel it quickly
        import asyncio
        task = asyncio.create_task(agent.run("test"))
        await asyncio.sleep(0.05)
        agent.cancel()
        result = await task

        assert not result.success

    @pytest.mark.asyncio
    async def test_budget_usage(self) -> None:
        provider = MockProvider()
        provider.add_response(
            content="Done",
            usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        )
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
            budget=ExecutionBudget(max_tokens=1000),
        )

        assert agent.get_budget_usage() == 0.0
        # Budget usage requires running context
        await agent.run("test")
        # After run, context is preserved for slash commands (/diff, /status, etc.)
        assert agent.get_budget_usage() == 0.15  # 150 / 1000

    @pytest.mark.asyncio
    async def test_double_run_rejected(self) -> None:
        provider = MockProvider()

        async def slow(msgs, opts):
            import asyncio
            await asyncio.sleep(1)
            return None

        provider.response_fn = slow
        agent = ProductionAgent(provider=provider, registry=ToolRegistry())

        import asyncio
        task1 = asyncio.create_task(agent.run("first"))
        await asyncio.sleep(0.05)

        # Second run should fail
        result2 = await agent.run("second")
        assert not result2.success
        assert "already running" in result2.error.lower()

        agent.cancel()
        await task1

    @pytest.mark.asyncio
    async def test_custom_system_prompt(self) -> None:
        provider = MockProvider()
        provider.add_response(
            content="Done",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
            system_prompt="You are a Python expert.",
        )

        await agent.run("test")
        # Check the messages sent to provider
        sent_msgs = provider.call_history[0][0]
        assert any("Python expert" in str(m.content) for m in sent_msgs)


# --- AgentBuilder Tests ---


class TestAgentBuilder:
    def test_build_with_mock(self) -> None:
        mock = MockProvider()
        agent = (
            AgentBuilder()
            .with_provider(provider=mock)
            .build()
        )
        assert agent.provider is mock

    def test_build_with_config(self) -> None:
        mock = MockProvider()
        config = AgentConfig(max_iterations=50, debug=True)
        agent = (
            AgentBuilder()
            .with_provider(provider=mock)
            .with_config(config)
            .build()
        )
        assert agent.config.max_iterations == 50
        assert agent.config.debug

    def test_build_with_budget(self) -> None:
        mock = MockProvider()
        agent = (
            AgentBuilder()
            .with_provider(provider=mock)
            .with_budget(max_tokens=500_000, max_iterations=50)
            .build()
        )
        # Agent should be created without errors
        assert agent is not None

    def test_build_with_registry(self) -> None:
        mock = MockProvider()
        reg = ToolRegistry()
        agent = (
            AgentBuilder()
            .with_provider(provider=mock)
            .with_registry(reg)
            .build()
        )
        assert agent.registry is reg

    def test_fluent_chain(self) -> None:
        mock = MockProvider()
        agent = (
            AgentBuilder()
            .with_provider(provider=mock)
            .with_model("gpt-4o")
            .with_max_iterations(50)
            .with_temperature(0.5)
            .with_max_tokens(4096)
            .with_system_prompt("Custom")
            .with_working_dir("/tmp/test")
            .with_debug()
            .build()
        )
        assert agent.config.model == "gpt-4o"
        assert agent.config.max_iterations == 50
        assert agent.config.temperature == 0.5
        assert agent.config.max_tokens == 4096
        assert agent.config.debug

    def test_event_handler(self) -> None:
        events: list[AgentEvent] = []
        mock = MockProvider()
        agent = (
            AgentBuilder()
            .with_provider(provider=mock)
            .on_event(events.append)
            .build()
        )
        assert agent is not None

    @pytest.mark.asyncio
    async def test_built_agent_runs(self) -> None:
        mock = MockProvider()
        mock.add_response(
            content="Built and running!",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        agent = (
            AgentBuilder()
            .with_provider(provider=mock)
            .build()
        )
        result = await agent.run("test")
        assert result.success
        assert result.response == "Built and running!"
