"""Tests for new swarm modules: request_throttle, swarm_budget, failure_classifier, swarm_state_store."""

import asyncio
import tempfile
import time

import pytest

from attocode.integrations.swarm.request_throttle import (
    SwarmThrottle,
    ThrottleConfig,
    ThrottleStats,
    FREE_TIER_THROTTLE,
    PAID_TIER_THROTTLE,
)
from attocode.integrations.swarm.swarm_budget import (
    SwarmBudget,
    SwarmBudgetConfig,
    WorkerSpending,
)
from attocode.integrations.swarm.failure_classifier import (
    classify_swarm_failure,
    SwarmFailureClass,
    FailureClassification,
    NON_RETRYABLE,
    _has_any,
)
from attocode.integrations.swarm.swarm_state_store import (
    SwarmStateStore,
    SwarmStateSnapshot,
)


# ---------------------------------------------------------------------------
# RequestThrottle tests
# ---------------------------------------------------------------------------

class TestThrottleConfig:
    def test_defaults(self):
        cfg = ThrottleConfig()
        assert cfg.max_concurrent == 5
        assert cfg.refill_rate_per_second == 2.0
        assert cfg.min_spacing_ms == 200.0

    def test_presets(self):
        assert FREE_TIER_THROTTLE.max_concurrent == 2
        assert PAID_TIER_THROTTLE.max_concurrent == 5


class TestSwarmThrottle:
    def test_initial_stats(self):
        t = SwarmThrottle(ThrottleConfig(max_concurrent=3))
        stats = t.get_stats()
        assert stats.current_max_concurrent == 3
        assert stats.total_acquired == 0
        assert stats.backoff_level == 0

    def test_backoff_increases_level(self):
        t = SwarmThrottle(ThrottleConfig(max_concurrent=4, min_spacing_ms=100.0))
        t.backoff()
        stats = t.get_stats()
        assert stats.backoff_level == 1
        assert stats.current_max_concurrent == 2  # halved
        assert stats.current_min_spacing_ms == 200.0  # doubled

    def test_backoff_capped_at_max(self):
        t = SwarmThrottle(ThrottleConfig(max_backoff_level=2))
        t.backoff()
        t.backoff()
        t.backoff()  # should not increase beyond 2
        assert t.get_stats().backoff_level == 2

    def test_feed_rate_limit_triggers_backoff(self):
        t = SwarmThrottle()
        t.feed_rate_limit_info(remaining=0)
        assert t.get_stats().backoff_level == 1

    def test_feed_rate_limit_high_reset(self):
        t = SwarmThrottle()
        t.feed_rate_limit_info(reset_ms=10_000)
        assert t.get_stats().backoff_level == 1

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        t = SwarmThrottle(ThrottleConfig(max_concurrent=2, min_spacing_ms=0.0))
        await t.acquire()
        stats = t.get_stats()
        assert stats.total_acquired == 1
        t.release()


# ---------------------------------------------------------------------------
# SwarmBudget tests
# ---------------------------------------------------------------------------

class TestSwarmBudget:
    def test_initial_status(self):
        budget = SwarmBudget(SwarmBudgetConfig(total_max_tokens=1_000_000))
        status = budget.get_status()
        assert status.total_tokens_used == 0
        assert status.total_tokens_remaining == 1_000_000
        assert status.can_spawn_worker is True

    def test_record_worker_usage(self):
        budget = SwarmBudget(SwarmBudgetConfig(total_max_tokens=1_000_000))
        budget.record_worker_usage("w1", 50_000, cost=0.5)
        budget.record_worker_usage("w1", 10_000)
        status = budget.get_status()
        assert status.worker_tokens_used == 60_000
        assert status.worker_count == 1

    def test_record_orchestrator_usage(self):
        budget = SwarmBudget(SwarmBudgetConfig(total_max_tokens=1_000_000))
        budget.record_orchestrator_usage(100_000)
        status = budget.get_status()
        assert status.orchestrator_tokens_used == 100_000

    def test_worker_budget_allocation(self):
        budget = SwarmBudget(SwarmBudgetConfig(
            total_max_tokens=1_000_000,
            per_worker_max_tokens=200_000,
            worker_fraction=0.8,
        ))
        wb = budget.get_worker_budget("w1")
        assert wb.max_tokens == 200_000  # capped by per_worker_max_tokens
        assert wb.max_iterations == 50

    def test_use_reserve(self):
        budget = SwarmBudget(SwarmBudgetConfig(
            total_max_tokens=1_000_000,
            reserve_fraction=0.05,
        ))
        # Reserve is 50_000
        assert budget.use_reserve(30_000) is True
        assert budget.use_reserve(30_000) is False  # exceeds reserve

    def test_can_spawn_worker_false_when_exhausted(self):
        budget = SwarmBudget(SwarmBudgetConfig(
            total_max_tokens=100_000,
            worker_fraction=0.8,
            per_worker_max_tokens=50_000,
        ))
        # Use up nearly all worker budget (80_000 total worker pool)
        budget.record_worker_usage("w1", 75_000)
        assert budget.can_spawn_worker() is False

    def test_to_json_and_restore(self):
        budget = SwarmBudget()
        budget.record_orchestrator_usage(5000)
        budget.record_worker_usage("w1", 1000, cost=0.1)
        budget.record_worker_completion("w1")

        data = budget.to_json()
        assert data["orchestrator_tokens"] == 5000
        assert "w1" in data["workers"]

        budget2 = SwarmBudget()
        budget2.restore_from(data)
        assert budget2.get_status().orchestrator_tokens_used == 5000

    def test_worker_stats(self):
        budget = SwarmBudget()
        budget.record_worker_usage("w1", 100)
        budget.record_worker_usage("w2", 200)
        stats = budget.get_worker_stats()
        assert len(stats) == 2


