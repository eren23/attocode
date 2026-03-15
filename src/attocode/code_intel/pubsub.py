"""Redis Streams — persistent event publishing and subscription for real-time updates.

Uses Redis Streams (XADD/XREAD) instead of ephemeral PubSub so that clients
that disconnect can resume from their last-seen event ID. Stream entries are
auto-trimmed to keep memory bounded.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# Max entries per stream before auto-trimming (MAXLEN ~)
_MAX_STREAM_LEN = 10_000


async def publish_event(repo_id: str, event_type: str, payload: dict) -> str | None:
    """Publish an event to the repo's stream. Returns the stream entry ID, or None on error.

    Fire-and-forget semantics — never raises.
    """
    try:
        from attocode.code_intel.redis import get_redis

        redis = await get_redis()
        stream_key = f"repo:{repo_id}:stream"
        message = json.dumps({"type": event_type, "payload": payload})
        entry_id = await redis.xadd(
            stream_key,
            {"event": message},
            maxlen=_MAX_STREAM_LEN,
            approximate=True,
        )
        return entry_id
    except Exception:
        logger.warning("Failed to publish event %s for repo %s", event_type, repo_id, exc_info=True)
        return None


async def subscribe(
    repo_id: str,
    last_event_id: str = "$",
    block_ms: int = 5000,
) -> AsyncGenerator[dict, None]:
    """Subscribe to events for a repository using Redis Streams.

    Yields event dicts. If last_event_id is provided, replays all events
    after that ID before switching to live mode.

    Args:
        repo_id: Repository ID to subscribe to.
        last_event_id: Resume from this event ID. "$" = new events only.
            "0" = replay all available events.
        block_ms: How long to block waiting for new events (milliseconds).
    """
    from attocode.code_intel.redis import get_redis

    redis = await get_redis()
    stream_key = f"repo:{repo_id}:stream"
    cursor = last_event_id

    try:
        while True:
            # XREAD blocks for up to block_ms waiting for new entries
            results = await redis.xread(
                {stream_key: cursor},
                count=100,
                block=block_ms,
            )

            if not results:
                # Timeout — no new events, yield control and retry
                continue

            for _stream_name, entries in results:
                for entry_id, fields in entries:
                    cursor = entry_id
                    event_data = fields.get("event") or fields.get(b"event")
                    if event_data is None:
                        continue
                    if isinstance(event_data, bytes):
                        event_data = event_data.decode("utf-8")
                    try:
                        data = json.loads(event_data)
                        # Include the stream entry ID so clients can resume
                        data["_stream_id"] = entry_id if isinstance(entry_id, str) else entry_id.decode("utf-8")
                        yield data
                    except (json.JSONDecodeError, TypeError):
                        continue
    except GeneratorExit:
        pass
    except Exception:
        logger.warning("Stream subscription ended for repo %s", repo_id, exc_info=True)


async def get_stream_info(repo_id: str) -> dict:
    """Get info about the repo's event stream (length, first/last entry IDs)."""
    try:
        from attocode.code_intel.redis import get_redis

        redis = await get_redis()
        stream_key = f"repo:{repo_id}:stream"
        info = await redis.xinfo_stream(stream_key)
        return {
            "length": info.get("length", 0),
            "first_entry": info.get("first-entry", [None])[0] if info.get("first-entry") else None,
            "last_entry": info.get("last-entry", [None])[0] if info.get("last-entry") else None,
        }
    except Exception:
        return {"length": 0, "first_entry": None, "last_entry": None}
