"""Redis connection management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_redis: Redis | None = None


async def get_redis() -> Redis:
    """Get or create the Redis connection singleton."""
    global _redis
    if _redis is not None:
        return _redis

    from attocode.code_intel.api.deps import get_config

    config = get_config()
    if not config.redis_url:
        raise RuntimeError("REDIS_URL not configured")

    from redis.asyncio import Redis as AsyncRedis

    _redis = AsyncRedis.from_url(config.redis_url, decode_responses=True)
    logger.info("Redis connection initialized")
    return _redis


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed")


async def health_check() -> bool:
    """Check if Redis is reachable."""
    try:
        r = await get_redis()
        await r.ping()
        return True
    except Exception:
        return False
