"""Retry utilities using tenacity."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")


def is_retryable(exc: BaseException) -> bool:
    """Check if an exception is retryable."""
    # Import here to avoid circular imports
    from attocode.errors import ProviderError

    if isinstance(exc, ProviderError):
        return exc.retryable
    # Network errors are retryable
    if isinstance(exc, (ConnectionError, TimeoutError, asyncio.TimeoutError)):
        return True
    return False


def with_retry(
    *,
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    multiplier: float = 2.0,
    on_retry: Callable[[RetryCallState], None] | None = None,
) -> Any:
    """Create a tenacity retry decorator for async functions.

    Args:
        max_attempts: Maximum number of retry attempts.
        min_wait: Minimum wait time between retries (seconds).
        max_wait: Maximum wait time between retries (seconds).
        multiplier: Exponential backoff multiplier.
        on_retry: Optional callback invoked on each retry.
    """
    kwargs: dict[str, Any] = {
        "stop": stop_after_attempt(max_attempts),
        "wait": wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
        "retry": retry_if_exception(is_retryable),
        "reraise": True,
    }
    if on_retry:
        kwargs["before_sleep"] = on_retry

    return retry(**kwargs)


async def retry_async(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    **kwargs: Any,
) -> T:
    """Retry an async function with exponential backoff.

    Args:
        fn: Async function to retry.
        *args: Positional arguments for fn.
        max_attempts: Maximum attempts.
        min_wait: Minimum wait seconds.
        max_wait: Maximum wait seconds.
        **kwargs: Keyword arguments for fn.
    """

    @with_retry(max_attempts=max_attempts, min_wait=min_wait, max_wait=max_wait)
    async def _wrapped() -> T:
        return await fn(*args, **kwargs)

    return await _wrapped()
