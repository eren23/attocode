"""API key authentication middleware."""

from __future__ import annotations

from fastapi import Header, HTTPException

from attocode.code_intel.api.deps import get_config


async def verify_api_key(authorization: str | None = Header(None)) -> None:
    """Verify the API key if one is configured.

    If ATTOCODE_API_KEY is not set, all requests are allowed (local mode).
    """
    config = get_config()
    if not config.api_key:
        return  # No auth configured = open access (local mode)
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    # Accept "Bearer <key>" or raw key
    token = authorization.removeprefix("Bearer ").strip()
    if token != config.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
