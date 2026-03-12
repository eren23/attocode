"""WebSocket endpoints for real-time event streaming + presence (service mode only)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


@router.websocket("/ws/repos/{repo_id}/events")
async def repo_events(
    websocket: WebSocket,
    repo_id: uuid.UUID,
    token: str = Query(""),
) -> None:
    """Stream real-time events for a repository with bidirectional presence support.

    Authenticate via query parameter `token` (JWT).

    Outgoing events: index.started, index.progress, index.completed, index.failed,
                     presence.joined, presence.left, presence.file_changed.

    Incoming messages:
        {"type": "presence.update", "file": "src/main.py"}
        {"type": "presence.heartbeat"}
    """
    # Validate auth
    user_id = ""
    user_name = ""
    if token:
        from attocode.code_intel.api.auth.jwt import decode_token

        payload = decode_token(token)
        if payload is None:
            await websocket.close(code=4001, reason="Invalid token")
            return
        user_id = payload.get("sub", "")
        user_name = payload.get("name", user_id)
    else:
        # Allow unauthenticated in development
        from attocode.code_intel.api.deps import get_config

        config = get_config()
        if config.api_key or config.is_service_mode:
            await websocket.close(code=4001, reason="Token required")
            return

    await websocket.accept()
    session_id = str(uuid.uuid4())
    repo_id_str = str(repo_id)
    logger.info("WebSocket connected for repo %s (user=%s)", repo_id, user_id)

    async def _pubsub_reader() -> None:
        """Read events from Redis pubsub and forward to WebSocket."""
        from attocode.code_intel.pubsub import subscribe

        async for event in subscribe(repo_id_str):
            await websocket.send_json(event)

    async def _ws_reader() -> None:
        """Read incoming messages from WebSocket for presence updates."""
        while True:
            try:
                data = await websocket.receive_json()
            except (WebSocketDisconnect, RuntimeError):
                break

            msg_type = data.get("type", "")
            if msg_type == "presence.update":
                file_path = data.get("file", "")
                if user_id:
                    from attocode.code_intel.presence import set_presence

                    await set_presence(
                        repo_id_str, user_id, user_name, file_path, session_id,
                    )
            elif msg_type == "presence.heartbeat":
                if user_id:
                    from attocode.code_intel.presence import heartbeat

                    await heartbeat(repo_id_str, user_id, session_id)

    try:
        # Run both tasks concurrently
        pubsub_task = asyncio.create_task(_pubsub_reader())
        ws_task = asyncio.create_task(_ws_reader())
        done, pending = await asyncio.wait(
            [pubsub_task, ws_task], return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for repo %s", repo_id)
    except Exception as e:
        logger.warning("WebSocket error for repo %s: %s", repo_id, e)
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
    finally:
        # Clean up presence on disconnect
        if user_id:
            try:
                from attocode.code_intel.presence import remove_presence

                await remove_presence(repo_id_str, user_id, session_id)
            except Exception:
                logger.debug("Failed to remove presence on disconnect", exc_info=True)
