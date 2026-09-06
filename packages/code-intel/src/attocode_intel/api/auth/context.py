"""Authentication context — carries identity info through request lifecycle."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(slots=True)
class AuthContext:
    """Identity and authorization context for an authenticated request."""

    user_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None
    scopes: list[str] = field(default_factory=list)
    auth_method: str = "legacy"  # legacy|jwt|api_key
    plan: str = "free"  # free|team|enterprise

    def has_scope(self, scope: str) -> bool:
        """Check if the context has a specific scope."""
        if not self.scopes:
            return True  # Empty scopes = full access (legacy mode)
        return scope in self.scopes

    def require_scope(self, scope: str) -> None:
        """Raise if the required scope is missing."""
        if not self.has_scope(scope):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")

    def require_role(self, org_id: uuid.UUID, min_role: str) -> None:
        """Placeholder for role checks — actual check done in route handlers."""
        pass
