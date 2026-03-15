"""Authentication package — unified auth resolution for local and service modes."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException

from attocode.code_intel.api.deps import get_config

if TYPE_CHECKING:
    from attocode.code_intel.api.auth.context import AuthContext

# In-memory revocation cache (jti → expiry_monotonic)
_revocation_cache: dict[str, float] = {}
_REVOCATION_CACHE_TTL = 30  # seconds
_revocation_cache_refreshed_at: float = 0.0


async def verify_api_key(authorization: str | None = Header(None)) -> None:
    """Legacy API key verification (local mode).

    If ATTOCODE_API_KEY is not set, all requests are allowed (local mode).
    """
    config = get_config()
    if not config.api_key:
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    if token != config.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


async def verify_auth(authorization: str | None = Header(None)) -> None:
    """Router-level auth guard — delegates to resolve_auth, discards AuthContext."""
    await resolve_auth(authorization)


async def _is_token_revoked(jti: str) -> bool:
    """Check if a JWT's jti is in the revocation blocklist.

    Uses a 30-second in-memory cache to avoid per-request DB hits.
    """
    global _revocation_cache_refreshed_at

    now = time.monotonic()

    # Refresh cache if stale
    if now - _revocation_cache_refreshed_at > _REVOCATION_CACHE_TTL:
        try:
            from attocode.code_intel.db.engine import get_session
            from attocode.code_intel.db.models import RevokedToken

            from sqlalchemy import select

            async for session in get_session():
                result = await session.execute(select(RevokedToken.jti))
                _revocation_cache.clear()
                for row in result:
                    _revocation_cache[row[0]] = now + _REVOCATION_CACHE_TTL
                _revocation_cache_refreshed_at = now
                break
        except Exception:
            pass  # If DB is unavailable, use stale cache

    return jti in _revocation_cache


async def resolve_auth(authorization: str | None = Header(None)) -> AuthContext:
    """Unified auth resolver — delegates to legacy or service path based on config.

    In local mode: verifies static API key, returns a stub AuthContext.
    In service mode: tries JWT first, then service API key resolution.
    """
    from attocode.code_intel.api.auth.context import AuthContext

    config = get_config()

    if not config.is_service_mode:
        # Local mode — delegate to legacy check
        await verify_api_key(authorization)
        return AuthContext(auth_method="legacy")

    # Service mode — try JWT, then API key
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authorization header required")

    # Try JWT first
    from attocode.code_intel.api.auth.jwt import decode_token

    payload = decode_token(token)
    if payload is not None:
        import uuid

        # Check revocation blocklist
        jti = payload.get("jti")
        if jti and await _is_token_revoked(jti):
            raise HTTPException(status_code=401, detail="Token has been revoked")

        return AuthContext(
            user_id=uuid.UUID(payload["sub"]),
            org_id=uuid.UUID(payload["org"]) if payload.get("org") else None,
            scopes=payload.get("scopes", []),
            auth_method="jwt",
            plan=payload.get("plan", "free"),
        )

    # Try API key
    from attocode.code_intel.api.auth.api_keys import resolve_api_key

    ctx = await resolve_api_key(token)
    if ctx is not None:
        return ctx

    raise HTTPException(status_code=401, detail="Invalid credentials")
