"""Middleware for CORS, request logging, rate limiting, and metrics collection."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metrics Collector (module-level singleton)
# ---------------------------------------------------------------------------

_MAX_ENTRIES = 10_000


def _get_metrics_category(path: str) -> str:
    """Categorize request path into a metrics bucket.

    Returns one of: "search", "analysis", "graph", "auth", "notify", "health",
    "lsp", "learning", "files", "projects", "embeddings", "other".
    """
    if path in ("/health", "/ready") or path.startswith("/api/v1/metrics"):
        return "health"
    if path.startswith("/api/v1/auth") or path.startswith("/api/v1/register"):
        return "auth"
    if path.startswith("/api/v1/notify") or path.startswith("/api/v2/notify"):
        return "notify"
    if "/search" in path or "/semantic" in path or "/symbols" in path:
        return "search"
    if "/analysis" in path or "/impact" in path or "/hotspots" in path or "/cross-ref" in path:
        return "analysis"
    if "/graph" in path or "/dependencies" in path or "/deps" in path:
        return "graph"
    if "/lsp" in path:
        return "lsp"
    if "/learning" in path:
        return "learning"
    if "/files" in path:
        return "files"
    if "/projects" in path or "/repos" in path:
        return "projects"
    if "/embeddings" in path:
        return "embeddings"
    return "other"


class MetricsCollector:
    """Thread-safe, in-memory metrics collector using a ring buffer.

    Tracks request latencies, search statistics, and tool call metrics.
    All data is stored in-memory using ``collections.deque`` with a max
    size of 10,000 entries per category.
    """

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._lock = threading.Lock()
        self._max_entries = max_entries

        # Request metrics: deque of (path_category, method, status, duration_ms, timestamp)
        self._requests: deque[tuple[str, str, int, float, float]] = deque(maxlen=max_entries)

        # Search metrics: deque of (query, result_count, duration_ms, cache_hit, timestamp)
        self._searches: deque[tuple[str, int, float, bool, float]] = deque(maxlen=max_entries)

        # Tool call metrics: deque of (tool_name, duration_ms, success, timestamp)
        self._tool_calls: deque[tuple[str, float, bool, float]] = deque(maxlen=max_entries)

    # -- Recording methods ---------------------------------------------------

    def record_request(
        self, path: str, method: str, status: int, duration_ms: float
    ) -> None:
        """Record an HTTP request metric."""
        category = _get_metrics_category(path)
        with self._lock:
            self._requests.append((category, method, status, duration_ms, time.time()))

    def record_search(
        self, query: str, result_count: int, duration_ms: float, cache_hit: bool
    ) -> None:
        """Record a search query metric."""
        with self._lock:
            self._searches.append((query, result_count, duration_ms, cache_hit, time.time()))

    def record_tool_call(
        self, tool_name: str, duration_ms: float, success: bool
    ) -> None:
        """Record an MCP tool call metric."""
        with self._lock:
            self._tool_calls.append((tool_name, duration_ms, success, time.time()))

    # -- Percentile computation ----------------------------------------------

    @staticmethod
    def _compute_percentiles(values: list[float]) -> dict[str, float]:
        """Compute p50, p95, and p99 from a list of values.

        Returns dict with keys "p50", "p95", "p99". Returns all zeros if
        *values* is empty.
        """
        if not values:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        sorted_vals = sorted(values)
        n = len(sorted_vals)

        def _pct(p: float) -> float:
            idx = int(p / 100.0 * (n - 1))
            return sorted_vals[min(idx, n - 1)]

        return {
            "p50": round(_pct(50), 2),
            "p95": round(_pct(95), 2),
            "p99": round(_pct(99), 2),
        }

    # -- Aggregation ---------------------------------------------------------

    def get_metrics(self, fmt: str = "json") -> dict[str, Any] | str:
        """Return aggregated metrics.

        Args:
            fmt: ``"json"`` returns a dict, ``"prometheus"`` returns
                 Prometheus text exposition format.
        """
        with self._lock:
            requests = list(self._requests)
            searches = list(self._searches)
            tool_calls = list(self._tool_calls)

        # -- Request metrics -------------------------------------------------
        requests_by_category: dict[str, list[float]] = defaultdict(list)
        status_counts: dict[int, int] = defaultdict(int)
        total_requests = len(requests)

        for category, _method, status, duration_ms, _ts in requests:
            requests_by_category[category].append(duration_ms)
            status_counts[status] += 1

        request_latency: dict[str, dict[str, Any]] = {}
        for category, durations in requests_by_category.items():
            request_latency[category] = {
                "count": len(durations),
                "avg_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
                **self._compute_percentiles(durations),
            }

        # -- Search metrics --------------------------------------------------
        search_durations = [d for _, _, d, _, _ in searches]
        search_result_counts = [rc for _, rc, _, _, _ in searches]
        cache_hits = sum(1 for _, _, _, hit, _ in searches if hit)
        cache_misses = len(searches) - cache_hits

        search_metrics: dict[str, Any] = {
            "total": len(searches),
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_hit_rate": round(cache_hits / len(searches), 4) if searches else 0.0,
            "latency": self._compute_percentiles(search_durations),
            "avg_result_count": (
                round(sum(search_result_counts) / len(search_result_counts), 2)
                if search_result_counts
                else 0.0
            ),
        }

        # -- Tool call metrics -----------------------------------------------
        tools_by_name: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "success": 0, "failure": 0, "durations": []}
        )
        for tool_name, duration_ms, success, _ts in tool_calls:
            entry = tools_by_name[tool_name]
            entry["count"] += 1
            if success:
                entry["success"] += 1
            else:
                entry["failure"] += 1
            entry["durations"].append(duration_ms)

        tool_metrics: dict[str, dict[str, Any]] = {}
        for tool_name, data in tools_by_name.items():
            durations = data["durations"]
            tool_metrics[tool_name] = {
                "count": data["count"],
                "success": data["success"],
                "failure": data["failure"],
                "avg_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
                **self._compute_percentiles(durations),
            }

        result: dict[str, Any] = {
            "requests": {
                "total": total_requests,
                "by_category": request_latency,
                "by_status": dict(status_counts),
            },
            "search": search_metrics,
            "tools": tool_metrics,
        }

        if fmt == "prometheus":
            return self._format_prometheus(result)
        return result

    # -- Prometheus formatting -----------------------------------------------

    @staticmethod
    def _format_prometheus(metrics: dict[str, Any]) -> str:
        """Format metrics as Prometheus text exposition."""
        lines: list[str] = []

        # Request metrics
        lines.append("# HELP code_intel_requests_total Total HTTP requests")
        lines.append("# TYPE code_intel_requests_total counter")
        lines.append(f"code_intel_requests_total {metrics['requests']['total']}")

        for category, data in metrics["requests"]["by_category"].items():
            lines.append(f'code_intel_requests_by_category{{category="{category}"}} {data["count"]}')

        lines.append("")
        lines.append("# HELP code_intel_request_duration_ms Request latency in milliseconds")
        lines.append("# TYPE code_intel_request_duration_ms summary")
        for category, data in metrics["requests"]["by_category"].items():
            for pct in ("p50", "p95", "p99"):
                quantile = {"p50": "0.5", "p95": "0.95", "p99": "0.99"}[pct]
                lines.append(
                    f'code_intel_request_duration_ms{{category="{category}",quantile="{quantile}"}} {data[pct]}'
                )

        for status, count in metrics["requests"]["by_status"].items():
            lines.append(f'code_intel_requests_by_status{{status="{status}"}} {count}')

        # Search metrics
        lines.append("")
        lines.append("# HELP code_intel_search_total Total search queries")
        lines.append("# TYPE code_intel_search_total counter")
        lines.append(f"code_intel_search_total {metrics['search']['total']}")
        lines.append(f"code_intel_search_cache_hits {metrics['search']['cache_hits']}")
        lines.append(f"code_intel_search_cache_misses {metrics['search']['cache_misses']}")
        lines.append(f"code_intel_search_cache_hit_rate {metrics['search']['cache_hit_rate']}")

        lines.append("")
        lines.append("# HELP code_intel_search_duration_ms Search latency in milliseconds")
        lines.append("# TYPE code_intel_search_duration_ms summary")
        for pct in ("p50", "p95", "p99"):
            quantile = {"p50": "0.5", "p95": "0.95", "p99": "0.99"}[pct]
            lines.append(
                f'code_intel_search_duration_ms{{quantile="{quantile}"}} {metrics["search"]["latency"][pct]}'
            )

        # Tool metrics
        lines.append("")
        lines.append("# HELP code_intel_tool_calls_total Total MCP tool calls")
        lines.append("# TYPE code_intel_tool_calls_total counter")
        for tool_name, data in metrics["tools"].items():
            lines.append(f'code_intel_tool_calls_total{{tool="{tool_name}"}} {data["count"]}')
            lines.append(f'code_intel_tool_calls_success{{tool="{tool_name}"}} {data["success"]}')
            lines.append(f'code_intel_tool_calls_failure{{tool="{tool_name}"}} {data["failure"]}')
            for pct in ("p50", "p95", "p99"):
                quantile = {"p50": "0.5", "p95": "0.95", "p99": "0.99"}[pct]
                lines.append(
                    f'code_intel_tool_duration_ms{{tool="{tool_name}",quantile="{quantile}"}} {data[pct]}'
                )

        lines.append("")
        return "\n".join(lines)


# Module-level singleton
metrics_collector = MetricsCollector()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


def _get_category(path: str) -> str:
    """Categorize request path for tiered rate limiting.

    Returns: "auth" | "notify" | "query"
    """
    if path.startswith("/api/v1/auth") or path.startswith("/api/v1/register"):
        return "auth"
    if path.startswith("/api/v1/notify"):
        return "notify"
    return "query"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window rate limiter with tiered limits.

    Tiers:
    - auth endpoints: 30 RPM (brute-force prevention)
    - notify endpoints: 10x base (initial sync, watch)
    - query endpoints: base RPM (default 300)

    Keyed by org_id (from auth header) or client IP for unauthenticated requests.
    """

    def __init__(self, app, requests_per_minute: int = 300) -> None:
        super().__init__(app)
        # Read from env, fallback to constructor arg
        self.base_rpm = int(os.environ.get("ATTOCODE_RATE_LIMIT_RPM", str(requests_per_minute)))
        self._tier_multipliers = {
            "auth": 0.1,    # 30 RPM at base=300
            "notify": 10.0,  # 3000 RPM at base=300
            "query": 1.0,    # 300 RPM at base=300
        }
        self._windows: dict[str, list[float]] = defaultdict(list)

    def _get_rpm(self, category: str) -> int:
        mult = self._tier_multipliers.get(category, 1.0)
        return max(1, int(self.base_rpm * mult))

    def _get_key(self, request: Request, category: str) -> str:
        """Extract rate limit key from request, scoped by category."""
        # Try to extract org from auth header (best-effort, pre-auth)
        auth = request.headers.get("authorization", "")
        base = f"auth:{hash(auth)}" if auth else f"ip:{request.client.host if request.client else 'unknown'}"
        return f"{category}:{base}"

    def _check_and_record(self, key: str, now: float, rpm: int | None = None) -> tuple[bool, int, int]:
        """Check rate limit and record request.

        Returns (allowed, remaining, reset_seconds).
        """
        if rpm is None:
            rpm = self.base_rpm
        window = self._windows[key]
        cutoff = now - 60.0
        # Prune expired entries
        self._windows[key] = window = [t for t in window if t > cutoff]

        remaining = max(0, rpm - len(window))
        reset_seconds = int(cutoff + 60 - now) if window else 60

        if len(window) >= rpm:
            return False, 0, max(1, reset_seconds)

        window.append(now)
        return True, remaining - 1, max(1, reset_seconds)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip health endpoints
        if request.url.path in ("/health", "/ready"):
            return await call_next(request)

        category = _get_category(request.url.path)
        rpm = self._get_rpm(category)
        key = self._get_key(request, category)
        now = time.monotonic()
        allowed, remaining, reset_seconds = self._check_and_record(key, now, rpm)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "X-RateLimit-Limit": str(rpm),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_seconds),
                    "Retry-After": str(reset_seconds),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_seconds)
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request metrics via the module-level ``metrics_collector``."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        metrics_collector.record_request(
            path=request.url.path,
            method=request.method,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response
