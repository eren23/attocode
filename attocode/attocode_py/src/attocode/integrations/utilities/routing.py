"""LLM routing system with multiple strategies.

Routes LLM requests to appropriate providers based on
configurable strategies: cost, quality, latency, balanced, or rules.
Includes fallback chains and circuit breaker integration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RoutingStrategy(StrEnum):
    """Strategy for routing LLM requests."""

    COST = "cost"  # Minimize cost
    QUALITY = "quality"  # Maximize quality
    LATENCY = "latency"  # Minimize latency
    BALANCED = "balanced"  # Balance cost/quality/latency
    RULES = "rules"  # Rule-based routing


class CircuitState(StrEnum):
    """Circuit breaker state."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass(slots=True)
class ProviderStats:
    """Runtime statistics for a provider."""

    name: str
    total_calls: int = 0
    total_failures: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float = 0.0
    last_failure_time: float = 0.0
    circuit_state: CircuitState = CircuitState.CLOSED
    circuit_failure_count: int = 0
    circuit_open_until: float = 0.0

    @property
    def failure_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_failures / self.total_calls

    @property
    def is_available(self) -> bool:
        if self.circuit_state == CircuitState.OPEN:
            if time.time() > self.circuit_open_until:
                return True  # Allow half-open probe
            return False
        return True


@dataclass(slots=True)
class ProviderConfig:
    """Configuration for a routable provider."""

    name: str
    priority: int = 0  # Lower = higher priority
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    quality_score: float = 0.8  # 0.0-1.0
    avg_latency_ms: float = 500.0
    max_tokens: int = 200_000
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_thinking: bool = False
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RoutingDecision:
    """Result of a routing decision."""

    provider_name: str
    reason: str = ""
    fallback_chain: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RoutingRule:
    """A rule for rules-based routing."""

    condition: str  # 'model_contains', 'task_type', 'token_count_gt', 'cost_sensitive'
    value: str
    provider_name: str
    priority: int = 0


