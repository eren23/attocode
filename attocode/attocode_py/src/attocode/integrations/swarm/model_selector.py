"""Swarm model selector — auto-detect workers and health tracking."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from attocode.integrations.swarm.types import (
    ModelHealthRecord,
    SwarmWorkerSpec,
    WorkerCapability,
    WorkerRole,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

FALLBACK_WORKERS: list[SwarmWorkerSpec] = [
    SwarmWorkerSpec(
        name="coder",
        model="mistralai/mistral-large-2512",
        capabilities=[WorkerCapability.CODE, WorkerCapability.TEST],
        context_window=262144,
        policy_profile="code-strict-bash",
        allowed_tools=["read_file", "write_file", "edit_file", "glob", "grep", "bash"],
    ),
    SwarmWorkerSpec(
        name="coder-alt",
        model="z-ai/glm-4.7-flash",
        capabilities=[WorkerCapability.CODE, WorkerCapability.TEST],
        context_window=202000,
        policy_profile="code-strict-bash",
        allowed_tools=["read_file", "write_file", "edit_file", "glob", "grep", "bash"],
    ),
    SwarmWorkerSpec(
        name="coder-alt2",
        model="allenai/olmo-3.1-32b-instruct",
        capabilities=[WorkerCapability.CODE, WorkerCapability.TEST],
        context_window=65536,
        policy_profile="code-strict-bash",
        allowed_tools=["read_file", "write_file", "edit_file", "glob", "grep", "bash"],
    ),
    SwarmWorkerSpec(
        name="researcher",
        model="moonshotai/kimi-k2.5-0127",
        capabilities=[WorkerCapability.RESEARCH, WorkerCapability.REVIEW],
        context_window=262144,
        policy_profile="research-safe",
        allowed_tools=["read_file", "list_files", "glob", "grep"],
    ),
    SwarmWorkerSpec(
        name="documenter",
        model="mistralai/ministral-14b-2512",
        capabilities=[WorkerCapability.DOCUMENT],
        context_window=262144,
        policy_profile="code-strict-bash",
        allowed_tools=["read_file", "write_file", "glob"],
    ),
]


# =============================================================================
# Options
# =============================================================================


@dataclass
class ModelSelectorOptions:
    """Options for auto-detecting worker models via OpenRouter."""

    api_key: str
    orchestrator_model: str
    min_context_window: int = 32768
    max_cost_per_million: float = 5.0
    preferred_models: list[str] | None = None
    paid_only: bool = False


# =============================================================================
# Role Assignment Helpers
# =============================================================================

# Maximum workers per role when auto-detecting
_MAX_CODERS = 3
_MAX_RESEARCHERS = 2
_MAX_DOCUMENTERS = 1


def _is_tools_capable(model_data: dict[str, Any]) -> bool:
    """Check if a model supports tool/function calling."""
    # OpenRouter models list supported features under 'supported_parameters'
    supported = model_data.get("supported_parameters", [])
    if isinstance(supported, list):
        return "tools" in supported or "tool_choice" in supported

    # Some models have an architecture.capabilities field
    arch = model_data.get("architecture", {})
    if isinstance(arch, dict):
        caps = arch.get("capabilities", [])
        if isinstance(caps, list) and "tool_use" in caps:
            return True

    # Fallback: assume large context models support tools
    return False


def _get_combined_cost(model_data: dict[str, Any]) -> float:
    """Get combined prompt + completion cost per million tokens."""
    pricing = model_data.get("pricing", {})
    if not isinstance(pricing, dict):
        return float("inf")
    try:
        prompt_cost = float(pricing.get("prompt", "0"))
        completion_cost = float(pricing.get("completion", "0"))
        # OpenRouter pricing is per-token; convert to per-million
        return (prompt_cost + completion_cost) * 1_000_000
    except (ValueError, TypeError):
        return float("inf")


def _assign_role(
    model_data: dict[str, Any],
    coders: int,
    researchers: int,
    documenters: int,
) -> tuple[str, list[WorkerCapability], str, list[str] | None]:
    """Assign a role based on current counts.

    Returns (name, capabilities, policy_profile, allowed_tools).
    """
    model_id = model_data.get("id", "unknown")
    lower_id = model_id.lower()

    # Heuristic role detection from model name/description
    desc = (model_data.get("description", "") or "").lower()
    is_code_model = any(
        kw in lower_id or kw in desc
        for kw in ("code", "coder", "starcoder", "codellama", "deepseek-coder")
    )

    if coders < _MAX_CODERS and (is_code_model or researchers >= _MAX_RESEARCHERS):
        idx = coders
        return (
            f"coder-{idx}" if idx > 0 else "coder",
            [WorkerCapability.CODE, WorkerCapability.TEST],
            "code-strict-bash",
            ["read_file", "write_file", "edit_file", "glob", "grep", "bash"],
        )

    if researchers < _MAX_RESEARCHERS:
        idx = researchers
        return (
            f"researcher-{idx}" if idx > 0 else "researcher",
            [WorkerCapability.RESEARCH, WorkerCapability.REVIEW],
            "research-safe",
            ["read_file", "list_files", "glob", "grep"],
        )

    if documenters < _MAX_DOCUMENTERS:
        return (
            "documenter",
            [WorkerCapability.DOCUMENT],
            "code-strict-bash",
            ["read_file", "write_file", "glob"],
        )

    # Overflow: additional coder
    return (
        f"coder-{coders}",
        [WorkerCapability.CODE, WorkerCapability.TEST],
        "code-strict-bash",
        ["read_file", "write_file", "edit_file", "glob", "grep", "bash"],
    )


# =============================================================================
# Auto-Detection
# =============================================================================


async def auto_detect_worker_models(
    options: ModelSelectorOptions,
) -> list[SwarmWorkerSpec]:
    """Auto-detect available worker models from OpenRouter API.

    Queries ``GET https://openrouter.ai/api/v1/models``, filters by
    context_length, cost, and tool support, then assigns roles.

    Returns :data:`FALLBACK_WORKERS` on any error.
    """
    try:
        import aiohttp
    except ImportError:
        logger.warning("aiohttp not available; using fallback workers")
        return get_fallback_workers(options.orchestrator_model)

    url = "https://openrouter.ai/api/v1/models"
    headers: dict[str, str] = {}
    if options.api_key:
        headers["Authorization"] = f"Bearer {options.api_key}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning(
                        "OpenRouter API returned %d; using fallback workers", resp.status
                    )
                    return get_fallback_workers(options.orchestrator_model)
                data = await resp.json()
    except Exception:
        logger.warning("Failed to query OpenRouter API; using fallback workers", exc_info=True)
        return get_fallback_workers(options.orchestrator_model)

    models_list = data.get("data", [])
    if not isinstance(models_list, list) or not models_list:
        return get_fallback_workers(options.orchestrator_model)

    # Filter candidates
    candidates: list[dict[str, Any]] = []
    for m in models_list:
        if not isinstance(m, dict):
            continue

        model_id = m.get("id", "")

        # Skip orchestrator model (it's reserved for review)
        if model_id == options.orchestrator_model:
            continue

        # Context window check
        ctx = m.get("context_length", 0)
        if not isinstance(ctx, (int, float)) or ctx < options.min_context_window:
            continue

        # Cost check
        cost = _get_combined_cost(m)
        if cost > options.max_cost_per_million:
            continue

        # Paid-only filter
        if options.paid_only:
            pricing = m.get("pricing", {})
            if isinstance(pricing, dict):
                prompt_cost = float(pricing.get("prompt", "0") or "0")
                if prompt_cost == 0:
                    continue

        # Tool support (prefer models with tool support)
        tools_capable = _is_tools_capable(m)

        # Preferred model bonus
        is_preferred = False
        if options.preferred_models:
            is_preferred = model_id in options.preferred_models

        candidates.append({
            **m,
            "_cost": cost,
            "_tools": tools_capable,
            "_preferred": is_preferred,
        })

    if not candidates:
        return get_fallback_workers(options.orchestrator_model)

    # Sort: preferred first, then tools-capable, then cheapest
    candidates.sort(
        key=lambda m: (
            not m["_preferred"],
            not m["_tools"],
            m["_cost"],
        )
    )

    # Assign roles
    workers: list[SwarmWorkerSpec] = []
    coders = 0
    researchers = 0
    documenters = 0
    max_workers = _MAX_CODERS + _MAX_RESEARCHERS + _MAX_DOCUMENTERS

    for m in candidates:
        if len(workers) >= max_workers:
            break

        model_id = m.get("id", "")
        ctx = int(m.get("context_length", 128000))

        name, capabilities, policy_profile, allowed_tools = _assign_role(
            m, coders, researchers, documenters
        )

        # Update counters
        if WorkerCapability.CODE in capabilities:
            coders += 1
        elif WorkerCapability.RESEARCH in capabilities:
            researchers += 1
        elif WorkerCapability.DOCUMENT in capabilities:
            documenters += 1

        workers.append(SwarmWorkerSpec(
            name=name,
            model=model_id,
            capabilities=capabilities,
            context_window=ctx,
            policy_profile=policy_profile,
            allowed_tools=allowed_tools,
        ))

    # Always add a reviewer using the orchestrator model
    workers.append(SwarmWorkerSpec(
        name="reviewer",
        model=options.orchestrator_model,
        capabilities=[WorkerCapability.REVIEW],
        context_window=128_000,
        role=WorkerRole.EXECUTOR,
        policy_profile="research-safe",
        allowed_tools=["read_file", "list_files", "glob", "grep"],
    ))

    return workers if workers else get_fallback_workers(options.orchestrator_model)


# =============================================================================
# Fallback Workers
# =============================================================================


def get_fallback_workers(orchestrator_model: str) -> list[SwarmWorkerSpec]:
    """Return fallback workers plus a reviewer using the orchestrator model.

    Uses :data:`FALLBACK_WORKERS` as the base set and appends a reviewer
    spec that uses the provided orchestrator model.
    """
    workers = list(FALLBACK_WORKERS)
    workers.append(SwarmWorkerSpec(
        name="reviewer",
        model=orchestrator_model,
        capabilities=[WorkerCapability.REVIEW],
        context_window=128_000,
        role=WorkerRole.EXECUTOR,
        policy_profile="research-safe",
        allowed_tools=["read_file", "list_files", "glob", "grep"],
    ))
    return workers


# =============================================================================
# Worker Selection
# =============================================================================


def select_worker_for_capability(
    workers: list[SwarmWorkerSpec],
    capability: WorkerCapability,
    task_index: int = 0,
    health_tracker: ModelHealthTracker | None = None,
) -> SwarmWorkerSpec | None:
    """Select a worker that matches the given capability.

    Without a health tracker, uses round-robin among matching workers.
    With a health tracker, sorts by: healthy > lower hollow_rate >
    higher success_rate, then round-robin within the top tier.

    Capability fallbacks: ``test`` -> ``code``, ``write`` -> ``code``.
    If no match at all, returns ``workers[0]`` if available.
    """
    if not workers:
        return None

    # Find matching workers
    matching = [w for w in workers if capability in w.capabilities]

    # Fallback capabilities
    if not matching:
        fallback_map: dict[WorkerCapability, WorkerCapability] = {
            WorkerCapability.TEST: WorkerCapability.CODE,
            WorkerCapability.WRITE: WorkerCapability.CODE,
        }
        fallback_cap = fallback_map.get(capability)
        if fallback_cap:
            matching = [w for w in workers if fallback_cap in w.capabilities]

    # Last resort: any worker
    if not matching:
        return workers[0] if workers else None

    if len(matching) == 1:
        return matching[0]

    # With health tracking: sort by health metrics
    if health_tracker is not None:
        matching = _sort_by_health(matching, health_tracker)

    # Round-robin within the matching set
    idx = task_index % len(matching)
    return matching[idx]


def _sort_by_health(
    workers: list[SwarmWorkerSpec],
    tracker: ModelHealthTracker,
) -> list[SwarmWorkerSpec]:
    """Sort workers by health: healthy first, then low hollow rate,
    then high success rate."""
    def sort_key(w: SwarmWorkerSpec) -> tuple[int, float, float]:
        healthy = 0 if tracker.is_healthy(w.model) else 1
        hollow_rate = tracker.get_hollow_rate(w.model)
        # Negate success rate so higher comes first
        neg_success = -tracker.get_success_rate(w.model)
        return (healthy, hollow_rate, neg_success)

    return sorted(workers, key=sort_key)


def select_alternative_model(
    workers: list[SwarmWorkerSpec],
    failed_model: str,
    capability: WorkerCapability,
    health_tracker: ModelHealthTracker | None = None,
) -> SwarmWorkerSpec | None:
    """Find an alternative worker after a model failure.

    Selects a different model with the same capability, preferring
    healthy models. For ``write`` capability, also tries ``code``
    workers as fallback.
    """
    if not workers:
        return None

    # Find candidates: different model + matching capability
    candidates = [
        w for w in workers
        if w.model != failed_model and capability in w.capabilities
    ]

    # For write tasks, also consider code workers
    if not candidates and capability == WorkerCapability.WRITE:
        candidates = [
            w for w in workers
            if w.model != failed_model and WorkerCapability.CODE in w.capabilities
        ]

    if not candidates:
        # Any worker with a different model
        candidates = [w for w in workers if w.model != failed_model]

    if not candidates:
        return None

    # Prefer healthy models
    if health_tracker is not None:
        healthy_candidates = [c for c in candidates if health_tracker.is_healthy(c.model)]
        if healthy_candidates:
            return healthy_candidates[0]

    return candidates[0]


# =============================================================================
# Model Health Tracker
# =============================================================================

# Exponential moving average weight: new=0.3, history=0.7
_EMA_NEW_WEIGHT = 0.3
_EMA_OLD_WEIGHT = 0.7

# Rate limit window (seconds) for burst detection
_RATE_LIMIT_WINDOW_S = 60.0
_RATE_LIMIT_BURST_THRESHOLD = 2

# Failure rate threshold for marking unhealthy
_FAILURE_RATE_THRESHOLD = 0.5
_MIN_TOTAL_FOR_FAILURE_CHECK = 3

# Quality rejection threshold
_QUALITY_REJECTION_THRESHOLD = 3


class ModelHealthTracker:
    """Tracks per-model health with exponential moving average latency.

    Monitors successes, failures, rate limits, quality rejections,
    and hollow completions. Uses an EMA (alpha=0.3) for latency
    smoothing and rate-limit burst detection within a 60-second window.
    """

    def __init__(self) -> None:
        self._records: dict[str, ModelHealthRecord] = {}
        self._recent_rate_limits: dict[str, list[float]] = {}
        self._hollow_counts: dict[str, int] = {}

    def _ensure_record(self, model: str) -> ModelHealthRecord:
        """Get or create a health record for a model."""
        if model not in self._records:
            self._records[model] = ModelHealthRecord(model=model)
        return self._records[model]

    def _recompute_success_rate(self, record: ModelHealthRecord) -> None:
        """Recompute the success rate for a record."""
        total = record.successes + record.failures
        record.success_rate = record.successes / total if total > 0 else 1.0

    # ----- Recording Methods -----

    def record_success(self, model: str, latency_ms: float) -> None:
        """Record a successful model call.

        Increments successes, updates EMA latency (0.7 old / 0.3 new),
        sets healthy=True, and recomputes success_rate.
        """
        record = self._ensure_record(model)
        record.successes += 1

        # EMA latency
        if record.average_latency_ms == 0.0:
            record.average_latency_ms = latency_ms
        else:
            record.average_latency_ms = (
                _EMA_OLD_WEIGHT * record.average_latency_ms
                + _EMA_NEW_WEIGHT * latency_ms
            )

        record.healthy = True
        self._recompute_success_rate(record)

    def record_failure(self, model: str, error_type: str) -> None:
        """Record a model call failure.

        For 429/402 errors, increments rate_limits and marks unhealthy
        if 2+ rate limits occur within 60 seconds. For all errors,
        marks unhealthy if failure rate exceeds 50% with at least 3
        total calls.
        """
        record = self._ensure_record(model)
        record.failures += 1

        # Rate limit handling (429 too many requests, 402 payment required)
        if error_type in ("429", "402", "rate_limit", "rate-limit"):
            record.rate_limits += 1
            record.last_rate_limit = time.time()

            # Track recent rate limits for burst detection
            now = time.time()
            if model not in self._recent_rate_limits:
                self._recent_rate_limits[model] = []
            self._recent_rate_limits[model].append(now)

            # Prune old entries outside the window
            cutoff = now - _RATE_LIMIT_WINDOW_S
            self._recent_rate_limits[model] = [
                t for t in self._recent_rate_limits[model] if t > cutoff
            ]

            # Mark unhealthy on burst
            if len(self._recent_rate_limits[model]) >= _RATE_LIMIT_BURST_THRESHOLD:
                record.healthy = False

        # General failure rate check
        total = record.successes + record.failures
        if total >= _MIN_TOTAL_FOR_FAILURE_CHECK:
            failure_rate = record.failures / total
            if failure_rate > _FAILURE_RATE_THRESHOLD:
                record.healthy = False

        self._recompute_success_rate(record)

    def mark_unhealthy(self, model: str) -> None:
        """Force a model to be marked as unhealthy."""
        record = self._ensure_record(model)
        record.healthy = False

    def record_quality_rejection(self, model: str, score: int) -> None:
        """Record a quality gate rejection.

        Undoes a premature success count (if any), increments failures
        and quality_rejections. Marks unhealthy at 3 rejections or
        >50% failure rate.
        """
        record = self._ensure_record(model)

        # Undo premature success: the task was initially counted as
        # success but quality gate rejected it
        if record.successes > 0:
            record.successes -= 1
        record.failures += 1
        record.quality_rejections += 1

        # Unhealthy thresholds
        if record.quality_rejections >= _QUALITY_REJECTION_THRESHOLD:
            record.healthy = False

        total = record.successes + record.failures
        if total >= _MIN_TOTAL_FOR_FAILURE_CHECK:
            failure_rate = record.failures / total
            if failure_rate > _FAILURE_RATE_THRESHOLD:
                record.healthy = False

        self._recompute_success_rate(record)

    def record_hollow(self, model: str) -> None:
        """Record a hollow completion and also record it as a failure."""
        self._hollow_counts[model] = self._hollow_counts.get(model, 0) + 1
        self.record_failure(model, "hollow")

    # ----- Query Methods -----

    def get_hollow_rate(self, model: str) -> float:
        """Get the hollow completion rate for a model.

        Returns ``hollow_count / (successes + failures)``, or ``0.0``
        if the model is unknown or has no calls.
        """
        hollow = self._hollow_counts.get(model, 0)
        if hollow == 0:
            return 0.0

        record = self._records.get(model)
        if record is None:
            return 0.0

        total = record.successes + record.failures
        return hollow / total if total > 0 else 0.0

    def get_hollow_count(self, model: str) -> int:
        """Get the total hollow completion count for a model."""
        return self._hollow_counts.get(model, 0)

    def is_healthy(self, model: str) -> bool:
        """Check if a model is considered healthy.

        Returns ``True`` for unknown models (optimistic default).
        """
        record = self._records.get(model)
        if record is None:
            return True
        return record.healthy

    def get_success_rate(self, model: str) -> float:
        """Get the success rate for a model.

        Returns ``1.0`` for unknown models (optimistic default).
        """
        record = self._records.get(model)
        if record is None:
            return 1.0
        return record.success_rate

    def get_healthy(self, models: list[str]) -> list[str]:
        """Filter a list of model IDs to only healthy ones."""
        return [m for m in models if self.is_healthy(m)]

    def get_all_records(self) -> list[ModelHealthRecord]:
        """Return all tracked health records."""
        return list(self._records.values())

    def restore(self, records: list[ModelHealthRecord]) -> None:
        """Restore health records from a checkpoint.

        Replaces current state with the provided records. Hollow
        counts and recent rate limit tracking are reset.
        """
        self._records.clear()
        self._recent_rate_limits.clear()
        self._hollow_counts.clear()

        for record in records:
            self._records[record.model] = ModelHealthRecord(
                model=record.model,
                successes=record.successes,
                failures=record.failures,
                rate_limits=record.rate_limits,
                last_rate_limit=record.last_rate_limit,
                average_latency_ms=record.average_latency_ms,
                healthy=record.healthy,
                quality_rejections=record.quality_rejections,
                success_rate=record.success_rate,
            )
