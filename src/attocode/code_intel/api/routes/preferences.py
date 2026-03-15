"""User preferences endpoints (service mode only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session

router = APIRouter(prefix="/api/v2/me", tags=["preferences"])


class PreferencesResponse(BaseModel):
    preferences: dict


class PreferencesUpdateRequest(BaseModel):
    preferences: dict


# --- Endpoints ---


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> PreferencesResponse:
    """Get current user's preferences."""
    if not auth.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    from attocode.code_intel.db.models import UserPreference

    result = await session.execute(
        select(UserPreference).where(UserPreference.user_id == auth.user_id)
    )
    pref = result.scalar_one_or_none()
    return PreferencesResponse(preferences=pref.preferences if pref else {})


@router.put("/preferences", response_model=PreferencesResponse)
async def replace_preferences(
    req: PreferencesUpdateRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> PreferencesResponse:
    """Full replace of user preferences."""
    if not auth.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    from attocode.code_intel.db.models import UserPreference

    result = await session.execute(
        select(UserPreference).where(UserPreference.user_id == auth.user_id)
    )
    pref = result.scalar_one_or_none()

    if pref:
        pref.preferences = req.preferences
    else:
        pref = UserPreference(user_id=auth.user_id, preferences=req.preferences)
        session.add(pref)

    await session.commit()
    await session.refresh(pref)
    return PreferencesResponse(preferences=pref.preferences)


@router.patch("/preferences", response_model=PreferencesResponse)
async def merge_preferences(
    req: PreferencesUpdateRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> PreferencesResponse:
    """Merge update of user preferences (shallow merge)."""
    if not auth.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    from attocode.code_intel.db.models import UserPreference

    result = await session.execute(
        select(UserPreference).where(UserPreference.user_id == auth.user_id)
    )
    pref = result.scalar_one_or_none()

    if pref:
        merged = {**pref.preferences, **req.preferences}
        pref.preferences = merged
    else:
        pref = UserPreference(user_id=auth.user_id, preferences=req.preferences)
        session.add(pref)

    await session.commit()
    await session.refresh(pref)
    return PreferencesResponse(preferences=pref.preferences)
