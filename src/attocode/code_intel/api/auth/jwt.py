"""JWT token creation and validation."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def create_access_token(
    user_id: uuid.UUID,
    org_id: uuid.UUID | None = None,
    scopes: list[str] | None = None,
    plan: str = "free",
    expires_minutes: int = 60,
) -> str:
    """Create a signed JWT access token."""
    from jose import jwt

    from attocode.code_intel.api.deps import get_config

    config = get_config()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "scopes": scopes or [],
        "plan": plan,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    if org_id:
        payload["org"] = str(org_id)
    return jwt.encode(payload, config.secret_key, algorithm="HS256")


def create_refresh_token(user_id: uuid.UUID, expires_days: int = 30) -> str:
    """Create a signed JWT refresh token."""
    from jose import jwt

    from attocode.code_intel.api.deps import get_config

    config = get_config()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=expires_days),
    }
    return jwt.encode(payload, config.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT token. Returns payload dict or None if invalid."""
    from jose import JWTError, jwt

    from attocode.code_intel.api.deps import get_config

    config = get_config()
    try:
        return jwt.decode(token, config.secret_key, algorithms=["HS256"])
    except JWTError:
        return None
