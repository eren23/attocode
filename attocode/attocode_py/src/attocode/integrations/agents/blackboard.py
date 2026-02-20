"""Shared blackboard for inter-agent communication.

Provides a key-value store with pub/sub notifications for
coordinating between multiple agents. Features:
- Thread-safe concurrent access via asyncio.Lock
- TTL-based entry expiry
- Namespace isolation (entries keyed by agent_id prefix)
- Read/write metrics per namespace
- Pattern-based subscription
- Automatic cleanup of expired entries
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from dataclasses import dataclass, field
from typing import Any, Callable


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class BlackboardEntry:
    """A single entry in the blackboard."""

    key: str
    value: Any
    owner: str
    timestamp: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)
    ttl: float | None = None  # Seconds until expiry, None = no expiry
    expires_at: float | None = None  # Monotonic time of expiry

    @property
    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        if self.expires_at is None:
            return False
        return time.monotonic() >= self.expires_at


@dataclass(slots=True)
class NamespaceMetrics:
    """Read/write metrics for a namespace."""

    reads: int = 0
    writes: int = 0
    deletes: int = 0
    expirations: int = 0

    @property
    def total_operations(self) -> int:
        return self.reads + self.writes + self.deletes


@dataclass(slots=True)
class BlackboardMetrics:
    """Aggregate metrics for the entire blackboard."""

    total_entries: int = 0
    total_reads: int = 0
    total_writes: int = 0
    total_deletes: int = 0
    total_expirations: int = 0
    namespaces: dict[str, NamespaceMetrics] = field(default_factory=dict)
    active_subscribers: int = 0
    pattern_subscribers: int = 0


Subscriber = Callable[[str, Any, str], None]  # (key, value, owner)
PatternSubscriber = Callable[[str, Any, str], None]  # (key, value, owner)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_TTL: float = 3600.0  # 1 hour
NAMESPACE_SEPARATOR: str = ":"


# =============================================================================
# SharedBlackboard
# =============================================================================


class SharedBlackboard:
    """Shared key-value store with pub/sub for multi-agent coordination.

    Agents can publish data under keys, subscribe to changes,
    and query the shared state. Supports namespace isolation via
    agent_id prefixes, TTL-based expiry, and pattern subscriptions.

    Thread-safe: all mutating operations acquire an asyncio.Lock.
    Non-async methods remain synchronous for backward compatibility
    but should be called from the event loop thread.
    """

    def __init__(self, default_ttl: float | None = None) -> None:
        self._store: dict[str, BlackboardEntry] = {}
        self._subscribers: dict[str, list[tuple[str, Subscriber]]] = {}
        self._global_subscribers: list[tuple[str, Subscriber]] = []
        self._pattern_subscribers: list[tuple[str, str, PatternSubscriber]] = []
        self._agent_keys: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()
        self._default_ttl = default_ttl
        self._namespace_metrics: dict[str, NamespaceMetrics] = {}

    # =========================================================================
    # Core Operations
    # =========================================================================

    def publish(
        self,
        key: str,
        value: Any,
        owner: str = "system",
        ttl: float | None = None,
    ) -> None:
        """Publish a value under a key.

        Args:
            key: The key to publish under.
            value: The value to store.
            owner: The agent ID that owns this entry.
            ttl: Time-to-live in seconds. None uses default_ttl.
                 Set to 0 or negative for no expiry.
        """
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at: float | None = None
        if effective_ttl is not None and effective_ttl > 0:
            expires_at = time.monotonic() + effective_ttl

        entry = BlackboardEntry(
            key=key,
            value=value,
            owner=owner,
            ttl=effective_ttl,
            expires_at=expires_at,
        )
        self._store[key] = entry

        # Track keys per agent
        if owner not in self._agent_keys:
            self._agent_keys[owner] = set()
        self._agent_keys[owner].add(key)

        # Record write metric
        namespace = self._extract_namespace(key)
        self._get_or_create_metrics(namespace).writes += 1

        # Notify subscribers
        self._notify(key, value, owner)

    async def publish_async(
        self,
        key: str,
        value: Any,
        owner: str = "system",
        ttl: float | None = None,
    ) -> None:
        """Thread-safe async version of publish."""
        async with self._lock:
            self.publish(key, value, owner, ttl)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by key. Returns default if not found or expired."""
        entry = self._store.get(key)
        if entry is None:
            return default

        if entry.is_expired:
            self._expire_entry(key, entry)
            return default

        # Record read metric
        namespace = self._extract_namespace(key)
        self._get_or_create_metrics(namespace).reads += 1

        return entry.value

    async def get_async(self, key: str, default: Any = None) -> Any:
        """Thread-safe async version of get."""
        async with self._lock:
            return self.get(key, default)

    def get_entry(self, key: str) -> BlackboardEntry | None:
        """Get the full entry by key. Returns None if not found or expired."""
        entry = self._store.get(key)
        if entry is None:
            return None

        if entry.is_expired:
            self._expire_entry(key, entry)
            return None

        return entry

    def has(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        entry = self._store.get(key)
        if entry is None:
            return False
        if entry.is_expired:
            self._expire_entry(key, entry)
            return False
        return True

    def keys(self) -> list[str]:
        """Get all non-expired keys."""
        self._cleanup_expired_inline()
        return list(self._store.keys())

    def items(self) -> list[tuple[str, Any]]:
        """Get all non-expired key-value pairs."""
        self._cleanup_expired_inline()
        return [(k, e.value) for k, e in self._store.items()]

    def remove(self, key: str) -> bool:
        """Remove a key."""
        if key in self._store:
            entry = self._store.pop(key)
            # Remove from agent tracking
            if entry.owner in self._agent_keys:
                self._agent_keys[entry.owner].discard(key)

            # Record delete metric
            namespace = self._extract_namespace(key)
            self._get_or_create_metrics(namespace).deletes += 1

            return True
        return False

    async def remove_async(self, key: str) -> bool:
        """Thread-safe async version of remove."""
        async with self._lock:
            return self.remove(key)

    # =========================================================================
    # Namespace Operations
    # =========================================================================

    def get_namespace(self, agent_id: str) -> dict[str, Any]:
        """Get all non-expired entries for an agent's namespace.

        Returns a dict of key -> value for all keys owned by the agent
        or prefixed with the agent's namespace.
        """
        self._cleanup_expired_inline()
        result: dict[str, Any] = {}
        prefix = f"{agent_id}{NAMESPACE_SEPARATOR}"

        for key, entry in self._store.items():
            if entry.owner == agent_id or key.startswith(prefix):
                result[key] = entry.value

        return result

    def get_agent_keys(self, owner: str) -> list[str]:
        """Get all keys owned by an agent."""
        return list(self._agent_keys.get(owner, set()))

    # =========================================================================
    # Subscription
    # =========================================================================

    def subscribe(
        self, key: str, callback: Subscriber, subscriber_id: str = ""
    ) -> Callable[[], None]:
        """Subscribe to changes on a specific key.

        Returns an unsubscribe function.
        """
        if key not in self._subscribers:
            self._subscribers[key] = []
        entry = (subscriber_id, callback)
        self._subscribers[key].append(entry)

        def unsubscribe() -> None:
            if key in self._subscribers:
                try:
                    self._subscribers[key].remove(entry)
                except ValueError:
                    pass

        return unsubscribe

    def subscribe_all(
        self, callback: Subscriber, subscriber_id: str = ""
    ) -> Callable[[], None]:
        """Subscribe to all key changes.

        Returns an unsubscribe function.
        """
        entry = (subscriber_id, callback)
        self._global_subscribers.append(entry)

        def unsubscribe() -> None:
            try:
                self._global_subscribers.remove(entry)
            except ValueError:
                pass

        return unsubscribe

    def subscribe_pattern(
        self,
        pattern: str,
        callback: PatternSubscriber,
        subscriber_id: str = "",
    ) -> Callable[[], None]:
        """Subscribe to keys matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g. "agent-*:status", "*.result").
            callback: Called with (key, value, owner) on matching changes.
            subscriber_id: ID for bulk unsubscription.

        Returns an unsubscribe function.
        """
        entry = (subscriber_id, pattern, callback)
        self._pattern_subscribers.append(entry)

        def unsubscribe() -> None:
            try:
                self._pattern_subscribers.remove(entry)
            except ValueError:
                pass

        return unsubscribe

    def unsubscribe_agent(self, agent_id: str) -> None:
        """Remove all subscriptions for an agent."""
        # Key-specific subscribers
        for key in list(self._subscribers.keys()):
            self._subscribers[key] = [
                (sid, cb)
                for sid, cb in self._subscribers[key]
                if sid != agent_id
            ]

        # Global subscribers
        self._global_subscribers = [
            (sid, cb)
            for sid, cb in self._global_subscribers
            if sid != agent_id
        ]

        # Pattern subscribers
        self._pattern_subscribers = [
            (sid, pat, cb)
            for sid, pat, cb in self._pattern_subscribers
            if sid != agent_id
        ]

    # =========================================================================
    # Cleanup & Expiry
    # =========================================================================

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of entries removed."""
        now = time.monotonic()
        expired_keys: list[str] = []

        for key, entry in self._store.items():
            if entry.expires_at is not None and now >= entry.expires_at:
                expired_keys.append(key)

        for key in expired_keys:
            entry = self._store.pop(key, None)
            if entry is not None:
                if entry.owner in self._agent_keys:
                    self._agent_keys[entry.owner].discard(key)
                namespace = self._extract_namespace(key)
                self._get_or_create_metrics(namespace).expirations += 1

        return len(expired_keys)

    async def cleanup_expired_async(self) -> int:
        """Thread-safe async version of cleanup_expired."""
        async with self._lock:
            return self.cleanup_expired()

    def _cleanup_expired_inline(self) -> None:
        """Inline cleanup during reads — avoids separate cleanup calls."""
        now = time.monotonic()
        expired_keys = [
            key
            for key, entry in self._store.items()
            if entry.expires_at is not None and now >= entry.expires_at
        ]
        for key in expired_keys:
            entry = self._store.pop(key, None)
            if entry is not None:
                if entry.owner in self._agent_keys:
                    self._agent_keys[entry.owner].discard(key)
                namespace = self._extract_namespace(key)
                self._get_or_create_metrics(namespace).expirations += 1

    def _expire_entry(self, key: str, entry: BlackboardEntry) -> None:
        """Expire a single entry."""
        self._store.pop(key, None)
        if entry.owner in self._agent_keys:
            self._agent_keys[entry.owner].discard(key)
        namespace = self._extract_namespace(key)
        self._get_or_create_metrics(namespace).expirations += 1

    # =========================================================================
    # Agent Lifecycle
    # =========================================================================

    def release_all(self, owner: str) -> int:
        """Remove all keys owned by an agent. Returns count removed."""
        keys = self._agent_keys.pop(owner, set())
        for key in keys:
            self._store.pop(key, None)
        return len(keys)

    async def release_all_async(self, owner: str) -> int:
        """Thread-safe async version of release_all."""
        async with self._lock:
            return self.release_all(owner)

    # =========================================================================
    # Metrics
    # =========================================================================

    def get_metrics(self) -> BlackboardMetrics:
        """Get aggregate blackboard metrics."""
        total_reads = 0
        total_writes = 0
        total_deletes = 0
        total_expirations = 0

        for m in self._namespace_metrics.values():
            total_reads += m.reads
            total_writes += m.writes
            total_deletes += m.deletes
            total_expirations += m.expirations

        # Count all subscriber entries
        active_key_subs = sum(
            len(subs) for subs in self._subscribers.values()
        )
        active_global_subs = len(self._global_subscribers)

        return BlackboardMetrics(
            total_entries=len(self._store),
            total_reads=total_reads,
            total_writes=total_writes,
            total_deletes=total_deletes,
            total_expirations=total_expirations,
            namespaces=dict(self._namespace_metrics),
            active_subscribers=active_key_subs + active_global_subs,
            pattern_subscribers=len(self._pattern_subscribers),
        )

    def get_namespace_metrics(self, namespace: str) -> NamespaceMetrics:
        """Get metrics for a specific namespace."""
        return self._get_or_create_metrics(namespace)

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def clear(self) -> None:
        """Clear all data and subscriptions."""
        self._store.clear()
        self._subscribers.clear()
        self._global_subscribers.clear()
        self._pattern_subscribers.clear()
        self._agent_keys.clear()
        self._namespace_metrics.clear()

    async def clear_async(self) -> None:
        """Thread-safe async version of clear."""
        async with self._lock:
            self.clear()

    def snapshot(self) -> dict[str, Any]:
        """Get a snapshot of all current non-expired data."""
        self._cleanup_expired_inline()
        return {k: e.value for k, e in self._store.items()}

    @property
    def size(self) -> int:
        """Number of entries (including possibly expired ones)."""
        return len(self._store)

    # =========================================================================
    # Notification
    # =========================================================================

    def _notify(self, key: str, value: Any, owner: str) -> None:
        """Notify subscribers of a change."""
        # Key-specific subscribers
        for _, callback in self._subscribers.get(key, []):
            try:
                callback(key, value, owner)
            except Exception:
                pass

        # Global subscribers
        for _, callback in self._global_subscribers:
            try:
                callback(key, value, owner)
            except Exception:
                pass

        # Pattern subscribers
        for _, pattern, callback in self._pattern_subscribers:
            try:
                if fnmatch.fnmatch(key, pattern):
                    callback(key, value, owner)
            except Exception:
                pass

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    @staticmethod
    def _extract_namespace(key: str) -> str:
        """Extract namespace from a key (part before first separator)."""
        idx = key.find(NAMESPACE_SEPARATOR)
        if idx >= 0:
            return key[:idx]
        return "__global__"

    def _get_or_create_metrics(self, namespace: str) -> NamespaceMetrics:
        """Get or create metrics for a namespace."""
        if namespace not in self._namespace_metrics:
            self._namespace_metrics[namespace] = NamespaceMetrics()
        return self._namespace_metrics[namespace]
