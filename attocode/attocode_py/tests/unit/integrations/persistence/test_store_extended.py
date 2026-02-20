"""Tests for extended session store tables and methods."""

from __future__ import annotations

import json
import time

import pytest

from attocode.integrations.persistence.store import SessionStore


@pytest.fixture
async def store(tmp_path) -> SessionStore:
    """Create a temporary session store with all tables."""
    db_path = tmp_path / "test_extended.db"
    s = SessionStore(db_path)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
async def store_with_session(store: SessionStore) -> SessionStore:
    """Store with a pre-created session for convenience."""
    await store.create_session("s1", "Fix bugs in auth module", model="claude-sonnet")
    return store


# --- Schema verification ---


class TestSchemaExtended:
    """Verify all new tables exist after initialization."""

    @pytest.mark.asyncio
    async def test_tool_calls_table_exists(self, store: SessionStore) -> None:
        db = store._ensure_db()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_calls'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_file_changes_table_exists(self, store: SessionStore) -> None:
        db = store._ensure_db()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_changes'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_compaction_history_table_exists(self, store: SessionStore) -> None:
        db = store._ensure_db()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='compaction_history'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_pending_plans_table_exists(self, store: SessionStore) -> None:
        db = store._ensure_db()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_plans'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_dead_letters_table_exists(self, store: SessionStore) -> None:
        db = store._ensure_db()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dead_letters'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_remembered_permissions_table_exists(self, store: SessionStore) -> None:
        db = store._ensure_db()
        async with db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='remembered_permissions'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_usage_logs_table_exists(self, store: SessionStore) -> None:
        db = store._ensure_db()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_logs'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None


# --- Tool calls ---


