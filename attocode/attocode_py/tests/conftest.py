"""Global test fixtures for attocode."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

import pytest

from attocode.agent.context import AgentContext
from attocode.providers.mock import MockProvider
from attocode.tools.registry import ToolRegistry
from attocode.types.agent import AgentConfig
from attocode.types.budget import ExecutionBudget


@pytest.fixture
def tmp_workdir(tmp_path: Path) -> Path:
    """Provide a temporary working directory for file operation tests."""
    return tmp_path


@pytest.fixture
def event_loop_policy():
    """Use default asyncio event loop policy."""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def mock_provider() -> Callable[..., MockProvider]:
    """Factory for pre-configured MockProvider instances.

    Usage::

        def test_something(mock_provider):
            provider = mock_provider(responses=["Hello!"])
    """
    def _factory(
        *,
        responses: list[str] | None = None,
        model: str = "mock-model",
    ) -> MockProvider:
        p = MockProvider(model=model)
        if responses:
            for r in responses:
                p.add_response(r)
        return p
    return _factory


@pytest.fixture
def agent_context(
    mock_provider: Callable[..., MockProvider],
    tmp_path: Path,
) -> Callable[..., AgentContext]:
    """Factory for AgentContext instances with sensible defaults.

    Usage::

        def test_something(agent_context):
            ctx = agent_context(working_dir="/tmp/test")
    """
    def _factory(
        *,
        responses: list[str] | None = None,
        working_dir: str | None = None,
        max_iterations: int = 10,
        **kwargs: Any,
    ) -> AgentContext:
        provider = mock_provider(responses=responses or ["Done."])
        registry = ToolRegistry()
        config = AgentConfig(max_iterations=max_iterations)
        budget = ExecutionBudget(max_iterations=max_iterations)
        return AgentContext(
            provider=provider,
            registry=registry,
            config=config,
            budget=budget,
            working_dir=working_dir or str(tmp_path),
            **kwargs,
        )
    return _factory


@pytest.fixture
def tmp_session_dir(tmp_path: Path) -> Path:
    """Temp directory pre-configured for session persistence."""
    session_dir = tmp_path / ".attocode" / "sessions"
    session_dir.mkdir(parents=True)
    return session_dir
