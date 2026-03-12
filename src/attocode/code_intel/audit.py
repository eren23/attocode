"""Audit event logging utility — writes to DB and publishes via Redis."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def log_event(
    session: AsyncSession,
    org_id: uuid.UUID,
    event_type: str,
    *,
    repo_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> None:
    """Log an audit event to DB and publish to Redis for real-time streaming.

    Args:
        session: Active DB session (caller should commit).
        org_id: Organization ID.
        event_type: Event type string (e.g. "org.created", "api_key.revoked").
        repo_id: Optional repository ID.
        user_id: Optional user ID who performed the action.
        detail: Optional JSON-serializable detail dict.
    """
    from attocode.code_intel.db.models import AuditEvent

    event = AuditEvent(
        org_id=org_id,
        repo_id=repo_id,
        user_id=user_id,
        event_type=event_type,
        detail=detail or {},
    )
    session.add(event)

    # Also publish to Redis for real-time WebSocket streaming
    try:
        from attocode.code_intel.pubsub import publish_event

        channel_id = str(repo_id) if repo_id else str(org_id)
        await publish_event(channel_id, f"audit.{event_type}", {
            "org_id": str(org_id),
            "repo_id": str(repo_id) if repo_id else None,
            "user_id": str(user_id) if user_id else None,
            "event_type": event_type,
            "detail": detail or {},
        })
    except Exception:
        # Don't fail the main operation if Redis publish fails
        logger.debug("Failed to publish audit event to Redis", exc_info=True)
