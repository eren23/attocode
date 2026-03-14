"""Authentication endpoints (service mode only)."""

from __future__ import annotations

import secrets
import time
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import RedirectResponse

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.auth.jwt import create_access_token, create_refresh_token, decode_token
from attocode.code_intel.api.auth.passwords import hash_password, verify_password
from attocode.code_intel.api.deps import get_config, get_db_session
from attocode.code_intel.db.models import OrgMembership, User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# --- OAuth state store (single-instance, 10 min TTL) ---

_oauth_states: dict[str, float] = {}


def _store_state(state: str) -> None:
    """Store an OAuth state token with the current timestamp."""
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if now - v > 600]
    for k in expired:
        del _oauth_states[k]
    _oauth_states[state] = now


def _validate_state(state: str) -> bool:
    """Validate and consume an OAuth state token (single-use)."""
    ts = _oauth_states.pop(state, None)
    if ts is None:
        return False
    return time.time() - ts < 600


# --- Request/Response models ---


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""
    registration_key: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserProfile(BaseModel):
    id: str
    email: str
    name: str
    avatar_url: str | None = None
    auth_provider: str
    orgs: list[dict]


# --- Endpoints ---


@router.post("/register", response_model=TokenResponse)
async def register(
    req: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Register a new user with email + password."""
    config = get_config()
    if config.registration_key and req.registration_key != config.registration_key:
        raise HTTPException(status_code=403, detail="Invalid registration key")

    # Check if email already exists
    existing = await session.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=req.email,
        name=req.name or req.email.split("@")[0],
        password_hash=hash_password(req.password),
        auth_provider="email",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    config = get_config()
    return TokenResponse(
        access_token=create_access_token(user.id, expires_minutes=config.jwt_expiry_minutes),
        refresh_token=create_refresh_token(user.id, expires_days=config.refresh_expiry_days),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Login with email + password, returns JWT tokens."""
    result = await session.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if user is None or not user.password_hash or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    config = get_config()
    return TokenResponse(
        access_token=create_access_token(user.id, expires_minutes=config.jwt_expiry_minutes),
        refresh_token=create_refresh_token(user.id, expires_days=config.refresh_expiry_days),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    req: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Exchange a refresh token for a new access token."""
    payload = decode_token(req.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = uuid.UUID(payload["sub"])
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    config = get_config()
    return TokenResponse(
        access_token=create_access_token(user.id, expires_minutes=config.jwt_expiry_minutes),
        refresh_token=create_refresh_token(user.id, expires_days=config.refresh_expiry_days),
    )


@router.get("/github")
async def github_authorize() -> dict:
    """Redirect URL for GitHub OAuth authorization."""
    from attocode.code_intel.api.auth.oauth import get_github_auth_url

    config = get_config()
    if not config.github_client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")

    state = secrets.token_urlsafe(32)
    _store_state(state)
    url = await get_github_auth_url(
        client_id=config.github_client_id,
        redirect_uri=f"{config.effective_base_url}/api/v1/auth/github/callback",
        state=state,
    )
    return {"authorize_url": url, "state": state}


@router.get("/github/callback")
async def github_callback(
    code: str = Query(...),
    state: str = Query(""),
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    """Handle GitHub OAuth callback — create/link user, redirect with JWT."""
    if not _validate_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    from attocode.code_intel.api.auth.oauth import exchange_github_code

    config = get_config()
    if not config.github_client_id or not config.github_client_secret:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")

    gh_user = await exchange_github_code(
        code=code,
        client_id=config.github_client_id,
        client_secret=config.github_client_secret,
    )

    # Try to find existing user by github_id
    result = await session.execute(
        select(User).where(User.github_id == gh_user["github_id"])
    )
    user = result.scalar_one_or_none()

    if user is None:
        # Try by email
        result = await session.execute(
            select(User).where(User.email == gh_user["email"])
        )
        user = result.scalar_one_or_none()
        if user:
            # Link GitHub to existing account
            user.github_id = gh_user["github_id"]
            user.avatar_url = user.avatar_url or gh_user["avatar_url"]
        else:
            # Create new user
            user = User(
                email=gh_user["email"],
                name=gh_user["name"],
                github_id=gh_user["github_id"],
                avatar_url=gh_user["avatar_url"],
                auth_provider="github",
            )
            session.add(user)

    await session.commit()
    await session.refresh(user)

    access_token = create_access_token(user.id, expires_minutes=config.jwt_expiry_minutes)
    refresh_token = create_refresh_token(user.id, expires_days=config.refresh_expiry_days)
    fragment = urlencode({"access_token": access_token, "refresh_token": refresh_token})
    return RedirectResponse(url=f"/auth/callback#{fragment}", status_code=302)


@router.get("/google")
async def google_authorize() -> dict:
    """Redirect URL for Google OAuth authorization."""
    from attocode.code_intel.api.auth.oauth import get_google_auth_url

    config = get_config()
    if not config.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    state = secrets.token_urlsafe(32)
    _store_state(state)
    url = await get_google_auth_url(
        client_id=config.google_client_id,
        redirect_uri=f"{config.effective_base_url}/api/v1/auth/google/callback",
        state=state,
    )
    return {"authorize_url": url, "state": state}


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(""),
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    """Handle Google OAuth callback — create/link user, redirect with JWT."""
    if not _validate_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    from attocode.code_intel.api.auth.oauth import exchange_google_code

    config = get_config()
    if not config.google_client_id or not config.google_client_secret:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    g_user = await exchange_google_code(
        code=code,
        client_id=config.google_client_id,
        client_secret=config.google_client_secret,
        redirect_uri=f"{config.effective_base_url}/api/v1/auth/google/callback",
    )

    # Lookup by google_id -> email -> create new
    result = await session.execute(select(User).where(User.google_id == g_user["google_id"]))
    user = result.scalar_one_or_none()

    if user is None:
        result = await session.execute(select(User).where(User.email == g_user["email"]))
        user = result.scalar_one_or_none()
        if user:
            user.google_id = g_user["google_id"]
            user.avatar_url = user.avatar_url or g_user["avatar_url"]
        else:
            user = User(
                email=g_user["email"],
                name=g_user["name"],
                google_id=g_user["google_id"],
                avatar_url=g_user["avatar_url"],
                auth_provider="google",
            )
            session.add(user)

    await session.commit()
    await session.refresh(user)

    access_token = create_access_token(user.id, expires_minutes=config.jwt_expiry_minutes)
    refresh_token = create_refresh_token(user.id, expires_days=config.refresh_expiry_days)
    fragment = urlencode({"access_token": access_token, "refresh_token": refresh_token})
    return RedirectResponse(url=f"/auth/callback#{fragment}", status_code=302)


@router.get("/providers")
async def list_providers() -> dict:
    """List available auth providers. No auth required — called from login page."""
    config = get_config()
    providers = ["email"]
    if config.github_client_id:
        providers.append("github")
    if config.google_client_id:
        providers.append("google")
    return {
        "providers": providers,
        "registration_enabled": True,
        "registration_key_required": bool(config.registration_key),
    }


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    avatar_url: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.patch("/me", response_model=UserProfile)
async def update_profile(
    req: UpdateProfileRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> UserProfile:
    """Update current user's profile (name, avatar_url)."""
    if not auth.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await session.execute(select(User).where(User.id == auth.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if req.name is not None:
        user.name = req.name
    if req.avatar_url is not None:
        user.avatar_url = req.avatar_url

    await session.commit()
    await session.refresh(user)

    memberships = await session.execute(
        select(OrgMembership).where(OrgMembership.user_id == user.id)
    )
    orgs = [{"org_id": str(m.org_id), "role": m.role} for m in memberships.scalars()]

    return UserProfile(
        id=str(user.id),
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        auth_provider=user.auth_provider,
        orgs=orgs,
    )


@router.post("/me/password")
async def change_password(
    req: ChangePasswordRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Change password (requires current password)."""
    if not auth.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await session.execute(select(User).where(User.id == auth.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.password_hash:
        raise HTTPException(status_code=400, detail="Account uses OAuth — no password to change")

    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    user.password_hash = hash_password(req.new_password)
    await session.commit()
    return {"detail": "Password changed"}


@router.get("/me", response_model=UserProfile)
async def me(
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> UserProfile:
    """Get current user profile with org memberships."""
    if not auth.user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await session.execute(select(User).where(User.id == auth.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Get org memberships
    memberships = await session.execute(
        select(OrgMembership).where(OrgMembership.user_id == user.id)
    )
    orgs = []
    for m in memberships.scalars():
        orgs.append({"org_id": str(m.org_id), "role": m.role})

    return UserProfile(
        id=str(user.id),
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        auth_provider=user.auth_provider,
        orgs=orgs,
    )
