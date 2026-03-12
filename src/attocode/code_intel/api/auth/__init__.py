"""Authentication package — unified auth resolution for local and service modes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Header, HTTPException

from attocode.code_intel.api.deps import get_config

if TYPE_CHECKING:
    from attocode.code_intel.api.auth.context import AuthContext


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