class TestToolCalls:
    @pytest.mark.asyncio
    async def test_log_tool_call_with_dict_args(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        record_id = await store.log_tool_call(
            "s1",
            iteration=1,
            tool_name="bash",
            args={"command": "ls -la"},
            result={"stdout": "file.txt"},
            duration_ms=150,
            danger_level="safe",
            approved=True,
        )
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_log_tool_call_with_string_args(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        record_id = await store.log_tool_call(
            "s1",
            iteration=1,
            tool_name="read_file",
            args='{"path": "/tmp/foo"}',
            result='{"content": "hello"}',
        )
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_list_tool_calls(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        await store.log_tool_call("s1", 1, "bash", {"cmd": "ls"}, {"out": ""})
        await store.log_tool_call("s1", 2, "write_file", {"path": "x"}, {"ok": True})
        calls = await store.list_tool_calls("s1")
        assert len(calls) == 2
        assert calls[0].tool_name == "bash"
        assert calls[1].tool_name == "write_file"

    @pytest.mark.asyncio
    async def test_tool_call_approved_flag(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        await store.log_tool_call(
            "s1", 1, "bash", {"cmd": "rm -rf /"}, {}, approved=False
        )
        calls = await store.list_tool_calls("s1")
        assert len(calls) == 1
        assert calls[0].approved is False

    @pytest.mark.asyncio
    async def test_tool_call_danger_level(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        await store.log_tool_call(
            "s1", 1, "bash", {}, {}, danger_level="high"
        )
        calls = await store.list_tool_calls("s1")
        assert calls[0].danger_level == "high"


# --- File changes ---


class TestFileChanges:
    @pytest.mark.asyncio
    async def test_log_file_change(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        record_id = await store.log_file_change(
            "s1",
            iteration=1,
            file_path="/src/main.py",
            before_content="old code",
            after_content="new code",
            tool_name="write_file",
        )
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_list_file_changes(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        await store.log_file_change("s1", 1, "/a.py", "before_a", "after_a", "edit")
        await store.log_file_change("s1", 2, "/b.py", "before_b", "after_b", "write")
        changes = await store.list_file_changes("s1")
        assert len(changes) == 2
        assert changes[0].file_path == "/a.py"
        assert changes[0].before_content == "before_a"
        assert changes[1].after_content == "after_b"

    @pytest.mark.asyncio
    async def test_file_change_preserves_content(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        large_content = "x" * 10_000
        await store.log_file_change("s1", 1, "/big.py", "", large_content)
        changes = await store.list_file_changes("s1")
        assert len(changes[0].after_content) == 10_000


# --- Compaction history ---


class TestCompactionHistory:
    @pytest.mark.asyncio
    async def test_log_compaction(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        record_id = await store.log_compaction(
            "s1",
            iteration=5,
            messages_before=100,
            messages_after=30,
            tokens_saved=15000,
            strategy="reversible",
        )
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_list_compactions(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        await store.log_compaction("s1", 5, 100, 30, 15000, "reversible")
        await store.log_compaction("s1", 10, 80, 25, 12000, "aggressive")
        compactions = await store.list_compactions("s1")
        assert len(compactions) == 2
        assert compactions[0].messages_before == 100
        assert compactions[0].tokens_saved == 15000
        assert compactions[1].strategy == "aggressive"


# --- Pending plans ---


class TestPendingPlans:
    @pytest.mark.asyncio
    async def test_save_pending_plan(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        plan = {"steps": ["step1", "step2"], "priority": "high"}
        record_id = await store.save_pending_plan("s1", plan)
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_load_pending_plan(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        plan = {"steps": ["step1", "step2"]}
        await store.save_pending_plan("s1", plan)
        loaded = await store.load_pending_plan("s1")
        assert loaded is not None
        assert loaded.status == "pending"
        parsed = json.loads(loaded.plan_json)
        assert parsed["steps"] == ["step1", "step2"]

    @pytest.mark.asyncio
    async def test_load_pending_plan_returns_latest(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        await store.save_pending_plan("s1", {"version": 1})
        await store.save_pending_plan("s1", {"version": 2})
        loaded = await store.load_pending_plan("s1")
        parsed = json.loads(loaded.plan_json)
        assert parsed["version"] == 2

    @pytest.mark.asyncio
    async def test_load_no_pending_plan(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        assert await store.load_pending_plan("s1") is None

    @pytest.mark.asyncio
    async def test_resolve_pending_plan(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        await store.save_pending_plan("s1", {"steps": ["a"]})
        await store.resolve_pending_plan("s1", "approved")
        loaded = await store.load_pending_plan("s1")
        assert loaded is None  # No more pending plans

    @pytest.mark.asyncio
    async def test_resolve_only_affects_pending(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        await store.save_pending_plan("s1", {"v": 1})
        await store.resolve_pending_plan("s1", "rejected")
        # Save a new pending plan after resolving the old one
        await store.save_pending_plan("s1", {"v": 2})
        loaded = await store.load_pending_plan("s1")
        assert loaded is not None
        assert json.loads(loaded.plan_json)["v"] == 2

    @pytest.mark.asyncio
    async def test_save_pending_plan_with_list(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        plan = [{"step": "a"}, {"step": "b"}]
        record_id = await store.save_pending_plan("s1", plan)
        assert record_id > 0
        loaded = await store.load_pending_plan("s1")
        parsed = json.loads(loaded.plan_json)
        assert isinstance(parsed, list)
        assert len(parsed) == 2


# --- Dead letters ---


class TestDeadLetters:
    @pytest.mark.asyncio
    async def test_add_dead_letter(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        record_id = await store.add_dead_letter(
            "s1", "tool_exec", {"tool": "bash", "cmd": "fail"}, "Command failed"
        )
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_drain_dead_letters(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        await store.add_dead_letter("s1", "tool_exec", {"t": "a"}, "err1")
        await store.add_dead_letter("s1", "llm_call", {"m": "b"}, "err2")
        letters = await store.drain_dead_letters("s1")
        assert len(letters) == 2
        assert letters[0].operation_type == "tool_exec"
        assert letters[1].error_message == "err2"
        assert letters[0].retry_count == 0

    @pytest.mark.asyncio
    async def test_retry_dead_letter(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        lid = await store.add_dead_letter("s1", "op", {}, "failed")
        await store.retry_dead_letter(lid)
        await store.retry_dead_letter(lid)
        letters = await store.drain_dead_letters("s1")
        assert len(letters) == 1
        assert letters[0].retry_count == 2
        assert letters[0].last_retry_at is not None

    @pytest.mark.asyncio
    async def test_dead_letter_with_string_payload(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        lid = await store.add_dead_letter("s1", "op", '{"raw": true}', "err")
        letters = await store.drain_dead_letters("s1")
        assert letters[0].payload_json == '{"raw": true}'


# --- Remembered permissions ---


class TestRememberedPermissions:
    @pytest.mark.asyncio
    async def test_grant_permission(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        pid = await store.grant_permission("s1", "bash", "*", "allow")
        assert pid > 0

    @pytest.mark.asyncio
    async def test_check_permission_wildcard(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        await store.grant_permission("s1", "bash", "*", "allow")
        assert await store.check_permission("s1", "bash", "ls -la") is True

    @pytest.mark.asyncio
    async def test_check_permission_pattern_match(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        await store.grant_permission("s1", "write_file", "/src/*", "allow")
        assert await store.check_permission("s1", "write_file", "/src/main.py") is True
        assert await store.check_permission("s1", "write_file", "/etc/passwd") is False

    @pytest.mark.asyncio
    async def test_check_permission_no_match(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        assert await store.check_permission("s1", "bash", "rm -rf /") is False

    @pytest.mark.asyncio
    async def test_check_permission_expired(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        # Grant a permission that already expired
        past = time.time() - 3600
        await store.grant_permission("s1", "bash", "*", "allow", expires_at=past)
        assert await store.check_permission("s1", "bash", "ls") is False

    @pytest.mark.asyncio
    async def test_check_permission_not_expired(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        future = time.time() + 3600
        await store.grant_permission("s1", "bash", "*", "allow", expires_at=future)
        assert await store.check_permission("s1", "bash", "ls") is True

    @pytest.mark.asyncio
    async def test_list_permissions(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        await store.grant_permission("s1", "bash", "*", "allow")
        await store.grant_permission("s1", "write_file", "/src/*", "allow")
        perms = await store.list_permissions("s1")
        assert len(perms) == 2
        assert perms[0].tool_name == "bash"
        assert perms[1].pattern == "/src/*"


# --- Usage logs ---


class TestUsageLogs:
    @pytest.mark.asyncio
    async def test_log_usage(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        record_id = await store.log_usage(
            "s1",
            iteration=1,
            provider="anthropic",
            model="claude-sonnet",
            input_tokens=1000,
            output_tokens=500,
            cache_read=200,
            cache_write=100,
            cost=0.005,
        )
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_list_usage_logs(self, store_with_session: SessionStore) -> None:
        store = store_with_session
        await store.log_usage("s1", 1, "anthropic", "claude", 1000, 500, 200, 100, 0.005)
        await store.log_usage("s1", 2, "openai", "gpt-4o", 800, 300, 0, 0, 0.003)
        logs = await store.list_usage_logs("s1")
        assert len(logs) == 2
        assert logs[0].provider == "anthropic"
        assert logs[0].input_tokens == 1000
        assert logs[0].cache_read_tokens == 200
        assert logs[1].model == "gpt-4o"
        assert logs[1].cost == pytest.approx(0.003)


# --- Session resume ---


class TestSessionResume:
    @pytest.mark.asyncio
    async def test_list_recent_sessions(self, store: SessionStore) -> None:
        await store.create_session("s1", "Task 1", model="claude")
        await store.create_session("s2", "Task 2", model="gpt-4o")
        sessions = await store.list_recent_sessions(limit=10)
        assert len(sessions) == 2
        # Most recent first
        assert sessions[0]["id"] == "s2"
        assert sessions[0]["goal"] == "Task 2"
        assert sessions[1]["id"] == "s1"

    @pytest.mark.asyncio
    async def test_list_recent_sessions_with_checkpoint(
        self, store: SessionStore
    ) -> None:
        await store.create_session("s1", "Task 1")
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        await store.save_checkpoint("s1", msgs)
        sessions = await store.list_recent_sessions()
        assert sessions[0]["message_count"] == 2
        assert sessions[0]["checkpoint_count"] == 1

    @pytest.mark.asyncio
    async def test_list_recent_sessions_limit(self, store: SessionStore) -> None:
        for i in range(5):
            await store.create_session(f"s{i}", f"Task {i}")
        sessions = await store.list_recent_sessions(limit=3)
        assert len(sessions) == 3

    @pytest.mark.asyncio
    async def test_resume_session_basic(self, store: SessionStore) -> None:
        await store.create_session("s1", "Fix bugs", model="claude-sonnet")
        msgs = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "I'll look into it"},
        ]
        await store.save_checkpoint("s1", msgs, metrics={"tokens": 500})
        await store.create_goal("s1", "Fix auth bug")
        await store.update_session("s1", status="paused")

        result = await store.resume_session("s1")
        assert result is not None
        assert result["session"]["id"] == "s1"
        assert result["session"]["task"] == "Fix bugs"
        assert result["session"]["status"] == "active"
        assert result["session"]["model"] == "claude-sonnet"
        assert len(result["messages"]) == 2
        assert result["messages"][0]["content"] == "fix the auth bug"
        assert result["metrics"]["tokens"] == 500
        assert len(result["goals"]) == 1
        assert result["goals"][0]["description"] == "Fix auth bug"

    @pytest.mark.asyncio
    async def test_resume_session_nonexistent(self, store: SessionStore) -> None:
        result = await store.resume_session("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_resume_session_no_checkpoint(self, store: SessionStore) -> None:
        await store.create_session("s1", "Task")
        result = await store.resume_session("s1")
        assert result is not None
        assert result["messages"] == []
        assert result["metrics"] == {}

    @pytest.mark.asyncio
    async def test_resume_session_with_pending_plan(
        self, store: SessionStore
    ) -> None:
        await store.create_session("s1", "Task")
        plan = {"steps": ["a", "b", "c"]}
        await store.save_pending_plan("s1", plan)
        result = await store.resume_session("s1")
        assert result["pending_plan"] is not None
        assert result["pending_plan"]["plan"]["steps"] == ["a", "b", "c"]
        assert result["pending_plan"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_resume_session_with_tool_calls_count(
        self, store: SessionStore
    ) -> None:
        await store.create_session("s1", "Task")
        await store.log_tool_call("s1", 1, "bash", {}, {})
        await store.log_tool_call("s1", 2, "read_file", {}, {})
        result = await store.resume_session("s1")
        assert result["tool_calls_count"] == 2

    @pytest.mark.asyncio
    async def test_resume_session_with_file_changes_count(
        self, store: SessionStore
    ) -> None:
        await store.create_session("s1", "Task")
        await store.log_file_change("s1", 1, "/a.py", "old", "new")
        result = await store.resume_session("s1")
        assert result["file_changes_count"] == 1

    @pytest.mark.asyncio
    async def test_resume_session_reactivates_session(
        self, store: SessionStore
    ) -> None:
        await store.create_session("s1", "Task")
        await store.update_session("s1", status="completed")
        result = await store.resume_session("s1")
        assert result["session"]["status"] == "active"
        # Verify the status is actually updated in the database
        session = await store.get_session("s1")
        assert session.status == "active"


# --- Edge cases ---


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_session_has_no_tool_calls(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        calls = await store.list_tool_calls("s1")
        assert calls == []

    @pytest.mark.asyncio
    async def test_empty_session_has_no_file_changes(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        changes = await store.list_file_changes("s1")
        assert changes == []

    @pytest.mark.asyncio
    async def test_empty_session_has_no_compactions(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        compactions = await store.list_compactions("s1")
        assert compactions == []

    @pytest.mark.asyncio
    async def test_empty_session_has_no_dead_letters(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        letters = await store.drain_dead_letters("s1")
        assert letters == []

    @pytest.mark.asyncio
    async def test_empty_session_has_no_permissions(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        perms = await store.list_permissions("s1")
        assert perms == []

    @pytest.mark.asyncio
    async def test_empty_session_has_no_usage_logs(
        self, store_with_session: SessionStore
    ) -> None:
        store = store_with_session
        logs = await store.list_usage_logs("s1")
        assert logs == []

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolation(self, store: SessionStore) -> None:
        """Tool calls for one session don't leak into another."""
        await store.create_session("s1", "Task 1")
        await store.create_session("s2", "Task 2")
        await store.log_tool_call("s1", 1, "bash", {}, {})
        await store.log_tool_call("s2", 1, "read_file", {}, {})
        calls_s1 = await store.list_tool_calls("s1")
        calls_s2 = await store.list_tool_calls("s2")
        assert len(calls_s1) == 1
        assert calls_s1[0].tool_name == "bash"
        assert len(calls_s2) == 1
        assert calls_s2[0].tool_name == "read_file"
