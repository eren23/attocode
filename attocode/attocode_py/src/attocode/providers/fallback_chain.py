"""Provider fallback chain with circuit breaker integration.

Tries providers in order, falling back to the next on failure.
Each provider is wrapped with a circuit breaker for fast failure
detection.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from attocode.errors import ProviderError
from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    Message,
    MessageWithStructuredContent,
)


@dataclass(slots=True)
class FallbackAttempt:
    """Record of a fallback attempt."""

    provider_name: str
    success: bool
    duration_ms: float
    error: str | None = None
    timestamp: float = 0.0


@dataclass(slots=True)
class FallbackStats:
    """Statistics for the fallback chain."""

    total_calls: int = 0
    primary_successes: int = 0
    fallback_successes: int = 0
    total_failures: int = 0
    attempts: list[FallbackAttempt] = field(default_factory=list)

    @property
    def fallback_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.fallback_successes / self.total_calls


class ProviderFallbackChain:
    """Try providers in order, falling back on failure.

    Integrates with circuit breakers to skip providers that are
    known to be down. Supports priority ordering and health-based
    reordering.
    """

    def __init__(
        self,
        providers: list[Any],
        *,
        circuit_breakers: dict[str, Any] | None = None,
        on_fallback: Any = None,
    ) -> None:
        """Initialize fallback chain.

        Args:
            providers: Ordered list of LLMProvider instances.
            circuit_breakers: Map of provider name -> CircuitBreaker.
            on_fallback: Callback(provider_name, error) on fallback.
        """
        if not providers:
            raise ValueError("At least one provider is required")
        self._providers = list(providers)
        self._circuit_breakers = circuit_breakers or {}
        self._on_fallback = on_fallback
        self._stats = FallbackStats()

    @property
    def stats(self) -> FallbackStats:
        return self._stats

    @property
    def name(self) -> str:
        names = [getattr(p, "name", "?") for p in self._providers]
        return f"fallback({' > '.join(names)})"

    async def chat(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> ChatResponse:
        """Call providers in order until one succeeds.

        Raises ProviderError if all providers fail.
        """
        self._stats.total_calls += 1
        errors: list[str] = []

        for i, provider in enumerate(self._providers):
            provider_name = getattr(provider, "name", f"provider_{i}")

            # Check circuit breaker
            cb = self._circuit_breakers.get(provider_name)
            if cb and hasattr(cb, "is_open") and cb.is_open:
                errors.append(f"{provider_name}: circuit breaker open")
                continue

            start = time.monotonic()
            try:
                response = await provider.chat(messages, options)
                duration_ms = (time.monotonic() - start) * 1000

                # Record success in circuit breaker
                if cb and hasattr(cb, "record_success"):
                    cb.record_success()

                self._stats.attempts.append(FallbackAttempt(
                    provider_name=provider_name,
                    success=True,
                    duration_ms=duration_ms,
                    timestamp=time.time(),
                ))

                if i == 0:
                    self._stats.primary_successes += 1
                else:
                    self._stats.fallback_successes += 1

                return response

            except Exception as e:
                duration_ms = (time.monotonic() - start) * 1000
                error_msg = str(e)
                errors.append(f"{provider_name}: {error_msg}")

                # Record failure in circuit breaker
                if cb and hasattr(cb, "record_failure"):
                    cb.record_failure()

                self._stats.attempts.append(FallbackAttempt(
                    provider_name=provider_name,
                    success=False,
                    duration_ms=duration_ms,
                    error=error_msg,
                    timestamp=time.time(),
                ))

                # Notify fallback callback
                if self._on_fallback and i < len(self._providers) - 1:
                    try:
                        self._on_fallback(provider_name, error_msg)
                    except Exception:
                        pass

        # All providers failed
        self._stats.total_failures += 1
        raise ProviderError(
            f"All providers failed: {'; '.join(errors)}",
            provider="fallback_chain",
            retryable=False,
        )

    async def close(self) -> None:
        """Close all providers."""
        for provider in self._providers:
            if hasattr(provider, "close"):
                try:
                    await provider.close()
                except Exception:
                    pass

    def get_healthy_providers(self) -> list[str]:
        """Get names of providers not in open circuit breaker state."""
        healthy = []
        for i, provider in enumerate(self._providers):
            name = getattr(provider, "name", f"provider_{i}")
            cb = self._circuit_breakers.get(name)
            if not cb or not (hasattr(cb, "is_open") and cb.is_open):
                healthy.append(name)
        return healthy

    def reorder_by_health(self) -> None:
        """Reorder providers putting healthy ones first."""
        healthy_names = set(self.get_healthy_providers())

        def _sort_key(p: Any) -> int:
            name = getattr(p, "name", "")
            return 0 if name in healthy_names else 1

        self._providers.sort(key=_sort_key)
