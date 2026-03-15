"""Middleware for CORS, request logging, and rate limiting."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)


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
