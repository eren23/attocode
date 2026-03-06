"""Resilient HTTP fetch with retry, timeout, and circuit breaker.

Wraps httpx with retry logic, exponential backoff, rate limiting,
and circuit breaker pattern for reliable HTTP requests to LLM APIs.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FetchResult:
    """Result of a resilient fetch operation."""

    status_code: int
    body: bytes
    headers: dict[str, str]
    success: bool
    error: str = ""
    retries: int = 0
    duration_ms: float = 0.0
    provider_name: str = ""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    @property
    def json(self) -> Any:
        import json
        return json.loads(self.body)


@dataclass(slots=True)
class FetchConfig:
    """Configuration for resilient fetch."""

    timeout: float = 120.0
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    retry_on_status: frozenset[int] = frozenset({429, 500, 502, 503, 504})
    rate_limit_delay: float = 0.0  # Extra delay between requests (0 = disabled)


class CircuitBreakerState:
    """Simple circuit breaker for a provider."""

    def __init__(self, threshold: int = 5, timeout: float = 60.0) -> None:
        self.threshold = threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.is_open = False

    def record_success(self) -> None:
        self.failure_count = 0
        self.is_open = False

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.threshold:
            self.is_open = True

    def should_allow(self) -> bool:
        if not self.is_open:
            return True
        # Half-open: allow after timeout period
        if time.time() - self.last_failure_time > self.timeout:
            return True
        return False


class ResilientFetch:
    """HTTP client with retry, timeout, and circuit breaker.

    Wraps httpx.AsyncClient with resilience patterns for
    reliable communication with LLM provider APIs.
    """

    def __init__(self, config: FetchConfig | None = None) -> None:
        self._config = config or FetchConfig()
        self._circuit_breakers: dict[str, CircuitBreakerState] = {}
        self._client: Any = None  # Lazy httpx.AsyncClient

    async def _get_client(self) -> Any:
        """Get or create the httpx client."""
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(timeout=self._config.timeout)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_circuit_breaker(self, provider: str) -> CircuitBreakerState:
        """Get or create a circuit breaker for a provider."""
        if provider not in self._circuit_breakers:
            self._circuit_breakers[provider] = CircuitBreakerState()
        return self._circuit_breakers[provider]

    async def fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | str | None = None,
        json_body: Any = None,
        provider: str = "",
    ) -> FetchResult:
        """Perform a resilient HTTP fetch.

        Args:
            method: HTTP method (GET, POST, etc.).
            url: Request URL.
            headers: Request headers.
            body: Raw body bytes or string.
            json_body: JSON body (mutually exclusive with body).
            provider: Provider name for circuit breaker tracking.

        Returns:
            FetchResult with response data.
        """
        # Circuit breaker check
        if provider:
            cb = self._get_circuit_breaker(provider)
            if not cb.should_allow():
                return FetchResult(
                    status_code=0,
                    body=b"",
                    headers={},
                    success=False,
                    error=f"Circuit breaker open for provider '{provider}'",
                    provider_name=provider,
                )

        client = await self._get_client()
        last_error = ""
        retries = 0

        for attempt in range(self._config.max_retries + 1):
            start = time.time()
            try:
                # Rate limiting delay
                if self._config.rate_limit_delay > 0 and attempt > 0:
                    await asyncio.sleep(self._config.rate_limit_delay)

                # Build request kwargs
                kwargs: dict[str, Any] = {"headers": headers or {}}
                if json_body is not None:
                    kwargs["json"] = json_body
                elif body is not None:
                    kwargs["content"] = body

                response = await client.request(method, url, **kwargs)
                duration_ms = (time.time() - start) * 1000

                # Success
                if response.status_code < 400:
                    if provider:
                        self._get_circuit_breaker(provider).record_success()
                    return FetchResult(
                        status_code=response.status_code,
                        body=response.content,
                        headers=dict(response.headers),
                        success=True,
                        retries=retries,
                        duration_ms=duration_ms,
                        provider_name=provider,
                    )

                # Check if we should retry this status code
                if response.status_code in self._config.retry_on_status:
                    last_error = f"HTTP {response.status_code}"
                    retries += 1

                    # Rate limit: check Retry-After header
                    retry_after = response.headers.get("retry-after", "")
                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except ValueError:
                            delay = self._calculate_backoff(attempt)
                    else:
                        delay = self._calculate_backoff(attempt)

                    await asyncio.sleep(delay)
                    continue

                # Non-retryable error
                if provider:
                    self._get_circuit_breaker(provider).record_failure()

                return FetchResult(
                    status_code=response.status_code,
                    body=response.content,
                    headers=dict(response.headers),
                    success=False,
                    error=f"HTTP {response.status_code}",
                    retries=retries,
                    duration_ms=duration_ms,
                    provider_name=provider,
                )

            except Exception as e:
                duration_ms = (time.time() - start) * 1000
                last_error = str(e)
                retries += 1

                if attempt < self._config.max_retries:
                    delay = self._calculate_backoff(attempt)
                    await asyncio.sleep(delay)
                    continue

                if provider:
                    self._get_circuit_breaker(provider).record_failure()

                return FetchResult(
                    status_code=0,
                    body=b"",
                    headers={},
                    success=False,
                    error=last_error,
                    retries=retries,
                    duration_ms=duration_ms,
                    provider_name=provider,
                )

        # Should not reach here, but just in case
        return FetchResult(
            status_code=0,
            body=b"",
            headers={},
            success=False,
            error=f"Max retries exceeded: {last_error}",
            retries=retries,
            provider_name=provider,
        )

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay."""
        delay = self._config.retry_base_delay * (2 ** attempt)
        return min(delay, self._config.retry_max_delay)
