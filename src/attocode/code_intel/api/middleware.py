"""Middleware for CORS, request logging, and rate limiting."""

from __future__ import annotations

import logging
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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window rate limiter.

    Keyed by org_id (from auth header) or client IP for unauthenticated requests.
    """

    def __init__(self, app, requests_per_minute: int = 60) -> None:
        super().__init__(app)
        self.rpm = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    def _get_key(self, request: Request) -> str:
        """Extract rate limit key from request."""
        # Try to extract org from auth header (best-effort, pre-auth)
        auth = request.headers.get("authorization", "")
        if auth:
            return f"auth:{hash(auth)}"
        # Fallback to client IP
        client = request.client
        return f"ip:{client.host}" if client else "ip:unknown"

    def _check_and_record(self, key: str, now: float) -> tuple[bool, int, int]:
        """Check rate limit and record request.

        Returns (allowed, remaining, reset_seconds).
        """
        window = self._windows[key]
        cutoff = now - 60.0
        # Prune expired entries
        self._windows[key] = window = [t for t in window if t > cutoff]

        remaining = max(0, self.rpm - len(window))
        reset_seconds = int(cutoff + 60 - now) if window else 60

        if len(window) >= self.rpm:
            return False, 0, max(1, reset_seconds)

        window.append(now)
        return True, remaining - 1, max(1, reset_seconds)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip health endpoints
        if request.url.path in ("/health", "/ready"):
            return await call_next(request)

        key = self._get_key(request)
        now = time.monotonic()
        allowed, remaining, reset_seconds = self._check_and_record(key, now)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "X-RateLimit-Limit": str(self.rpm),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_seconds),
                    "Retry-After": str(reset_seconds),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_seconds)
        return response
