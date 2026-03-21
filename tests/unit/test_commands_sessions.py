"""Session slash command tests for pre-context usage."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from attocode import commands


@dataclass
class _Session:
    id: str
    task: str
    status: str = "active"
    total_tokens: int = 0
    total_cost: float = 0.0


@dataclass
class _Checkpoint:
    messages: list[dict[str, Any]]


class _FakeStore:
    def __init__(self) -> None:
        self._sessions = [_Session(id="abc123", task="Fix auth bug", total_tokens=1234, total_cost=0.42)]

    async def list_sessions(self, limit: int = 10) -> list[_Session]:
        return self._sessions[:limit]

    async def get_session(self, session_id: str) -> _Session | None:
        return next((s for s in self._sessions if s.id == session_id), None)

    async def load_checkpoint(self, session_id: str) -> _Checkpoint | None:
        if session_id != "abc123":
            return None
        return _Checkpoint(messages=[{"role": "user", "content": "hello"}])

    async def resume_session(self, session_id: str) -> dict[str, Any] | None:
        if session_id != "abc123":
            return None
        return {
            "session": {"id": "abc123", "task": "Fix auth bug", "total_tokens": 1234, "total_cost": 0.42},
            "messages": [{"role": "user", "content": "hello"}],
        }

    async def list_checkpoints(self, session_id: str) -> list[Any]:
        return []


class _FakeAgent:
    def __init__(self, store: _FakeStore) -> None:
        self._store = store
        self.context = None
        self.config = SimpleNamespace(resume_session=None, resume_session_explicit=False)
        self._working_dir = "/tmp"
        self.session_store = None
        self._conversation_messages = ["old"]
        self._session_id = "stale"
        self.reset_called = False

    async def ensure_session_store(self) -> _FakeStore:
        self.session_store = self._store
        return self._store

    def reset_conversation(self) -> None:
        self.reset_called = True
        self._conversation_messages = []
        self._session_id = None
        self.config.resume_session = None
        self.config.resume_session_explicit = False


@pytest.mark.asyncio
async def test_sessions_works_without_active_context() -> None:
    agent = _FakeAgent(_FakeStore())
    result = await commands._sessions_command(agent, "")
    assert "Recent sessions:" in result.output
    assert "[abc123]" in result.output


@pytest.mark.asyncio
async def test_load_stages_resume_without_active_context() -> None:
    agent = _FakeAgent(_FakeStore())
    result = await commands._load_command(agent, "abc123")
    assert "staged for resume" in result.output
    assert agent.config.resume_session == "abc123"
    assert agent.config.resume_session_explicit is True


@pytest.mark.asyncio
async def test_resume_without_id_uses_latest_session() -> None:
    agent = _FakeAgent(_FakeStore())
    result = await commands._resume_command(agent, "")
    assert "staged for resume" in result.output
    assert agent.config.resume_session == "abc123"
    assert agent.config.resume_session_explicit is True


@pytest.mark.asyncio
async def test_trace_id_returns_guidance() -> None:
    agent = _FakeAgent(_FakeStore())
    result = await commands._resume_command(agent, "trace-1727543556")
    assert "trace session" in result.output.lower()
    assert "Use /sessions" in result.output


@pytest.mark.asyncio
async def test_reset_clears_session_state() -> None:
    agent = _FakeAgent(_FakeStore())
    agent.context = SimpleNamespace(
        messages=[{"role": "user", "content": "hello"}],
        iteration=3,
        metrics=object(),
        session_id="abc123",
    )

    result = commands._reset_command(agent)

    assert "Session reset" in result.output
    assert agent.reset_called is True
    assert agent.config.resume_session is None
    assert agent.config.resume_session_explicit is False
    assert agent._session_id is None
