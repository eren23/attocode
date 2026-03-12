"""Redis PubSub — event publishing and subscription for real-time updates."""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


async def publish_event(repo_id: str, event_type: str, payload: dict) -> None:
    """Publish an event to the repo's channel."""
    from attocode.code_intel.redis import get_redis

    redis = await get_redis()
    channel = f"repo:{repo_id}:events"
    message = json.dumps({"type": event_type, "payload": payload})
    await redis.publish(channel, message)


async def subscribe(repo_id: str) -> AsyncGenerator[dict, None]:
    """Subscribe to events for a repository. Yields event dicts."""
    from attocode.code_intel.redis import get_redis

    redis = await get_redis()
    channel = f"repo:{repo_id}:events"
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    yield data
                except (json.JSONDecodeError, TypeError):
                    continue
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
