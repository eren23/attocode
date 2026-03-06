"""Tests for shared state modules (context, economics, budget tracker, persistence)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from attocode.shared.budget_tracker import (
    WorkerBudgetCheckResult,
    WorkerBudgetConfig,
    WorkerBudgetTracker,
    compute_tool_fingerprint,
)
from attocode.shared.persistence import JSONFilePersistenceAdapter, SQLitePersistenceAdapter
from attocode.shared.shared_context_state import SharedContextConfig, SharedContextState
from attocode.shared.shared_economics_state import SharedEconomicsConfig, SharedEconomicsState


class TestSharedContextState:
    def test_construction(self) -> None:
        state = SharedContextState()
        assert state.config.max_references == 200

    def test_custom_config(self) -> None:
        config = SharedContextConfig(max_references=50, max_failures_per_worker=10)
        state = SharedContextState(config=config)
        assert state.config.max_references == 50

    def test_kv_cache_prefix(self) -> None:
        state = SharedContextState()
        assert state.kv_cache_prefix == ""
        state.kv_cache_prefix = "prefix-123"
        assert state.kv_cache_prefix == "prefix-123"

    def test_clear_resets_kv_prefix(self) -> None:
        state = SharedContextState()
        state.kv_cache_prefix = "test"
        state.clear()
        assert state.kv_cache_prefix == ""

    def test_clear_resets_internal_references(self) -> None:
        state = SharedContextState()
        state.clear()
        # After clear, internal _references list should be empty
        assert len(state._references) == 0
        assert len(state._reference_ids) == 0

    def test_search_references_empty(self) -> None:
        state = SharedContextState()
        results = state.search_references("anything")
        assert results == []

    def test_restore_kv_prefix(self) -> None:
        data = {"failures": [], "references": [], "kv_cache_prefix": "restored-prefix"}
        state = SharedContextState()
        state.restore_from(data)
        assert state.kv_cache_prefix == "restored-prefix"

    def test_thread_safety_kv_prefix(self) -> None:
        state = SharedContextState()
        errors: list[Exception] = []

        def worker(prefix: str) -> None:
            try:
                for i in range(100):
                    state.kv_cache_prefix = f"{prefix}-{i}"
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(f"w-{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # The prefix should be set to some valid value
        assert isinstance(state.kv_cache_prefix, str)


class TestSharedEconomicsState:
    def test_initial_stats(self) -> None:
        state = SharedEconomicsState()
        stats = state.get_stats()
        assert stats["unique_fingerprints"] == 0
        assert stats["total_calls"] == 0
        assert stats["active_doom_loops"] == 0

    def test_record_tool_call(self) -> None:
        state = SharedEconomicsState()
        state.record_tool_call("worker-1", "fp-abc")
        stats = state.get_stats()
        assert stats["unique_fingerprints"] == 1
        assert stats["total_calls"] == 1

    def test_doom_loop_detection(self) -> None:
        state = SharedEconomicsState(config=SharedEconomicsConfig(global_doom_threshold=3))
        fp = "doom-fp"
        state.record_tool_call("w1", fp)
        state.record_tool_call("w2", fp)
        assert state.is_global_doom_loop(fp) is False
        state.record_tool_call("w3", fp)
        assert state.is_global_doom_loop(fp) is True

    def test_global_loop_info(self) -> None:
        state = SharedEconomicsState(config=SharedEconomicsConfig(global_doom_threshold=2))
        state.record_tool_call("w1", "fp1")
        state.record_tool_call("w2", "fp1")
        info = state.get_global_loop_info("fp1")
        assert info is not None
        assert info.total_calls == 2
        assert info.worker_count == 2
        assert set(info.workers) == {"w1", "w2"}

    def test_nonexistent_fingerprint(self) -> None:
        state = SharedEconomicsState()
        assert state.is_global_doom_loop("nonexistent") is False
        assert state.get_global_loop_info("nonexistent") is None

    def test_clear(self) -> None:
        state = SharedEconomicsState()
        state.record_tool_call("w1", "fp1")
        state.clear()
        assert state.get_stats()["total_calls"] == 0

    def test_to_json_and_restore(self) -> None:
        state = SharedEconomicsState()
        state.record_tool_call("w1", "fp-a")
        state.record_tool_call("w2", "fp-a")
        data = state.to_json()

        new_state = SharedEconomicsState()
        new_state.restore_from(data)
        assert new_state.get_stats()["total_calls"] == 2


class TestWorkerBudgetTracker:
    def test_initial_usage(self) -> None:
        tracker = WorkerBudgetTracker(worker_id="w1")
        usage = tracker.get_usage()
        assert usage["total_tokens"] == 0
        assert usage["iterations"] == 0

    def test_record_llm_usage(self) -> None:
        tracker = WorkerBudgetTracker(worker_id="w1")
        tracker.record_llm_usage(100, 50)
        usage = tracker.get_usage()
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 50
        assert usage["total_tokens"] == 150

    def test_budget_token_exhaustion(self) -> None:
        config = WorkerBudgetConfig(max_tokens=100, max_iterations=50)
        tracker = WorkerBudgetTracker(worker_id="w1", config=config)
        tracker.record_llm_usage(60, 50)
        result = tracker.check_budget()
        assert result.can_continue is False
        assert result.budget_type == "tokens"

    def test_budget_iteration_exhaustion(self) -> None:
        config = WorkerBudgetConfig(max_tokens=1_000_000, max_iterations=2)
        tracker = WorkerBudgetTracker(worker_id="w1", config=config)
        tracker.record_iteration()
        tracker.record_iteration()
        result = tracker.check_budget()
        assert result.can_continue is False
        assert result.budget_type == "iterations"

    def test_doom_loop_detection(self) -> None:
        config = WorkerBudgetConfig(doom_loop_threshold=3)
        tracker = WorkerBudgetTracker(worker_id="w1", config=config)
        # Same call 3 times
        for _ in range(3):
            tracker.record_tool_call("read_file", {"path": "/foo"})
        result = tracker.check_budget()
        assert result.can_continue is False
        assert result.budget_type == "doom_loop"

    def test_no_doom_loop_different_calls(self) -> None:
        config = WorkerBudgetConfig(doom_loop_threshold=3)
        tracker = WorkerBudgetTracker(worker_id="w1", config=config)
        tracker.record_tool_call("read_file", {"path": "/foo"})
        tracker.record_tool_call("read_file", {"path": "/bar"})
        tracker.record_tool_call("read_file", {"path": "/baz"})
        result = tracker.check_budget()
        assert result.can_continue is True

    def test_utilization(self) -> None:
        config = WorkerBudgetConfig(max_tokens=1000)
        tracker = WorkerBudgetTracker(worker_id="w1", config=config)
        tracker.record_llm_usage(100, 100)
        assert tracker.get_utilization() == pytest.approx(20.0)

    def test_tool_fingerprint_deterministic(self) -> None:
        fp1 = compute_tool_fingerprint("read_file", {"path": "/foo"})
        fp2 = compute_tool_fingerprint("read_file", {"path": "/foo"})
        assert fp1 == fp2

    def test_tool_fingerprint_differs_for_different_args(self) -> None:
        fp1 = compute_tool_fingerprint("read_file", {"path": "/foo"})
        fp2 = compute_tool_fingerprint("read_file", {"path": "/bar"})
        assert fp1 != fp2

    def test_shared_state_reporting(self) -> None:
        shared = SharedEconomicsState()
        tracker = WorkerBudgetTracker(worker_id="w1", shared_state=shared)
        tracker.record_tool_call("bash", {"command": "ls"})
        assert shared.get_stats()["total_calls"] == 1


class TestPersistenceAdapters:
    @pytest.mark.asyncio
    async def test_json_save_and_load(self, tmp_path: Path) -> None:
        adapter = JSONFilePersistenceAdapter(tmp_path / "state")
        await adapter.save("ns1", "key1", {"value": 42})
        result = await adapter.load("ns1", "key1")
        assert result == {"value": 42}

    @pytest.mark.asyncio
    async def test_json_load_missing(self, tmp_path: Path) -> None:
        adapter = JSONFilePersistenceAdapter(tmp_path / "state")
        result = await adapter.load("ns1", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_json_list_keys(self, tmp_path: Path) -> None:
        adapter = JSONFilePersistenceAdapter(tmp_path / "state")
        await adapter.save("ns1", "a", 1)
        await adapter.save("ns1", "b", 2)
        keys = await adapter.list_keys("ns1")
        assert set(keys) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_json_delete(self, tmp_path: Path) -> None:
        adapter = JSONFilePersistenceAdapter(tmp_path / "state")
        await adapter.save("ns1", "key1", "data")
        assert await adapter.delete("ns1", "key1") is True
        assert await adapter.load("ns1", "key1") is None
        assert await adapter.delete("ns1", "key1") is False

    @pytest.mark.asyncio
    async def test_json_exists(self, tmp_path: Path) -> None:
        adapter = JSONFilePersistenceAdapter(tmp_path / "state")
        assert await adapter.exists("ns1", "key1") is False
        await adapter.save("ns1", "key1", "data")
        assert await adapter.exists("ns1", "key1") is True

    @pytest.mark.asyncio
    async def test_sqlite_save_and_load(self, tmp_path: Path) -> None:
        adapter = SQLitePersistenceAdapter(tmp_path / "test.db")
        await adapter.save("ns1", "key1", {"value": 99})
        result = await adapter.load("ns1", "key1")
        assert result == {"value": 99}

    @pytest.mark.asyncio
    async def test_sqlite_list_keys(self, tmp_path: Path) -> None:
        adapter = SQLitePersistenceAdapter(tmp_path / "test.db")
        await adapter.save("ns1", "x", 1)
        await adapter.save("ns1", "y", 2)
        await adapter.save("ns2", "z", 3)
        assert set(await adapter.list_keys("ns1")) == {"x", "y"}

    @pytest.mark.asyncio
    async def test_sqlite_delete_and_exists(self, tmp_path: Path) -> None:
        adapter = SQLitePersistenceAdapter(tmp_path / "test.db")
        await adapter.save("ns1", "key1", "val")
        assert await adapter.exists("ns1", "key1") is True
        assert await adapter.delete("ns1", "key1") is True
        assert await adapter.exists("ns1", "key1") is False
