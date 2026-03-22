"""Session API - save/load/list sessions and checkpoints.

Provides a high-level API for session management, wrapping the
lower-level SessionStore with convenience methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.types.agent import AgentMetrics
    from attocode.types.messages import Message


@dataclass(slots=True)
class SessionSummary:
    """Summary of a saved session."""

    session_id: str
    task: str
    status: str
    model: str
    created_at: float
    last_active: float
    total_tokens: int
    total_cost: float
    iterations: int
    message_count: int
    checkpoint_count: int


@dataclass(slots=True)
class SessionSnapshot:
    """Full snapshot for resuming a session."""

    session_id: str
    task: str
    messages: list[dict[str, Any]]
    metrics: dict[str, Any]
    goals: list[dict[str, Any]]
    pending_plan: dict[str, Any] | None
    model: str = ""
    iterations: int = 0
    metadata: dict[str, Any] | None = None


class SessionAPI:
    """High-level session management API.

    Wraps SessionStore for common operations:
    - save_session / load_session / list_sessions
    - create_checkpoint / load_checkpoint
    - resume_session
    """

    def __init__(self, session_dir: str | Path) -> None:
        self._session_dir = Path(session_dir)
        self._store: Any = None
        self._initialized = False

    async def _ensure_store(self) -> Any:
        """Lazy-initialize the session store."""
        if self._store is not None:
            return self._store

        from attocode.integrations.persistence.store import SessionStore

        db_path = self._session_dir / "sessions.db"
        self._store = SessionStore(db_path)
        await self._store.initialize()
        self._initialized = True
        return self._store

    async def close(self) -> None:
        """Close the session store."""
        if self._store is not None:
            await self._store.close()
            self._store = None
            self._initialized = False

    async def save_session(
        self,
        session_id: str,
        task: str,
        messages: list[Message | Any],
        metrics: AgentMetrics | None = None,
        *,
        model: str = "",
        status: str = "active",
        thread_manager: Any = None,
    ) -> None:
        """Save a session with its current messages as a checkpoint.

        Args:
            session_id: Unique session identifier.
            task: The session task description.
            messages: Conversation messages.
            metrics: Optional agent metrics.
            model: Model name.
            status: Session status.
            thread_manager: Optional ThreadManager to persist.
        """
        store = await self._ensure_store()

        # Check if session exists
        existing = await store.get_session(session_id)
        if existing is None:
            await store.create_session(session_id, task, model=model)

        # Build session metadata, preserving existing metadata
        metadata: dict[str, Any] = {}
        if existing and existing.metadata:
            metadata.update(existing.metadata)

        # Serialize thread manager state into metadata
        if thread_manager is not None:
            try:
                metadata["thread_manager"] = thread_manager.to_dict()
            except Exception:
                pass  # Don't fail the save if thread serialization fails

        # Update session status
        metrics_dict = {}
        if metrics:
            metrics_dict = {
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "total_tokens": metrics.total_tokens,
                "llm_calls": metrics.llm_calls,
                "tool_calls": metrics.tool_calls,
                "estimated_cost": metrics.estimated_cost,
            }

        await store.update_session(
            session_id,
            status=status,
            total_tokens=metrics.total_tokens if metrics else None,
            total_cost=metrics.estimated_cost if metrics else None,
            metadata=metadata if metadata else None,
        )

        # Save checkpoint
        serialized_messages = [_serialize_message(m) for m in messages]
        await store.save_checkpoint(session_id, serialized_messages, metrics_dict)

    async def load_session(self, session_id: str) -> SessionSnapshot | None:
        """Load a session snapshot for resuming.

        If the session metadata contains thread_manager state, it is
        included in the snapshot's metadata field so the caller can
        restore the ThreadManager via ``ThreadManager.from_dict()``.
        """
        store = await self._ensure_store()
        result = await store.resume_session(session_id)
        if result is None:
            return None

        session_data = result["session"]
        metadata = session_data.get("metadata") or {}

        return SessionSnapshot(
            session_id=session_data["id"],
            task=session_data["task"],
            messages=result["messages"],
            metrics=result["metrics"],
            goals=result["goals"],
            pending_plan=result["pending_plan"],
            model=session_data.get("model", ""),
            iterations=session_data.get("iterations", 0),
            metadata=metadata if metadata else None,
        )

    async def list_sessions(
        self,
        *,
        limit: int = 20,
        status: str | None = None,
    ) -> list[SessionSummary]:
        """List saved sessions."""
        store = await self._ensure_store()
        recent = await store.list_recent_sessions(limit=limit)

        summaries = []
        for r in recent:
            if status and r.get("status") != status:
                continue
            summaries.append(SessionSummary(
                session_id=r["id"],
                task=r["goal"],
                status=r["status"],
                model=r.get("model", ""),
                created_at=r["created_at"],
                last_active=r["last_active"],
                total_tokens=r.get("total_tokens", 0),
                total_cost=r.get("total_cost", 0.0),
                iterations=r.get("iterations", 0),
                message_count=r.get("message_count", 0),
                checkpoint_count=r.get("checkpoint_count", 0),
            ))
        return summaries

    async def create_checkpoint(
        self,
        session_id: str,
        messages: list[Message | Any],
        metrics: AgentMetrics | None = None,
    ) -> int:
        """Create a checkpoint for an existing session."""
        store = await self._ensure_store()
        serialized = [_serialize_message(m) for m in messages]
        metrics_dict = {}
        if metrics:
            metrics_dict = {
                "total_tokens": metrics.total_tokens,
                "estimated_cost": metrics.estimated_cost,
                "llm_calls": metrics.llm_calls,
                "tool_calls": metrics.tool_calls,
            }
        return await store.save_checkpoint(session_id, serialized, metrics_dict)

    async def delete_session(self, session_id: str) -> None:
        """Delete a session and all its data."""
        store = await self._ensure_store()
        await store.delete_session(session_id)


def _serialize_message(msg: Any) -> dict[str, Any]:
    """Serialize a message to a dict for storage."""
    if isinstance(msg, dict):
        return msg
    result: dict[str, Any] = {
        "role": getattr(msg, "role", "user"),
    }
    content = getattr(msg, "content", "")
    if content:
        result["content"] = str(content)
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "name": tc.name,
                "arguments": tc.arguments,
            }
            for tc in tool_calls
        ]
    tool_call_id = getattr(msg, "tool_call_id", None)
    if tool_call_id:
        result["tool_call_id"] = tool_call_id
    return result
