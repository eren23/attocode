"""Service API key generation and resolution."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attocode.code_intel.api.auth.context import AuthContext


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (plaintext_key, key_hash, key_prefix) — show plaintext once, store hash.
    """
    plaintext = f"aci_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    key_prefix = plaintext[:12]
    return plaintext, key_hash, key_prefix


async def resolve_api_key(token: str) -> AuthContext | None:
    """Look up a service API key by its SHA-256 hash. Returns AuthContext or None."""
    import hashlib

    from sqlalchemy import select

    from attocode.code_intel.api.auth.context import AuthContext
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import ApiKey

    key_hash = hashlib.sha256(token.encode()).hexdigest()

    async for session in get_session():
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            return None

        # Check expiry
        if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
            return None

        # Update last_used_at
        api_key.last_used_at = datetime.now(timezone.utc)
        await session.commit()

        return AuthContext(
            user_id=api_key.user_id,
            org_id=api_key.org_id,
            scopes=list(api_key.scopes) if api_key.scopes else [],
            auth_method="api_key",
            plan="free",
        )
    return None
