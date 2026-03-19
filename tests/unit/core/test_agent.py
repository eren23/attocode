"""Tests for ProductionAgent and AgentBuilder."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from attocode.agent.agent import ProductionAgent
from attocode.agent.builder import AgentBuilder
from attocode.agent.message_builder import DEFAULT_SYSTEM_PROMPT, build_initial_messages, build_system_prompt
from attocode.integrations.persistence.store import SessionStore
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

    def test_includes_rules(self) -> None:
        msgs = build_initial_messages("Hi", rules=["Python only"])
        assert "Python only" in str(msgs[0].content)


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

    @pytest.mark.asyncio
    async def test_rules_from_agent_config_are_injected(self) -> None:
        provider = MockProvider()
        provider.add_response(
            content="Done",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
            config=AgentConfig(model="mock-model", rules=["Focus only on Python TUI"]),
        )

        await agent.run("test")
        sent_msgs = provider.call_history[0][0]
        assert "Focus only on Python TUI" in str(sent_msgs[0].content)

    def test_reset_conversation_clears_resume_and_session_state(self) -> None:
        agent = ProductionAgent(provider=MockProvider(), registry=ToolRegistry())
        agent._conversation_messages = [object()]
        agent._session_id = "abc123"
        agent.config.resume_session = "resume-me"
        agent._thread_manager = object()

        agent.reset_conversation()

        assert agent._conversation_messages == []
        assert agent._session_id is None
        assert agent.config.resume_session is None
        assert agent.config.resume_session_explicit is False
        assert agent._thread_manager is None

    @pytest.mark.asyncio
    async def test_resume_session_is_consumed_once(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        session_dir = tmp_path / "sessions"
        session_dir.mkdir()
        store = SessionStore(session_dir / "sessions.db")
        await store.initialize()
        await store.create_session(
            "resume1",
            "Old task",
            model="mock-model",
            metadata={
                "working_dir": str(tmp_path),
                "session_dir": str(session_dir),
                "project_root": str(tmp_path),
            },
        )
        await store.save_checkpoint(
            "resume1",
            [
                {"role": "user", "content": "previous user"},
                {"role": "assistant", "content": "previous reply"},
            ],
            {},
        )
        await store.close()

        provider = MockProvider()
        provider.add_response(
            content="First reply",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        provider.add_response(
            content="Second reply",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
            config=AgentConfig(model="mock-model", resume_session="resume1"),
            session_dir=str(session_dir),
            working_dir=str(tmp_path),
        )

        await agent.run("continue")
        assert agent.config.resume_session is None

        await agent.run("next")

        first_messages = provider.call_history[0][0]
        second_messages = provider.call_history[1][0]
        first_text = "\n".join(str(m.content) for m in first_messages)
        second_text = "\n".join(str(m.content) for m in second_messages)
        assert first_text.count("previous user") == 1
        assert second_text.count("previous user") == 1

    @pytest.mark.asyncio
    async def test_missing_resume_emits_rejected_event(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        session_dir = tmp_path / "sessions"
        session_dir.mkdir()

        provider = MockProvider()
        provider.add_response(
            content="fresh reply",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
            config=AgentConfig(model="mock-model", resume_session="missing"),
            session_dir=str(session_dir),
            working_dir=str(tmp_path),
            project_root=str(tmp_path),
        )
        events: list[AgentEvent] = []
        agent.on_event(events.append)

        result = await agent.run("continue")

        assert result.success
        assert EventType.SESSION_RESUME_REJECTED in [event.type for event in events]

    @pytest.mark.asyncio
    async def test_resume_without_store_emits_rejected_event(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        provider = MockProvider()
        provider.add_response(
            content="fresh reply",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
            config=AgentConfig(model="mock-model", resume_session="staged-id"),
            session_dir=None,
            working_dir=str(tmp_path),
            project_root=str(tmp_path),
        )
        events: list[AgentEvent] = []
        agent.on_event(events.append)

        result = await agent.run("continue")

        assert result.success
        rejected = [e for e in events if e.type == EventType.SESSION_RESUME_REJECTED]
        assert rejected
        assert "session persistence" in (rejected[0].metadata or {}).get("message", "").lower()
        assert agent.config.resume_session is None
        assert agent.config.resume_session_explicit is False

    @pytest.mark.asyncio
    async def test_apply_budget_extension_syncs_context_and_economics(self) -> None:
        class _Econ:
            def __init__(self) -> None:
                self.budget: ExecutionBudget | None = None

        provider = MockProvider()
        provider.add_response(
            content="Done",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        econ = _Econ()
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
            budget=ExecutionBudget(max_tokens=1_000_000, soft_token_limit=800_000),
            economics=econ,
        )

        await agent.run("test")
        new_max = agent.apply_budget_extension(500_000)

        assert new_max == 1_500_000
        assert agent.budget.max_tokens == 1_500_000
        assert agent.budget.soft_token_limit == 1_200_000
        assert agent.context is not None
        assert agent.context.budget.max_tokens == 1_500_000
        assert econ.budget is not None
        assert econ.budget.max_tokens == 1_500_000

    @pytest.mark.asyncio
    async def test_request_budget_extension_uses_apply_path(self) -> None:
        provider = MockProvider()
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
            budget=ExecutionBudget(max_tokens=1_000_000, soft_token_limit=800_000),
        )

        async def grant(_request: dict[str, Any]) -> bool:
            return True

        agent.set_extension_handler(grant)
        granted = await agent.request_budget_extension(additional_tokens=250_000, reason="test")

        assert granted
        assert agent.budget.max_tokens == 1_250_000
        assert agent.budget.soft_token_limit == 1_000_000


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

    def test_with_rules(self) -> None:
        mock = MockProvider()
        agent = (
            AgentBuilder()
            .with_provider(provider=mock)
            .with_rules(["Python only"])
            .build()
        )
        assert agent.config.rules == ["Python only"]

    def test_with_project_root(self) -> None:
        mock = MockProvider()
        agent = (
            AgentBuilder()
            .with_provider(provider=mock)
            .with_project_root("/tmp/project")
            .build()
        )
        assert agent.project_root == "/tmp/project"

    @pytest.mark.asyncio
    async def test_subagent_spawn_inherits_rules_and_project_root(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        captured: dict[str, Any] = {}

        class _FakeBuilder:
            def with_provider(self, provider=None, **kwargs):  # type: ignore[no-untyped-def]
                return self

            def with_model(self, model: str):  # type: ignore[no-untyped-def]
                captured["model"] = model
                return self

            def with_working_dir(self, path: str):  # type: ignore[no-untyped-def]
                captured["working_dir"] = path
                return self

            def with_project_root(self, path: str):  # type: ignore[no-untyped-def]
                captured["project_root"] = path
                return self

            def with_rules(self, rules: list[str]):  # type: ignore[no-untyped-def]
                captured["rules"] = list(rules)
                return self

            def with_budget(self, budget):  # type: ignore[no-untyped-def]
                return self

            def with_compaction(self, enabled: bool):  # type: ignore[no-untyped-def]
                return self

            def with_spawn_agent(self, enabled: bool):  # type: ignore[no-untyped-def]
                return self

            def build(self):  # type: ignore[no-untyped-def]
                class _Subagent:
                    async def run(self, task: str):  # type: ignore[no-untyped-def]
                        return SimpleNamespace(success=True, response="ok")

                    async def close(self) -> None:
                        return None

                return _Subagent()

        class _FakeSpawner:
            def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
                pass

            async def spawn(self, run_subagent, **kwargs):  # type: ignore[no-untyped-def]
                await run_subagent(SimpleNamespace(), "sub-1")
                return SimpleNamespace(success=True, response="ok", tokens_used=0, error=None)

        monkeypatch.setattr("attocode.agent.builder.AgentBuilder", _FakeBuilder)
        monkeypatch.setattr("attocode.core.subagent_spawner.SubagentSpawner", _FakeSpawner)

        provider = MockProvider()
        agent = ProductionAgent(
            provider=provider,
            registry=ToolRegistry(),
            config=AgentConfig(model="mock-model", rules=["Python only"]),
            working_dir="/tmp/project/work",
            project_root="/tmp/project",
        )

        result = await agent.spawn_agent("worker-1", "investigate")

        assert result["success"] is True
        assert captured["project_root"] == "/tmp/project"
        assert captured["rules"] == ["Python only"]

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
