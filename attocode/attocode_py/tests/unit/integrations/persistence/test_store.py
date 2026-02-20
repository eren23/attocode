"""Tests for session store."""

from __future__ import annotations

import pytest

from attocode.integrations.persistence.store import SessionStore


@pytest.fixture
async def store(tmp_path) -> SessionStore:
    """Create a temporary session store."""
    db_path = tmp_path / "test.db"
    s = SessionStore(db_path)
    await s.initialize()
    yield s
    await s.close()


class TestSessionCRUD:
    @pytest.mark.asyncio
    async def test_create_session(self, store: SessionStore) -> None:
        session = await store.create_session("s1", "fix bugs")
        assert session.id == "s1"
        assert session.task == "fix bugs"
        assert session.status == "active"

    @pytest.mark.asyncio
    async def test_get_session(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        session = await store.get_session("s1")
        assert session is not None
        assert session.task == "task"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store: SessionStore) -> None:
        assert await store.get_session("nope") is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, store: SessionStore) -> None:
        await store.create_session("s1", "task1")
        await store.create_session("s2", "task2")
        sessions = await store.list_sessions()
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_list_by_status(self, store: SessionStore) -> None:
        await store.create_session("s1", "task1")
        await store.create_session("s2", "task2")
        await store.update_session("s1", status="completed")
        active = await store.list_sessions(status="active")
        assert len(active) == 1
        assert active[0].id == "s2"

    @pytest.mark.asyncio
    async def test_update_session(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        await store.update_session("s1", status="completed", total_tokens=1000)
        session = await store.get_session("s1")
        assert session.status == "completed"
        assert session.total_tokens == 1000

    @pytest.mark.asyncio
    async def test_delete_session(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        await store.delete_session("s1")
        assert await store.get_session("s1") is None


class TestCheckpoints:
    @pytest.mark.asyncio
    async def test_save_and_load(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        cp_id = await store.save_checkpoint("s1", [{"role": "user", "content": "hi"}])
        assert cp_id > 0

        cp = await store.load_checkpoint("s1")
        assert cp is not None
        assert cp.messages[0]["content"] == "hi"

    @pytest.mark.asyncio
    async def test_latest_checkpoint(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        await store.save_checkpoint("s1", [{"content": "first"}])
        await store.save_checkpoint("s1", [{"content": "second"}])
        cp = await store.load_checkpoint("s1")
        assert cp.messages[0]["content"] == "second"

    @pytest.mark.asyncio
    async def test_list_checkpoints(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        await store.save_checkpoint("s1", [{"n": 1}])
        await store.save_checkpoint("s1", [{"n": 2}])
        cps = await store.list_checkpoints("s1")
        assert len(cps) == 2

    @pytest.mark.asyncio
    async def test_no_checkpoint(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        assert await store.load_checkpoint("s1") is None


class TestGoals:
    @pytest.mark.asyncio
    async def test_create_goal(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        gid = await store.create_goal("s1", "Build API")
        assert gid > 0

    @pytest.mark.asyncio
    async def test_complete_goal(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        gid = await store.create_goal("s1", "Build API")
        await store.complete_goal(gid)
        goals = await store.list_goals("s1", status="completed")
        assert len(goals) == 1
        assert goals[0].completed_at is not None

    @pytest.mark.asyncio
    async def test_list_goals_by_status(self, store: SessionStore) -> None:
        await store.create_session("s1", "task")
        await store.create_goal("s1", "Goal 1")
        g2 = await store.create_goal("s1", "Goal 2")
        await store.complete_goal(g2)
        active = await store.list_goals("s1", status="active")
        assert len(active) == 1
        all_goals = await store.list_goals("s1")
        assert len(all_goals) == 2


class TestStoreLifecycle:
    @pytest.mark.asyncio
    async def test_not_initialized_raises(self) -> None:
        store = SessionStore("/tmp/nonexistent.db")
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.get_session("x")

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path) -> None:
        db_path = tmp_path / "deep" / "nested" / "test.db"
        store = SessionStore(db_path)
        await store.initialize()
        await store.create_session("s1", "task")
        await store.close()
        assert db_path.exists()
