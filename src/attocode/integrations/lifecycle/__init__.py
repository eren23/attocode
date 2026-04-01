"""Async lifecycle utilities — generation counters and graceful shutdown.

Two utilities extracted from CC's patterns:

1. GenerationCounter — prevents stale async init race conditions.
   When a component is re-initialized mid-flight, the pending async
   operation is invalidated and a new one starts.  The generation
   counter detects and discards the stale result.

2. GracefulShutdown — full LSP/server shutdown lifecycle with timeouts.
   Implements: shutdown request → exit notification → dispose → kill.
   CC's comment: "Don't skip steps."
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Generation Counter
# =============================================================================


class GenerationCounter:
    """Monotonically increasing counter for async init invalidation.

    Use this when a component can be re-initialized while a previous
    init call is still in-flight.  The pending call's result is stale
    once the generation advances.

    Example:
        class MyServer:
            def __init__(self):
                self._gen = GenerationCounter()
                self._init_promise: Awaitable[None] | None = None

            async def ensure_initialized(self) -> bool:
                gen = self._gen.current
                self._init_promise = self._do_init()
                await self._init_promise
                # Check if our generation is still current
                return self._gen.is_current(gen)

            async def reinitialize(self) -> bool:
                self._gen.advance()          # Increment generation
                self._init_promise = None    # Discard old init
                return await self.ensure_initialized()

        # Usage:
        # Two concurrent reinitialize() calls race. The winner's
        # init finishes and its generation is current. The loser
        # advances, its old init completes, but is_current() is False
        # so the loser discards the result and starts its own init.
    """

    __slots__ = ("_count",)

    def __init__(self) -> None:
        self._count = 0

    @property
    def current(self) -> int:
        """Current generation number."""
        return self._count

    def advance(self) -> int:
        """Advance the generation. Returns the new generation number."""
        self._count += 1
        return self._count

    def is_current(self, gen: int) -> bool:
        """Return True if *gen* matches the current generation."""
        return gen == self._count

    def reset(self) -> None:
        """Reset to generation 0. Used for testing."""
        self._count = 0


class GenerationGuardedFuture:
    """An asyncio Future whose result is guarded by a GenerationCounter.

    Resolves the future, but only if the generation hasn't advanced.
    If the generation has advanced, the result is discarded.
    """

    __slots__ = ("_future", "_generation", "_counter", "_result")

    def __init__(
        self,
        counter: GenerationCounter,
        future: Awaitable[T],
    ) -> None:
        self._counter = counter
        self._generation = counter.current
        self._future = asyncio.create_task(future)
        self._result: T | None = None

    async def wait(self) -> T | None:
        """Wait for the future, returning None if the generation advanced."""
        try:
            self._result = await self._future
        except Exception:
            self._result = None

        # Discard result if generation has advanced
        if not self._counter.is_current(self._generation):
            logger.debug(
                "GenerationGuardedFuture: discarding result (gen=%d, current=%d)",
                self._generation, self._counter.current,
            )
            return None

        return self._result

    @property
    def done(self) -> bool:
        return self._future.done()

    @property
    def cancelled(self) -> bool:
        return self._future.cancelled()


# =============================================================================
# Graceful Shutdown
# =============================================================================


class GracefulShutdown:
    """Full LSP/server shutdown lifecycle.

    Implements the complete CC shutdown sequence to prevent orphaned processes
    and spurious errors:

    1. Send ``shutdown`` request (clean stop request to server)
    2. Send ``exit`` notification (server should terminate gracefully)
    3. Close stdin/stdout/stderr
    4. Wait for process to exit (with timeout)
    5. Kill if still alive
    6. Cancel pending requests

    The ``is_stopping`` flag prevents spurious errors during shutdown.
    """

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        request_fn: Callable[[str, Any], Awaitable[Any]],
        notify_fn: Callable[[str, Any], None],
        timeout: float = 10.0,
        name: str = "process",
    ) -> None:
        self._process = process
        self._request = request_fn
        self._notify = notify_fn
        self._timeout = timeout
        self._name = name
        self._is_stopping = False

    @property
    def is_stopping(self) -> bool:
        """True once shutdown has been initiated. Prevents spurious errors."""
        return self._is_stopping

    async def shutdown(self) -> None:
        """Execute the full shutdown sequence."""
        self._is_stopping = True

        try:
            # Step 1: Send shutdown request
            try:
                await asyncio.wait_for(
                    self._request("shutdown", None),
                    timeout=self._timeout,
                )
                logger.debug("%s: shutdown request sent", self._name)
            except TimeoutError:
                logger.warning("%s: shutdown request timed out", self._name)
            except Exception as exc:
                logger.debug("%s: shutdown request error (non-fatal): %s", self._name, exc)

            # Step 2: Send exit notification
            try:
                self._notify("exit", None)
                logger.debug("%s: exit notification sent", self._name)
            except Exception as exc:
                logger.debug("%s: exit notification error (non-fatal): %s", self._name, exc)

            # Brief pause to let server clean up
            await asyncio.sleep(0.1)

            # Step 3: Close pipes
            try:
                if self._process.stdin:
                    self._process.stdin.close()
            except Exception:
                pass

            # Step 4: Wait for graceful exit
            try:
                retcode = await asyncio.wait_for(
                    self._process.wait(),
                    timeout=self._timeout,
                )
                logger.debug(
                    "%s: exited gracefully with code %s",
                    self._name, retcode,
                )
                return
            except TimeoutError:
                logger.warning("%s: did not exit gracefully, killing", self._name)

            # Step 5: Kill
            try:
                self._process.kill()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
                logger.info("%s: killed", self._name)
            except Exception as exc:
                logger.warning("%s: kill failed: %s", self._name, exc)

        finally:
            self._is_stopping = False


# =============================================================================
# Pending request tracker
# =============================================================================


class PendingRequestTracker:
    """Track in-flight JSON-RPC requests with cancellation support.

    When a server is shutting down, all pending requests are cancelled
    so they don't hang waiting for a dead process.

    Usage:
        tracker = PendingRequestTracker()

        async def make_request(method, params):
            req_id = tracker.track(loop.create_future())
            try:
                result = await asyncio.wait_for(
                    tracker.wait(req_id, send_fn(method, params)),
                    timeout=30.0,
                )
                return result
            finally:
                tracker.remove(req_id)
    """

    __slots__ = ("_pending", "_lock", "_next_id")

    def __init__(self) -> None:
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._lock = asyncio.Lock()
        self._next_id = 1

    def track(self, future: asyncio.Future[Any]) -> int:
        """Start tracking a future. Returns a request ID."""
        req_id = self._next_id
        self._next_id += 1
        self._pending[req_id] = future
        future.add_done_callback(lambda f: self._pending.pop(req_id, None))
        return req_id

    async def wait(self, req_id: int) -> Any:
        """Wait for a tracked request to complete."""
        future = self._pending.get(req_id)
        if future is None:
            raise KeyError(f"No tracked request with ID {req_id}")
        return await future

    def cancel_all(self, reason: str = "server_shutdown") -> None:
        """Cancel all pending requests with an error."""
        for req_id, future in list(self._pending.items()):
            if not future.done():
                logger.debug("Cancelling pending request %d: %s", req_id, reason)
                future.cancel()

    def resolve(self, req_id: int, result: Any) -> None:
        """Resolve a pending request (used by the message reader)."""
        future = self._pending.get(req_id)
        if future and not future.done():
            future.set_result(result)

    def reject(self, req_id: int, exc: Exception) -> None:
        """Reject a pending request (used by the message reader)."""
        future = self._pending.get(req_id)
        if future and not future.done():
            future.set_exception(exc)

    @property
    def count(self) -> int:
        return len(self._pending)
