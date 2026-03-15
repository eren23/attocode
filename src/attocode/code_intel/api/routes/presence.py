"""Presence tracking REST endpoints (service mode only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext

router = APIRouter(prefix="/api/v2/repos/{repo_id}", tags=["presence"])


class PresenceEntryResponse(BaseModel):
    user_id: str
    user_name: str
    file: str
    session_id: str
    timestamp: float


@router.get("/presence", response_model=list[PresenceEntryResponse])
async def get_repo_presence(
    repo_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
) -> list[PresenceEntryResponse]:
    """Get current viewers of a repository (REST fallback for non-WebSocket clients)."""
    from attocode.code_intel.presence import get_presence

    entries = await get_presence(str(repo_id))
    return [
        PresenceEntryResponse(
            user_id=e.user_id,
            user_name=e.user_name,
            file=e.file,
            session_id=e.session_id,
            timestamp=e.timestamp,
        )
        for e in entries
    ]
