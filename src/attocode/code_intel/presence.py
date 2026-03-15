"""Redis-backed presence tracking for collaboration."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Presence entries expire after 120 seconds without heartbeat
_PRESENCE_TTL = 120


@dataclass(slots=True)
class PresenceEntry:
    user_id: str
    user_name: str
    file: str
    session_id: str
    timestamp: float


async def set_presence(
    repo_id: str,
    user_id: str,
    user_name: str,
    file_path: str,
    session_id: str,
) -> None:
    """Set or update presence for a user in a repo."""
    from attocode.code_intel.redis import get_redis

    redis = await get_redis()
    key = f"presence:{repo_id}"
    field = f"{user_id}:{session_id}"

    # Check for file change to publish event
    old_raw = await redis.hget(key, field)
    old_file = ""
    if old_raw:
        try:
            old_data = json.loads(old_raw)
            old_file = old_data.get("file", "")
        except (json.JSONDecodeError, TypeError):
            pass

    value = json.dumps({
        "user_id": user_id,
        "user_name": user_name,
        "file": file_path,
        "session_id": session_id,
        "timestamp": time.time(),
    })
    await redis.hset(key, field, value)

    # Set TTL on the hash key (renews on each update)
    await redis.expire(key, _PRESENCE_TTL)

    # Publish presence events
    from attocode.code_intel.pubsub import publish_event

    if not old_raw:
        await publish_event(repo_id, "presence.joined", {
            "user_id": user_id, "user_name": user_name, "file": file_path,
        })
    elif old_file != file_path:
        await publish_event(repo_id, "presence.file_changed", {
            "user_id": user_id, "user_name": user_name,
            "from_file": old_file, "to_file": file_path,
        })


async def remove_presence(
    repo_id: str,
    user_id: str,
    session_id: str,
) -> None:
    """Remove presence for a user session."""
    from attocode.code_intel.redis import get_redis

    redis = await get_redis()
    key = f"presence:{repo_id}"
    field = f"{user_id}:{session_id}"

    # Get user name before removing
    raw = await redis.hget(key, field)
    user_name = ""
    if raw:
        try:
            data = json.loads(raw)
            user_name = data.get("user_name", "")
        except (json.JSONDecodeError, TypeError):
            pass

    await redis.hdel(key, field)

    from attocode.code_intel.pubsub import publish_event

    await publish_event(repo_id, "presence.left", {
        "user_id": user_id, "user_name": user_name,
    })


async def get_presence(repo_id: str) -> list[PresenceEntry]:
    """Get all active presence entries for a repo."""
    from attocode.code_intel.redis import get_redis

    redis = await get_redis()
    key = f"presence:{repo_id}"

    all_entries = await redis.hgetall(key)
    now = time.time()
    result = []

    for field, raw in all_entries.items():
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        # Filter out stale entries
        ts = data.get("timestamp", 0)
        if now - ts > _PRESENCE_TTL:
            await redis.hdel(key, field)
            continue

        result.append(PresenceEntry(
            user_id=data["user_id"],
            user_name=data.get("user_name", ""),
            file=data.get("file", ""),
            session_id=data.get("session_id", ""),
            timestamp=ts,
        ))

    return result


async def heartbeat(
    repo_id: str,
    user_id: str,
    session_id: str,
) -> None:
    """Renew presence TTL via heartbeat."""
    from attocode.code_intel.redis import get_redis

    redis = await get_redis()
    key = f"presence:{repo_id}"
    field = f"{user_id}:{session_id}"

    raw = await redis.hget(key, field)
    if raw:
        try:
            data = json.loads(raw)
            data["timestamp"] = time.time()
            await redis.hset(key, field, json.dumps(data))
            await redis.expire(key, _PRESENCE_TTL)
        except (json.JSONDecodeError, TypeError):
            pass