class RoutingManager:
    """Routes LLM requests to providers based on strategy.

    Supports multiple routing strategies, fallback chains,
    and circuit breaker patterns for resilient provider selection.
    """

    def __init__(
        self,
        strategy: RoutingStrategy = RoutingStrategy.BALANCED,
        *,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: float = 60.0,
    ) -> None:
        self._strategy = strategy
        self._providers: dict[str, ProviderConfig] = {}
        self._stats: dict[str, ProviderStats] = {}
        self._rules: list[RoutingRule] = []
        self._cb_threshold = circuit_breaker_threshold
        self._cb_timeout = circuit_breaker_timeout

    @property
    def strategy(self) -> RoutingStrategy:
        return self._strategy

    def set_strategy(self, strategy: RoutingStrategy | str) -> None:
        """Change the routing strategy."""
        if isinstance(strategy, str):
            strategy = RoutingStrategy(strategy)
        self._strategy = strategy

    def register_provider(self, config: ProviderConfig) -> None:
        """Register a provider for routing."""
        self._providers[config.name] = config
        if config.name not in self._stats:
            self._stats[config.name] = ProviderStats(name=config.name)

    def add_rule(self, rule: RoutingRule) -> None:
        """Add a routing rule (for rules-based strategy)."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)

    def route(
        self,
        *,
        model: str = "",
        task_type: str = "",
        estimated_tokens: int = 0,
        require_tools: bool = False,
        require_streaming: bool = False,
        require_thinking: bool = False,
    ) -> RoutingDecision:
        """Route a request to the best provider.

        Args:
            model: Requested model name.
            task_type: Type of task (planning, coding, review, etc.).
            estimated_tokens: Estimated total tokens for the request.
            require_tools: Whether tool use is needed.
            require_streaming: Whether streaming is needed.
            require_thinking: Whether extended thinking is needed.

        Returns:
            RoutingDecision with selected provider and fallback chain.
        """
        available = self._get_available_providers(
            require_tools=require_tools,
            require_streaming=require_streaming,
            require_thinking=require_thinking,
            min_tokens=estimated_tokens,
        )

        if not available:
            # No providers available, return first registered as last resort
            first = next(iter(self._providers), "")
            return RoutingDecision(
                provider_name=first,
                reason="No available providers, falling back to first registered",
            )

        if self._strategy == RoutingStrategy.RULES:
            decision = self._route_by_rules(available, model=model, task_type=task_type)
            if decision:
                return decision

        if self._strategy == RoutingStrategy.COST:
            return self._route_by_cost(available)
        if self._strategy == RoutingStrategy.QUALITY:
            return self._route_by_quality(available)
        if self._strategy == RoutingStrategy.LATENCY:
            return self._route_by_latency(available)

        return self._route_balanced(available)

    def record_success(self, provider_name: str, latency_ms: float, tokens: int, cost: float) -> None:
        """Record a successful call to a provider."""
        stats = self._stats.get(provider_name)
        if not stats:
            return
        stats.total_calls += 1
        stats.total_tokens += tokens
        stats.total_cost += cost
        # Rolling average
        alpha = 0.2
        stats.avg_latency_ms = (1 - alpha) * stats.avg_latency_ms + alpha * latency_ms

        # Reset circuit breaker on success
        if stats.circuit_state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            stats.circuit_state = CircuitState.CLOSED
            stats.circuit_failure_count = 0

    def record_failure(self, provider_name: str) -> None:
        """Record a failed call to a provider."""
        stats = self._stats.get(provider_name)
        if not stats:
            return
        stats.total_calls += 1
        stats.total_failures += 1
        stats.last_failure_time = time.time()
        stats.circuit_failure_count += 1

        # Trip circuit breaker if threshold exceeded
        if stats.circuit_failure_count >= self._cb_threshold:
            stats.circuit_state = CircuitState.OPEN
            stats.circuit_open_until = time.time() + self._cb_timeout

    def get_stats(self) -> dict[str, ProviderStats]:
        """Get all provider statistics."""
        return dict(self._stats)

    def _get_available_providers(
        self,
        *,
        require_tools: bool = False,
        require_streaming: bool = False,
        require_thinking: bool = False,
        min_tokens: int = 0,
    ) -> list[ProviderConfig]:
        """Filter providers by availability and capabilities."""
        result = []
        for name, config in self._providers.items():
            stats = self._stats.get(name)
            if stats and not stats.is_available:
                continue
            if require_tools and not config.supports_tools:
                continue
            if require_streaming and not config.supports_streaming:
                continue
            if require_thinking and not config.supports_thinking:
                continue
            if min_tokens and config.max_tokens < min_tokens:
                continue
            result.append(config)
        return result

    def _route_by_cost(self, providers: list[ProviderConfig]) -> RoutingDecision:
        """Select cheapest provider."""
        sorted_p = sorted(providers, key=lambda p: p.cost_per_1k_input + p.cost_per_1k_output)
        return RoutingDecision(
            provider_name=sorted_p[0].name,
            reason="Lowest cost",
            fallback_chain=[p.name for p in sorted_p[1:]],
        )

    def _route_by_quality(self, providers: list[ProviderConfig]) -> RoutingDecision:
        """Select highest quality provider."""
        sorted_p = sorted(providers, key=lambda p: -p.quality_score)
        return RoutingDecision(
            provider_name=sorted_p[0].name,
            reason="Highest quality",
            fallback_chain=[p.name for p in sorted_p[1:]],
        )

    def _route_by_latency(self, providers: list[ProviderConfig]) -> RoutingDecision:
        """Select lowest latency provider."""
        sorted_p = sorted(providers, key=lambda p: p.avg_latency_ms)
        return RoutingDecision(
            provider_name=sorted_p[0].name,
            reason="Lowest latency",
            fallback_chain=[p.name for p in sorted_p[1:]],
        )

    def _route_balanced(self, providers: list[ProviderConfig]) -> RoutingDecision:
        """Balance cost, quality, and latency."""

        def score(p: ProviderConfig) -> float:
            cost_score = 1.0 - min((p.cost_per_1k_input + p.cost_per_1k_output) / 0.1, 1.0)
            quality_score = p.quality_score
            latency_score = 1.0 - min(p.avg_latency_ms / 5000.0, 1.0)
            # Check runtime stats for actual performance
            stats = self._stats.get(p.name)
            reliability = 1.0 - (stats.failure_rate if stats else 0.0)
            return 0.3 * cost_score + 0.35 * quality_score + 0.15 * latency_score + 0.2 * reliability

        sorted_p = sorted(providers, key=score, reverse=True)
        return RoutingDecision(
            provider_name=sorted_p[0].name,
            reason="Balanced (cost/quality/latency/reliability)",
            fallback_chain=[p.name for p in sorted_p[1:]],
        )

    def _route_by_rules(
        self,
        providers: list[ProviderConfig],
        *,
        model: str = "",
        task_type: str = "",
    ) -> RoutingDecision | None:
        """Apply rule-based routing."""
        provider_names = {p.name for p in providers}

        for rule in self._rules:
            if rule.provider_name not in provider_names:
                continue

            matched = False
            if rule.condition == "model_contains" and model:
                matched = rule.value.lower() in model.lower()
            elif rule.condition == "task_type" and task_type:
                matched = rule.value.lower() == task_type.lower()

            if matched:
                others = [p.name for p in providers if p.name != rule.provider_name]
                return RoutingDecision(
                    provider_name=rule.provider_name,
                    reason=f"Rule: {rule.condition}={rule.value}",
                    fallback_chain=others,
                )

        return None
