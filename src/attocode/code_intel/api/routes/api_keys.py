"""API key management endpoints (service mode only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.api_keys import generate_api_key
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session
from attocode.code_intel.db.models import ApiKey, OrgMembership

router = APIRouter(prefix="/api/v1/orgs/{org_id}/api-keys", tags=["api-keys"])


class CreateKeyRequest(BaseModel):
    name: str
    scopes: list[str] = []
    expires_in_days: int | None = None


class KeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    created_at: str
    expires_at: str | None = None
    plaintext_key: str | None = None  # Only set on creation


class KeyListResponse(BaseModel):
    keys: list[KeyResponse]
    total: int = 0
    limit: int = 20
    offset: int = 0
    has_more: bool = False


async def _require_org_admin(
    org_id: uuid.UUID, auth: AuthContext, session: AsyncSession
) -> None:
    """Verify user is admin+ in the org."""
    if not auth.user_id:
        raise HTTPException(status_code=403, detail="Authentication required")
    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == auth.user_id,
            OrgMembership.role.in_(["owner", "admin"]),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.post("", response_model=KeyResponse)
async def create_api_key(
    org_id: uuid.UUID,
    req: CreateKeyRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> KeyResponse:
    """Create a new API key. The plaintext key is shown only once."""
    await _require_org_admin(org_id, auth, session)

    plaintext, key_hash, key_prefix = generate_api_key()

    expires_at = None
    if req.expires_in_days:
        from datetime import datetime, timedelta, timezone

        expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_in_days)

    api_key = ApiKey(
        org_id=org_id,
        user_id=auth.user_id,
        name=req.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=req.scopes,
        expires_at=expires_at,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    from attocode.code_intel.audit import log_event

    await log_event(session, org_id, "api_key.created", user_id=auth.user_id, detail={"key_name": req.name, "key_prefix": key_prefix})

    return KeyResponse(
        id=str(api_key.id),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        scopes=list(api_key.scopes),
        created_at=api_key.created_at.isoformat(),
        expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
        plaintext_key=plaintext,
    )


@router.get("", response_model=KeyListResponse)
async def list_api_keys(
    org_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> KeyListResponse:
    """List API keys (prefix + metadata only, no secrets)."""
    await _require_org_admin(org_id, auth, session)

    count_result = await session.execute(
        select(func.count()).select_from(
            select(ApiKey).where(ApiKey.org_id == org_id).subquery()
        )
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(ApiKey).where(ApiKey.org_id == org_id)
        .offset(offset).limit(limit)
    )
    keys = []
    for k in result.scalars():
        keys.append(KeyResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=list(k.scopes),
            created_at=k.created_at.isoformat(),
            expires_at=k.expires_at.isoformat() if k.expires_at else None,
        ))
    return KeyListResponse(
        keys=keys, total=total, limit=limit, offset=offset,
        has_more=(offset + limit < total),
    )


@router.delete("/{key_id}")
async def revoke_api_key(
    org_id: uuid.UUID,
    key_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Revoke (delete) an API key."""
    await _require_org_admin(org_id, auth, session)

    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == org_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    await session.delete(api_key)

    from attocode.code_intel.audit import log_event

    await log_event(session, org_id, "api_key.revoked", user_id=auth.user_id, detail={"key_id": str(key_id), "key_name": api_key.name})

    await session.commit()
    return {"detail": "API key revoked"}