# ---------------------------------------------------------------------------
# FailureClassifier tests
# ---------------------------------------------------------------------------

class TestFailureClassifier:
    def test_rate_limited(self):
        r = classify_swarm_failure("Error 429: too many requests")
        assert r.failure_class == SwarmFailureClass.RATE_LIMITED
        assert r.retryable is True
        assert r.error_type == "429"

    def test_spend_limit(self):
        r = classify_swarm_failure("HTTP 402 payment required")
        assert r.failure_class == SwarmFailureClass.PROVIDER_SPEND_LIMIT
        assert r.retryable is False

    def test_auth_error(self):
        r = classify_swarm_failure("401 Unauthorized - invalid api key")
        assert r.failure_class == SwarmFailureClass.PROVIDER_AUTH
        assert r.retryable is False

    def test_timeout(self):
        r = classify_swarm_failure("Worker timed out after 120s")
        assert r.failure_class == SwarmFailureClass.TIMEOUT
        assert r.retryable is True

    def test_policy_blocked(self):
        r = classify_swarm_failure("Action blocked by policy")
        assert r.failure_class == SwarmFailureClass.POLICY_BLOCKED
        assert r.retryable is False

    def test_missing_path(self):
        r = classify_swarm_failure("ENOENT: no such file or directory")
        assert r.failure_class == SwarmFailureClass.MISSING_TARGET_PATH

    def test_permission_denied(self):
        r = classify_swarm_failure("EACCES permission denied")
        assert r.failure_class == SwarmFailureClass.PERMISSION_REQUIRED

    def test_transient_server_error(self):
        r = classify_swarm_failure("HTTP 503 server error")
        assert r.failure_class == SwarmFailureClass.PROVIDER_TRANSIENT
        assert r.retryable is True

    def test_unknown_fallback(self):
        r = classify_swarm_failure("something completely unexpected happened")
        assert r.failure_class == SwarmFailureClass.UNKNOWN
        assert r.retryable is True

    def test_non_retryable_set(self):
        assert SwarmFailureClass.POLICY_BLOCKED in NON_RETRYABLE
        assert SwarmFailureClass.RATE_LIMITED not in NON_RETRYABLE

    def test_has_any_helper(self):
        assert _has_any("Rate limit hit", ["rate limit"]) is True
        assert _has_any("all fine", ["error", "timeout"]) is False


# ---------------------------------------------------------------------------
# SwarmStateStore tests
# ---------------------------------------------------------------------------

class TestSwarmStateStore:
    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.store = SwarmStateStore(self._tmp.name)

    def test_save_and_get_session(self):
        self.store.save_session("s1", "executing", task_description="Build API")
        session = self.store.get_session("s1")
        assert session is not None
        assert session["phase"] == "executing"
        assert session["task_description"] == "Build API"

    def test_list_sessions(self):
        self.store.save_session("s1", "executing")
        self.store.save_session("s2", "completed")
        sessions = self.store.list_sessions()
        assert len(sessions) == 2

    def test_delete_session(self):
        self.store.save_session("s1", "executing")
        assert self.store.delete_session("s1") is True
        assert self.store.get_session("s1") is None

    def test_save_and_load_checkpoint(self):
        self.store.save_session("s1", "executing")
        snapshot = SwarmStateSnapshot(
            session_id="s1",
            phase="executing",
            timestamp=time.time(),
            task_queue=[{"id": "t1", "status": "pending"}],
            worker_status={"w1": "running"},
        )
        cp_id = self.store.save_checkpoint("s1", snapshot)
        assert cp_id > 0

        loaded = self.store.load_latest_checkpoint("s1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.phase == "executing"
        assert len(loaded.task_queue) == 1

    def test_load_no_checkpoint(self):
        result = self.store.load_latest_checkpoint("nonexistent")
        assert result is None

    def test_get_nonexistent_session(self):
        assert self.store.get_session("nope") is None
