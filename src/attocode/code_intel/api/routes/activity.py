"""Activity feed / audit log endpoints (service mode only)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session

router = APIRouter(tags=["activity"])


# --- Response models ---


class ActivityEventResponse(BaseModel):
    id: str
    event_type: str
    org_id: str
    repo_id: str | None = None
    user_id: str | None = None
    detail: dict = {}
    created_at: str


class ActivityFeedResponse(BaseModel):
    events: list[ActivityEventResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


# --- Endpoints ---


@router.get("/api/v2/orgs/{org_id}/activity", response_model=ActivityFeedResponse)
async def get_org_activity(
    org_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    event_type: str = Query("", description="Filter by event type"),
    since: str = Query("", description="ISO datetime to filter events after"),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> ActivityFeedResponse:
    """Get organization activity feed (paginated)."""
    from attocode.code_intel.db.models import AuditEvent

    # Build query
    query = select(AuditEvent).where(AuditEvent.org_id == org_id)

    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(AuditEvent.created_at >= since_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format")

    # Count total
    count_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar() or 0

    # Fetch page
    result = await session.execute(
        query.order_by(AuditEvent.created_at.desc())
        .offset(offset).limit(limit)
    )

    events = []
    for event in result.scalars():
        events.append(ActivityEventResponse(
            id=str(event.id),
            event_type=event.event_type,
            org_id=str(event.org_id),
            repo_id=str(event.repo_id) if event.repo_id else None,
            user_id=str(event.user_id) if event.user_id else None,
            detail=event.detail or {},
            created_at=event.created_at.isoformat(),
        ))

    return ActivityFeedResponse(
        events=events, total=total, limit=limit, offset=offset,
        has_more=(offset + limit < total),
    )


@router.get("/api/v2/repos/{repo_id}/activity", response_model=ActivityFeedResponse)
async def get_repo_activity(
    repo_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    event_type: str = Query("", description="Filter by event type"),
    since: str = Query("", description="ISO datetime to filter events after"),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> ActivityFeedResponse:
    """Get repository activity feed (paginated)."""
    from attocode.code_intel.db.models import AuditEvent

    query = select(AuditEvent).where(AuditEvent.repo_id == repo_id)

    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(AuditEvent.created_at >= since_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format")

    count_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        query.order_by(AuditEvent.created_at.desc())
        .offset(offset).limit(limit)
    )

    events = []
    for event in result.scalars():
        events.append(ActivityEventResponse(
            id=str(event.id),
            event_type=event.event_type,
            org_id=str(event.org_id),
            repo_id=str(event.repo_id) if event.repo_id else None,
            user_id=str(event.user_id) if event.user_id else None,
            detail=event.detail or {},
            created_at=event.created_at.isoformat(),
        ))

    return ActivityFeedResponse(
        events=events, total=total, limit=limit, offset=offset,
        has_more=(offset + limit < total),
    )
