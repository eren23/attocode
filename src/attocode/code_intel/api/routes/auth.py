"""Authentication endpoints (service mode only)."""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.auth.jwt import create_access_token, create_refresh_token, decode_token
from attocode.code_intel.api.auth.passwords import hash_password, verify_password
from attocode.code_intel.api.deps import get_config, get_db_session
from attocode.code_intel.db.models import OrgMembership, User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# --- Request/Response models ---


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""


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
    url = await get_github_auth_url(
        client_id=config.github_client_id,
        redirect_uri=f"http://{config.host}:{config.port}/api/v1/auth/github/callback",
        state=state,
    )
    return {"authorize_url": url, "state": state}


@router.get("/github/callback", response_model=TokenResponse)
async def github_callback(
    code: str = Query(...),
    state: str = Query(""),
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Handle GitHub OAuth callback — create/link user, return JWT."""
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
            user.avatar_url = gh_user["avatar_url"]
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

    return TokenResponse(
        access_token=create_access_token(user.id, expires_minutes=config.jwt_expiry_minutes),
        refresh_token=create_refresh_token(user.id, expires_days=config.refresh_expiry_days),
    )


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
