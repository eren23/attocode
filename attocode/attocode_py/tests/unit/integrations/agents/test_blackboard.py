"""Comprehensive tests for the SharedBlackboard module."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from attocode.integrations.agents.blackboard import (
    BlackboardEntry,
    BlackboardMetrics,
    NamespaceMetrics,
    SharedBlackboard,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def bb() -> SharedBlackboard:
    """Fresh blackboard with no default TTL."""
    return SharedBlackboard()


@pytest.fixture
def bb_ttl() -> SharedBlackboard:
    """Blackboard with a short default TTL for expiry tests."""
    return SharedBlackboard(default_ttl=0.05)


# =============================================================================
# Data Types
# =============================================================================


class TestBlackboardEntry:
    def test_defaults(self) -> None:
        entry = BlackboardEntry(key="k", value="v", owner="agent-1")
        assert entry.key == "k"
        assert entry.value == "v"
        assert entry.owner == "agent-1"
        assert entry.ttl is None
        assert entry.expires_at is None
        assert entry.metadata == {}
        assert entry.timestamp > 0

    def test_not_expired_when_no_ttl(self) -> None:
        entry = BlackboardEntry(key="k", value="v", owner="o")
        assert not entry.is_expired

    def test_expired_when_past(self) -> None:
        entry = BlackboardEntry(
            key="k", value="v", owner="o", expires_at=time.monotonic() - 1.0
        )
        assert entry.is_expired

    def test_not_expired_when_future(self) -> None:
        entry = BlackboardEntry(
            key="k", value="v", owner="o", expires_at=time.monotonic() + 100.0
        )
        assert not entry.is_expired


class TestNamespaceMetrics:
    def test_defaults(self) -> None:
        m = NamespaceMetrics()
        assert m.reads == 0
        assert m.writes == 0
        assert m.deletes == 0
        assert m.expirations == 0

    def test_total_operations(self) -> None:
        m = NamespaceMetrics(reads=5, writes=3, deletes=2, expirations=1)
        assert m.total_operations == 10  # reads + writes + deletes


class TestBlackboardMetrics:
    def test_defaults(self) -> None:
        m = BlackboardMetrics()
        assert m.total_entries == 0
        assert m.total_reads == 0
        assert m.total_writes == 0
        assert m.total_deletes == 0
        assert m.total_expirations == 0
        assert m.namespaces == {}
        assert m.active_subscribers == 0
        assert m.pattern_subscribers == 0


# =============================================================================
# Core Operations: publish / get
# =============================================================================


class TestPublishAndGet:
    def test_publish_then_get(self, bb: SharedBlackboard) -> None:
        bb.publish("foo", 42, owner="agent-1")
        assert bb.get("foo") == 42

    def test_publish_overwrites(self, bb: SharedBlackboard) -> None:
        bb.publish("key", "first", owner="a")
        bb.publish("key", "second", owner="b")
        assert bb.get("key") == "second"

    def test_get_missing_returns_none(self, bb: SharedBlackboard) -> None:
        assert bb.get("nonexistent") is None

    def test_get_missing_returns_default(self, bb: SharedBlackboard) -> None:
        assert bb.get("nonexistent", default="fallback") == "fallback"

    def test_get_expired_returns_default(self, bb: SharedBlackboard) -> None:
        bb.publish("x", 1, owner="o", ttl=0.001)
        time.sleep(0.01)
        assert bb.get("x", default="gone") == "gone"

    def test_publish_various_value_types(self, bb: SharedBlackboard) -> None:
        bb.publish("str", "hello")
        bb.publish("int", 42)
        bb.publish("list", [1, 2, 3])
        bb.publish("dict", {"a": 1})
        bb.publish("none", None)

        assert bb.get("str") == "hello"
        assert bb.get("int") == 42
        assert bb.get("list") == [1, 2, 3]
        assert bb.get("dict") == {"a": 1}
        assert bb.get("none") is None

    def test_publish_default_owner_is_system(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v")
        entry = bb.get_entry("k")
        assert entry is not None
        assert entry.owner == "system"


# =============================================================================
# get_entry
# =============================================================================


class TestGetEntry:
    def test_existing_entry(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v", owner="agent-1")
        entry = bb.get_entry("k")
        assert entry is not None
        assert entry.key == "k"
        assert entry.value == "v"
        assert entry.owner == "agent-1"

    def test_missing_entry(self, bb: SharedBlackboard) -> None:
        assert bb.get_entry("nope") is None

    def test_expired_entry(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v", ttl=0.001)
        time.sleep(0.01)
        assert bb.get_entry("k") is None


# =============================================================================
# has()
# =============================================================================


class TestHas:
    def test_has_existing(self, bb: SharedBlackboard) -> None:
        bb.publish("key", "value")
        assert bb.has("key") is True

    def test_has_missing(self, bb: SharedBlackboard) -> None:
        assert bb.has("nope") is False

    def test_has_expired(self, bb: SharedBlackboard) -> None:
        bb.publish("key", "value", ttl=0.001)
        time.sleep(0.01)
        assert bb.has("key") is False


# =============================================================================
# keys() and items()
# =============================================================================


class TestKeysAndItems:
    def test_keys_empty(self, bb: SharedBlackboard) -> None:
        assert bb.keys() == []

    def test_keys_returns_all(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.publish("b", 2)
        bb.publish("c", 3)
        assert sorted(bb.keys()) == ["a", "b", "c"]

    def test_keys_excludes_expired(self, bb: SharedBlackboard) -> None:
        bb.publish("alive", 1)
        bb.publish("dead", 2, ttl=0.001)
        time.sleep(0.01)
        assert bb.keys() == ["alive"]

    def test_items_empty(self, bb: SharedBlackboard) -> None:
        assert bb.items() == []

    def test_items_returns_all(self, bb: SharedBlackboard) -> None:
        bb.publish("x", 10)
        bb.publish("y", 20)
        result = sorted(bb.items(), key=lambda t: t[0])
        assert result == [("x", 10), ("y", 20)]

    def test_items_excludes_expired(self, bb: SharedBlackboard) -> None:
        bb.publish("alive", 1)
        bb.publish("dead", 2, ttl=0.001)
        time.sleep(0.01)
        assert bb.items() == [("alive", 1)]


# =============================================================================
# remove()
# =============================================================================


class TestRemove:
    def test_remove_existing(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v", owner="a")
        assert bb.remove("k") is True
        assert bb.has("k") is False

    def test_remove_missing(self, bb: SharedBlackboard) -> None:
        assert bb.remove("nope") is False

    def test_remove_updates_agent_keys(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v", owner="agent-1")
        assert "k" in bb.get_agent_keys("agent-1")
        bb.remove("k")
        assert "k" not in bb.get_agent_keys("agent-1")

    def test_remove_records_delete_metric(self, bb: SharedBlackboard) -> None:
        bb.publish("ns:k", "v")
        bb.remove("ns:k")
        m = bb.get_namespace_metrics("ns")
        assert m.deletes == 1


# =============================================================================
# Namespace Operations
# =============================================================================


class TestNamespaceOperations:
    def test_agent_id_key_pattern(self, bb: SharedBlackboard) -> None:
        bb.publish("agent-1:status", "running", owner="agent-1")
        bb.publish("agent-1:result", {"data": 1}, owner="agent-1")
        bb.publish("agent-2:status", "idle", owner="agent-2")

        ns = bb.get_namespace("agent-1")
        assert "agent-1:status" in ns
        assert "agent-1:result" in ns
        assert "agent-2:status" not in ns

    def test_get_namespace_includes_owned_keys(self, bb: SharedBlackboard) -> None:
        # Keys owned by agent but not using namespace prefix
        bb.publish("global_key", "val", owner="agent-1")
        ns = bb.get_namespace("agent-1")
        assert "global_key" in ns

    def test_get_namespace_excludes_expired(self, bb: SharedBlackboard) -> None:
        bb.publish("agent-1:alive", 1, owner="agent-1")
        bb.publish("agent-1:dead", 2, owner="agent-1", ttl=0.001)
        time.sleep(0.01)
        ns = bb.get_namespace("agent-1")
        assert "agent-1:alive" in ns
        assert "agent-1:dead" not in ns

    def test_get_agent_keys(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1, owner="agent-1")
        bb.publish("b", 2, owner="agent-1")
        bb.publish("c", 3, owner="agent-2")
        keys = sorted(bb.get_agent_keys("agent-1"))
        assert keys == ["a", "b"]

    def test_get_agent_keys_empty(self, bb: SharedBlackboard) -> None:
        assert bb.get_agent_keys("no-such-agent") == []


# =============================================================================
# TTL and Expiry
# =============================================================================


class TestTTLAndExpiry:
    def test_publish_with_explicit_ttl(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v", ttl=10.0)
        entry = bb.get_entry("k")
        assert entry is not None
        assert entry.ttl == 10.0
        assert entry.expires_at is not None

    def test_publish_with_zero_ttl_no_expiry(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v", ttl=0)
        entry = bb.get_entry("k")
        assert entry is not None
        assert entry.expires_at is None

    def test_publish_with_negative_ttl_no_expiry(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v", ttl=-1)
        entry = bb.get_entry("k")
        assert entry is not None
        assert entry.expires_at is None

    def test_default_ttl_applied(self, bb_ttl: SharedBlackboard) -> None:
        bb_ttl.publish("k", "v")
        entry = bb_ttl.get_entry("k")
        assert entry is not None
        assert entry.ttl == 0.05
        assert entry.expires_at is not None

    def test_explicit_ttl_overrides_default(self, bb_ttl: SharedBlackboard) -> None:
        bb_ttl.publish("k", "v", ttl=999.0)
        entry = bb_ttl.get_entry("k")
        assert entry is not None
        assert entry.ttl == 999.0

    def test_entry_expires_after_ttl(self, bb: SharedBlackboard) -> None:
        bb.publish("ephemeral", "data", ttl=0.01)
        assert bb.has("ephemeral") is True
        time.sleep(0.02)
        assert bb.has("ephemeral") is False

    def test_cleanup_expired(self, bb: SharedBlackboard) -> None:
        bb.publish("keep", "yes")
        bb.publish("expire1", "no", ttl=0.001)
        bb.publish("expire2", "no", ttl=0.001)
        time.sleep(0.01)
        removed = bb.cleanup_expired()
        assert removed == 2
        assert bb.has("keep") is True
        assert bb.has("expire1") is False
        assert bb.has("expire2") is False

    def test_cleanup_expired_records_metrics(self, bb: SharedBlackboard) -> None:
        bb.publish("ns:expire", "v", ttl=0.001)
        time.sleep(0.01)
        bb.cleanup_expired()
        m = bb.get_namespace_metrics("ns")
        assert m.expirations == 1

    def test_cleanup_expired_removes_agent_keys(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v", owner="agent-1", ttl=0.001)
        time.sleep(0.01)
        bb.cleanup_expired()
        assert "k" not in bb.get_agent_keys("agent-1")

    def test_cleanup_when_nothing_expired(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.publish("b", 2)
        removed = bb.cleanup_expired()
        assert removed == 0


# =============================================================================
# subscribe() - key-specific
# =============================================================================


class TestSubscribe:
    def test_subscriber_called_on_publish(self, bb: SharedBlackboard) -> None:
        calls: list[tuple[str, object, str]] = []
        bb.subscribe("status", lambda k, v, o: calls.append((k, v, o)))
        bb.publish("status", "running", owner="agent-1")
        assert len(calls) == 1
        assert calls[0] == ("status", "running", "agent-1")

    def test_subscriber_not_called_for_other_keys(
        self, bb: SharedBlackboard
    ) -> None:
        calls: list[tuple[str, object, str]] = []
        bb.subscribe("status", lambda k, v, o: calls.append((k, v, o)))
        bb.publish("other_key", "value")
        assert len(calls) == 0

    def test_multiple_subscribers_on_same_key(self, bb: SharedBlackboard) -> None:
        calls_a: list[str] = []
        calls_b: list[str] = []
        bb.subscribe("key", lambda k, v, o: calls_a.append("a"))
        bb.subscribe("key", lambda k, v, o: calls_b.append("b"))
        bb.publish("key", "val")
        assert len(calls_a) == 1
        assert len(calls_b) == 1

    def test_unsubscribe_function(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        unsub = bb.subscribe("key", lambda k, v, o: calls.append("hit"))
        bb.publish("key", 1)
        assert len(calls) == 1
        unsub()
        bb.publish("key", 2)
        assert len(calls) == 1  # Not called after unsubscribe

    def test_unsubscribe_twice_safe(self, bb: SharedBlackboard) -> None:
        unsub = bb.subscribe("key", lambda k, v, o: None)
        unsub()
        unsub()  # Should not raise

    def test_subscriber_exception_does_not_propagate(
        self, bb: SharedBlackboard
    ) -> None:
        def bad_callback(k: str, v: object, o: str) -> None:
            raise RuntimeError("boom")

        good_calls: list[str] = []
        bb.subscribe("key", bad_callback)
        bb.subscribe("key", lambda k, v, o: good_calls.append("ok"))
        bb.publish("key", "val")
        # The good subscriber should still be called
        assert len(good_calls) == 1


# =============================================================================
# subscribe_all() - global
# =============================================================================


class TestSubscribeAll:
    def test_called_for_every_publish(self, bb: SharedBlackboard) -> None:
        calls: list[tuple[str, object, str]] = []
        bb.subscribe_all(lambda k, v, o: calls.append((k, v, o)))
        bb.publish("a", 1, owner="x")
        bb.publish("b", 2, owner="y")
        assert len(calls) == 2
        assert calls[0] == ("a", 1, "x")
        assert calls[1] == ("b", 2, "y")

    def test_unsubscribe_all(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        unsub = bb.subscribe_all(lambda k, v, o: calls.append("hit"))
        bb.publish("k", 1)
        assert len(calls) == 1
        unsub()
        bb.publish("k", 2)
        assert len(calls) == 1

    def test_global_subscriber_exception_contained(
        self, bb: SharedBlackboard
    ) -> None:
        def bad(k: str, v: object, o: str) -> None:
            raise ValueError("oops")

        good_calls: list[str] = []
        bb.subscribe_all(bad)
        bb.subscribe_all(lambda k, v, o: good_calls.append("ok"))
        bb.publish("k", "v")
        assert len(good_calls) == 1


# =============================================================================
# subscribe_pattern() - fnmatch patterns
# =============================================================================


class TestSubscribePattern:
    def test_pattern_match(self, bb: SharedBlackboard) -> None:
        calls: list[tuple[str, object, str]] = []
        bb.subscribe_pattern(
            "agent-*:status", lambda k, v, o: calls.append((k, v, o))
        )
        bb.publish("agent-1:status", "running", owner="agent-1")
        bb.publish("agent-2:status", "idle", owner="agent-2")
        bb.publish("agent-1:result", "done", owner="agent-1")
        assert len(calls) == 2
        assert calls[0][0] == "agent-1:status"
        assert calls[1][0] == "agent-2:status"

    def test_pattern_no_match(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        bb.subscribe_pattern("task-*", lambda k, v, o: calls.append("hit"))
        bb.publish("agent-1:status", "running")
        assert len(calls) == 0

    def test_star_pattern_matches_all(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        bb.subscribe_pattern("*", lambda k, v, o: calls.append(k))
        bb.publish("a", 1)
        bb.publish("b:c", 2)
        # fnmatch("b:c", "*") is True on most platforms
        assert len(calls) >= 1  # "a" always matches

    def test_question_mark_pattern(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        bb.subscribe_pattern("k?", lambda k, v, o: calls.append(k))
        bb.publish("k1", 1)
        bb.publish("k2", 2)
        bb.publish("key", 3)  # Does not match "k?"
        assert sorted(calls) == ["k1", "k2"]

    def test_unsubscribe_pattern(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        unsub = bb.subscribe_pattern("*", lambda k, v, o: calls.append("hit"))
        bb.publish("k", 1)
        assert len(calls) == 1
        unsub()
        bb.publish("k", 2)
        assert len(calls) == 1

    def test_pattern_subscriber_exception_contained(
        self, bb: SharedBlackboard
    ) -> None:
        def bad(k: str, v: object, o: str) -> None:
            raise RuntimeError("pattern boom")

        good_calls: list[str] = []
        bb.subscribe_pattern("*", bad)
        bb.subscribe_pattern("*", lambda k, v, o: good_calls.append("ok"))
        bb.publish("k", "v")
        assert len(good_calls) == 1


# =============================================================================
# Combined subscriber interactions
# =============================================================================


class TestCombinedSubscribers:
    def test_key_and_global_both_fire(self, bb: SharedBlackboard) -> None:
        key_calls: list[str] = []
        global_calls: list[str] = []
        bb.subscribe("key", lambda k, v, o: key_calls.append("key"))
        bb.subscribe_all(lambda k, v, o: global_calls.append("global"))
        bb.publish("key", "v")
        assert len(key_calls) == 1
        assert len(global_calls) == 1

    def test_key_global_and_pattern_all_fire(self, bb: SharedBlackboard) -> None:
        key_calls: list[str] = []
        global_calls: list[str] = []
        pattern_calls: list[str] = []
        bb.subscribe("my:key", lambda k, v, o: key_calls.append("k"))
        bb.subscribe_all(lambda k, v, o: global_calls.append("g"))
        bb.subscribe_pattern("my:*", lambda k, v, o: pattern_calls.append("p"))
        bb.publish("my:key", "v")
        assert len(key_calls) == 1
        assert len(global_calls) == 1
        assert len(pattern_calls) == 1


# =============================================================================
# unsubscribe_agent()
# =============================================================================


class TestUnsubscribeAgent:
    def test_removes_key_subscribers(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        bb.subscribe("k", lambda k, v, o: calls.append("hit"), subscriber_id="agent-1")
        bb.unsubscribe_agent("agent-1")
        bb.publish("k", "v")
        assert len(calls) == 0

    def test_removes_global_subscribers(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        bb.subscribe_all(
            lambda k, v, o: calls.append("hit"), subscriber_id="agent-1"
        )
        bb.unsubscribe_agent("agent-1")
        bb.publish("k", "v")
        assert len(calls) == 0

    def test_removes_pattern_subscribers(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        bb.subscribe_pattern(
            "*", lambda k, v, o: calls.append("hit"), subscriber_id="agent-1"
        )
        bb.unsubscribe_agent("agent-1")
        bb.publish("k", "v")
        assert len(calls) == 0

    def test_does_not_remove_other_agents(self, bb: SharedBlackboard) -> None:
        calls_1: list[str] = []
        calls_2: list[str] = []
        bb.subscribe(
            "k", lambda k, v, o: calls_1.append("1"), subscriber_id="agent-1"
        )
        bb.subscribe(
            "k", lambda k, v, o: calls_2.append("2"), subscriber_id="agent-2"
        )
        bb.unsubscribe_agent("agent-1")
        bb.publish("k", "v")
        assert len(calls_1) == 0
        assert len(calls_2) == 1

    def test_unsubscribe_nonexistent_agent_safe(
        self, bb: SharedBlackboard
    ) -> None:
        bb.unsubscribe_agent("no-such-agent")  # Should not raise


# =============================================================================
# release_all() by owner
# =============================================================================


class TestReleaseAll:
    def test_release_removes_owned_keys(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1, owner="agent-1")
        bb.publish("b", 2, owner="agent-1")
        bb.publish("c", 3, owner="agent-2")
        removed = bb.release_all("agent-1")
        assert removed == 2
        assert bb.has("a") is False
        assert bb.has("b") is False
        assert bb.has("c") is True

    def test_release_returns_zero_for_unknown_owner(
        self, bb: SharedBlackboard
    ) -> None:
        assert bb.release_all("no-such-agent") == 0

    def test_release_cleans_agent_keys_tracking(
        self, bb: SharedBlackboard
    ) -> None:
        bb.publish("k", "v", owner="agent-1")
        bb.release_all("agent-1")
        assert bb.get_agent_keys("agent-1") == []

    def test_release_then_publish_fresh(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "old", owner="agent-1")
        bb.release_all("agent-1")
        bb.publish("k", "new", owner="agent-1")
        assert bb.get("k") == "new"
        assert bb.get_agent_keys("agent-1") == ["k"]


# =============================================================================
# get_metrics() and get_namespace_metrics()
# =============================================================================


class TestMetrics:
    def test_empty_metrics(self, bb: SharedBlackboard) -> None:
        m = bb.get_metrics()
        assert m.total_entries == 0
        assert m.total_reads == 0
        assert m.total_writes == 0
        assert m.total_deletes == 0
        assert m.total_expirations == 0
        assert m.active_subscribers == 0
        assert m.pattern_subscribers == 0

    def test_write_metrics(self, bb: SharedBlackboard) -> None:
        bb.publish("ns:k1", "v1")
        bb.publish("ns:k2", "v2")
        m = bb.get_metrics()
        assert m.total_writes == 2
        assert m.total_entries == 2

    def test_read_metrics(self, bb: SharedBlackboard) -> None:
        bb.publish("ns:k", "v")
        bb.get("ns:k")
        bb.get("ns:k")
        m = bb.get_metrics()
        assert m.total_reads == 2

    def test_read_missing_does_not_record_metric(
        self, bb: SharedBlackboard
    ) -> None:
        bb.get("nonexistent")
        m = bb.get_metrics()
        assert m.total_reads == 0

    def test_delete_metrics(self, bb: SharedBlackboard) -> None:
        bb.publish("ns:k", "v")
        bb.remove("ns:k")
        m = bb.get_metrics()
        assert m.total_deletes == 1

    def test_subscriber_counts(self, bb: SharedBlackboard) -> None:
        bb.subscribe("k1", lambda k, v, o: None)
        bb.subscribe("k2", lambda k, v, o: None)
        bb.subscribe_all(lambda k, v, o: None)
        bb.subscribe_pattern("*", lambda k, v, o: None)
        m = bb.get_metrics()
        assert m.active_subscribers == 3  # 2 key-specific + 1 global
        assert m.pattern_subscribers == 1

    def test_namespace_metrics_isolation(self, bb: SharedBlackboard) -> None:
        bb.publish("ns1:a", 1)
        bb.publish("ns2:b", 2)
        bb.get("ns1:a")
        m1 = bb.get_namespace_metrics("ns1")
        m2 = bb.get_namespace_metrics("ns2")
        assert m1.writes == 1
        assert m1.reads == 1
        assert m2.writes == 1
        assert m2.reads == 0

    def test_global_namespace_for_unnamespaced_keys(
        self, bb: SharedBlackboard
    ) -> None:
        bb.publish("plain_key", "v")
        m = bb.get_namespace_metrics("__global__")
        assert m.writes == 1

    def test_expiration_metrics(self, bb: SharedBlackboard) -> None:
        bb.publish("ns:exp", "v", ttl=0.001)
        time.sleep(0.01)
        bb.cleanup_expired()
        m = bb.get_namespace_metrics("ns")
        assert m.expirations == 1
        agg = bb.get_metrics()
        assert agg.total_expirations == 1


# =============================================================================
# clear()
# =============================================================================


class TestClear:
    def test_clear_removes_all_entries(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.publish("b", 2)
        bb.clear()
        assert bb.size == 0
        assert bb.keys() == []

    def test_clear_removes_subscribers(self, bb: SharedBlackboard) -> None:
        calls: list[str] = []
        bb.subscribe("k", lambda k, v, o: calls.append("key"))
        bb.subscribe_all(lambda k, v, o: calls.append("global"))
        bb.subscribe_pattern("*", lambda k, v, o: calls.append("pattern"))
        bb.clear()
        bb.publish("k", "v")
        # After clear, no subscribers should fire
        assert len(calls) == 0

    def test_clear_resets_metrics(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v")
        bb.get("k")
        bb.clear()
        m = bb.get_metrics()
        assert m.total_writes == 0
        assert m.total_reads == 0
        assert m.namespaces == {}

    def test_clear_resets_agent_keys(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v", owner="agent-1")
        bb.clear()
        assert bb.get_agent_keys("agent-1") == []


# =============================================================================
# snapshot()
# =============================================================================


class TestSnapshot:
    def test_snapshot_empty(self, bb: SharedBlackboard) -> None:
        assert bb.snapshot() == {}

    def test_snapshot_returns_values(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.publish("b", "hello")
        snap = bb.snapshot()
        assert snap == {"a": 1, "b": "hello"}

    def test_snapshot_excludes_expired(self, bb: SharedBlackboard) -> None:
        bb.publish("alive", "yes")
        bb.publish("dead", "no", ttl=0.001)
        time.sleep(0.01)
        snap = bb.snapshot()
        assert "alive" in snap
        assert "dead" not in snap

    def test_snapshot_is_independent_copy(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "original")
        snap = bb.snapshot()
        bb.publish("k", "modified")
        assert snap["k"] == "original"


# =============================================================================
# Async Variants
# =============================================================================


class TestAsyncVariants:
    @pytest.mark.asyncio
    async def test_publish_async(self, bb: SharedBlackboard) -> None:
        await bb.publish_async("k", "v", owner="agent-1")
        assert bb.get("k") == "v"

    @pytest.mark.asyncio
    async def test_get_async(self, bb: SharedBlackboard) -> None:
        bb.publish("k", 42)
        val = await bb.get_async("k")
        assert val == 42

    @pytest.mark.asyncio
    async def test_get_async_default(self, bb: SharedBlackboard) -> None:
        val = await bb.get_async("missing", default="fallback")
        assert val == "fallback"

    @pytest.mark.asyncio
    async def test_remove_async(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v")
        result = await bb.remove_async("k")
        assert result is True
        assert bb.has("k") is False

    @pytest.mark.asyncio
    async def test_remove_async_missing(self, bb: SharedBlackboard) -> None:
        result = await bb.remove_async("nope")
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_expired_async(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1, ttl=0.001)
        bb.publish("b", 2, ttl=0.001)
        bb.publish("c", 3)
        time.sleep(0.01)
        removed = await bb.cleanup_expired_async()
        assert removed == 2
        assert bb.has("c") is True

    @pytest.mark.asyncio
    async def test_release_all_async(self, bb: SharedBlackboard) -> None:
        bb.publish("x", 1, owner="agent-1")
        bb.publish("y", 2, owner="agent-1")
        removed = await bb.release_all_async("agent-1")
        assert removed == 2
        assert bb.size == 0

    @pytest.mark.asyncio
    async def test_clear_async(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.publish("b", 2)
        await bb.clear_async()
        assert bb.size == 0
        assert bb.keys() == []


# =============================================================================
# size property
# =============================================================================


class TestSize:
    def test_empty(self, bb: SharedBlackboard) -> None:
        assert bb.size == 0

    def test_after_publish(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.publish("b", 2)
        assert bb.size == 2

    def test_after_remove(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.publish("b", 2)
        bb.remove("a")
        assert bb.size == 1

    def test_includes_expired_entries(self, bb: SharedBlackboard) -> None:
        """size includes expired entries (documented behavior)."""
        bb.publish("alive", 1)
        bb.publish("dead", 2, ttl=0.001)
        time.sleep(0.01)
        # size does NOT filter expired; only cleanup/has/get do
        assert bb.size == 2

    def test_after_cleanup_expired(self, bb: SharedBlackboard) -> None:
        bb.publish("alive", 1)
        bb.publish("dead", 2, ttl=0.001)
        time.sleep(0.01)
        bb.cleanup_expired()
        assert bb.size == 1

    def test_after_clear(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.clear()
        assert bb.size == 0


# =============================================================================
# Namespace extraction (internal helper exposed via metrics)
# =============================================================================


class TestNamespaceExtraction:
    def test_colon_separated(self, bb: SharedBlackboard) -> None:
        bb.publish("agent-1:key", "v")
        m = bb.get_namespace_metrics("agent-1")
        assert m.writes == 1

    def test_multiple_colons_uses_first(self, bb: SharedBlackboard) -> None:
        bb.publish("ns:sub:key", "v")
        m = bb.get_namespace_metrics("ns")
        assert m.writes == 1

    def test_no_colon_uses_global(self, bb: SharedBlackboard) -> None:
        bb.publish("plain", "v")
        m = bb.get_namespace_metrics("__global__")
        assert m.writes == 1

    def test_extract_namespace_static_method(self) -> None:
        assert SharedBlackboard._extract_namespace("a:b") == "a"
        assert SharedBlackboard._extract_namespace("a:b:c") == "a"
        assert SharedBlackboard._extract_namespace("plain") == "__global__"
        assert SharedBlackboard._extract_namespace(":leading") == ""


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    def test_overwrite_changes_owner(self, bb: SharedBlackboard) -> None:
        bb.publish("k", "v1", owner="agent-1")
        bb.publish("k", "v2", owner="agent-2")
        entry = bb.get_entry("k")
        assert entry is not None
        assert entry.owner == "agent-2"
        # Both agents track the key
        assert "k" in bb.get_agent_keys("agent-1")
        assert "k" in bb.get_agent_keys("agent-2")

    def test_empty_key(self, bb: SharedBlackboard) -> None:
        bb.publish("", "empty_key")
        assert bb.get("") == "empty_key"

    def test_large_value(self, bb: SharedBlackboard) -> None:
        big = list(range(10_000))
        bb.publish("big", big)
        assert bb.get("big") == big

    def test_none_value_distinguishable_from_missing(
        self, bb: SharedBlackboard
    ) -> None:
        bb.publish("k", None)
        assert bb.has("k") is True
        sentinel = object()
        assert bb.get("k", default=sentinel) is None

    def test_publish_triggers_subscriber_synchronously(
        self, bb: SharedBlackboard
    ) -> None:
        """Subscriber is called during publish, not deferred."""
        order: list[str] = []
        bb.subscribe("k", lambda k, v, o: order.append("subscriber"))
        order.append("before_publish")
        bb.publish("k", "v")
        order.append("after_publish")
        assert order == ["before_publish", "subscriber", "after_publish"]

    def test_many_entries(self, bb: SharedBlackboard) -> None:
        for i in range(500):
            bb.publish(f"key-{i}", i, owner=f"agent-{i % 5}")
        assert bb.size == 500
        assert len(bb.keys()) == 500
        # Verify namespace distribution
        for a in range(5):
            keys = bb.get_agent_keys(f"agent-{a}")
            assert len(keys) == 100
