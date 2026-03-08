"""Checkpoint and file-change tracking operations.

Extracted from agent.py.  Provides standalone functions for creating
and restoring checkpoints and for tracking / undoing file changes.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.agent.agent import ProductionAgent

logger = logging.getLogger(__name__)


async def create_checkpoint(
    agent: ProductionAgent,
    label: str = "",
) -> dict[str, Any]:
    """Create a checkpoint of the current conversation state for later restore."""
    checkpoint_id = f"cp-{uuid.uuid4().hex[:8]}"
    timestamp = time.time()
    message_count = len(agent._ctx.messages) if agent._ctx else 0

    # Persist to session store if available
    if agent._ctx and hasattr(agent._ctx, "session_store") and agent._ctx.session_store:
        try:
            session_id = getattr(agent._ctx, "session_id", "")
            await agent._ctx.session_store.create_checkpoint(
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                label=label,
                messages=agent._ctx.messages,
            )
        except Exception:
            logger.debug("checkpoint_persist_failed", exc_info=True)

    return {
        "checkpoint_id": checkpoint_id,
        "label": label or f"Checkpoint at iteration {agent._ctx.iteration if agent._ctx else 0}",
        "message_count": message_count,
        "timestamp": timestamp,
    }


async def restore_checkpoint(
    agent: ProductionAgent,
    checkpoint_id: str,
) -> bool:
    """Restore conversation state from a previously created checkpoint."""
    if not agent._ctx:
        return False

    if not hasattr(agent._ctx, "session_store") or not agent._ctx.session_store:
        return False

    try:
        session_id = getattr(agent._ctx, "session_id", "")
        checkpoint_data = await agent._ctx.session_store.load_checkpoint(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
        )
        if checkpoint_data and "messages" in checkpoint_data:
            agent._ctx.messages.clear()
            agent._ctx.messages.extend(checkpoint_data["messages"])
            return True
    except Exception:
        logger.warning("checkpoint_restore_failed", exc_info=True)

    return False


def track_file_change(
    agent: ProductionAgent,
    path: str,
    action: str,
    content_before: str = "",
    content_after: str = "",
) -> None:
    """Record a file change for /diff review and /undo capability."""
    if agent._file_change_tracker is not None:
        try:
            agent._file_change_tracker.track_change(
                path=path,
                before_content=content_before,
                after_content=content_after,
                tool_name=action,
            )
        except Exception:
            logger.debug("file_change_track_failed", exc_info=True)


def undo_last_change(agent: ProductionAgent) -> dict[str, Any] | None:
    """Undo the most recent file change, restoring previous content."""
    if agent._file_change_tracker is None:
        return None
    try:
        result_msg = agent._file_change_tracker.undo_last_change()
        if not result_msg or result_msg == "No changes to undo.":
            return None
        return {
            "message": result_msg,
            "success": "restored" in result_msg.lower() or "undone" in result_msg.lower(),
        }
    except Exception:
        logger.debug("undo_failed", exc_info=True)
        return None
