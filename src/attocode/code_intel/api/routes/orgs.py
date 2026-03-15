"""Organization management endpoints (service mode only)."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session, get_repo_service
from attocode.code_intel.db.models import Organization, OrgMembership, Repository, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/orgs", tags=["organizations"])


# --- Request/Response models ---


class CreateOrgRequest(BaseModel):
    name: str
    slug: str = ""


class UpdateOrgRequest(BaseModel):
    name: str | None = None
    plan: str | None = None
    settings: dict | None = None


class OrgResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    created_at: str
    member_count: int = 0


class OrgListResponse(BaseModel):
    organizations: list[OrgResponse]
    total: int = 0
    limit: int = 20
    offset: int = 0
    has_more: bool = False


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"


class MemberResponse(BaseModel):
    user_id: str
    email: str
    name: str
    role: str
    accepted: bool


class MemberListResponse(BaseModel):
    members: list[MemberResponse]
    total: int = 0
    limit: int = 20
    offset: int = 0
    has_more: bool = False


class UpdateMemberRequest(BaseModel):
    role: str


class CreateRepoRequest(BaseModel):
    name: str
    clone_url: str | None = None
    local_path: str | None = None
    default_branch: str = "main"
    language: str | None = None


class RepoResponse(BaseModel):
    id: str
    name: str
    clone_url: str | None = None
    local_path: str | None = None
    default_branch: str
    language: str | None = None
    index_status: str
    last_indexed_at: str | None = None
    created_at: str


class RepoListResponse(BaseModel):
    repositories: list[RepoResponse]
    total: int = 0
    limit: int = 20
    offset: int = 0
    has_more: bool = False


def _slugify(name: str) -> str:
    """Generate a URL-safe slug from a name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:64]


async def _require_membership(
    org_id: uuid.UUID, auth: AuthContext, session: AsyncSession, min_role: str = "member"
) -> OrgMembership:
    """Verify the user is a member of the org with sufficient role."""
    if not auth.user_id:
        raise HTTPException(status_code=403, detail="Authentication required")

    role_hierarchy = {"owner": 3, "admin": 2, "member": 1}
    min_level = role_hierarchy.get(min_role, 1)

    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == auth.user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    user_level = role_hierarchy.get(membership.role, 0)
    if user_level < min_level:
        raise HTTPException(status_code=403, detail=f"Requires {min_role} role or higher")

    return membership


# --- Organization CRUD ---


@router.post("", response_model=OrgResponse)
async def create_org(
    req: CreateOrgRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> OrgResponse:
    """Create a new organization. Creator becomes owner."""
    if not auth.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    slug = req.slug or _slugify(req.name)
    existing = await session.execute(select(Organization).where(Organization.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Slug '{slug}' already taken")

    org = Organization(name=req.name, slug=slug)
    session.add(org)
    await session.flush()

    # Add creator as owner
    membership = OrgMembership(
        org_id=org.id,
        user_id=auth.user_id,
        role="owner",
        accepted_at=datetime.now(timezone.utc),
    )
    session.add(membership)
    await session.commit()
    await session.refresh(org)

    from attocode.code_intel.audit import log_event

    await log_event(session, org.id, "org.created", user_id=auth.user_id, detail={"name": org.name, "slug": org.slug})

    return OrgResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        created_at=org.created_at.isoformat(),
        member_count=1,
    )


@router.get("", response_model=OrgListResponse)
async def list_orgs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> OrgListResponse:
    """List organizations the current user belongs to."""
    if not auth.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    base_query = (
        select(Organization)
        .join(OrgMembership, Organization.id == OrgMembership.org_id)
        .where(OrgMembership.user_id == auth.user_id)
    )

    count_result = await session.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar() or 0

    result = await session.execute(base_query.offset(offset).limit(limit))
    orgs = []
    for org in result.scalars():
        orgs.append(OrgResponse(
            id=str(org.id),
            name=org.name,
            slug=org.slug,
            plan=org.plan,
            created_at=org.created_at.isoformat(),
        ))
    return OrgListResponse(
        organizations=orgs, total=total, limit=limit, offset=offset,
        has_more=(offset + limit < total),
    )


@router.get("/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> OrgResponse:
    """Get organization details."""
    await _require_membership(org_id, auth, session)

    result = await session.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    return OrgResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        created_at=org.created_at.isoformat(),
    )


@router.patch("/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: uuid.UUID,
    req: UpdateOrgRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> OrgResponse:
    """Update organization. Requires admin+ role."""
    await _require_membership(org_id, auth, session, min_role="admin")

    result = await session.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    if req.name is not None:
        org.name = req.name
    if req.plan is not None:
        org.plan = req.plan
    if req.settings is not None:
        org.settings = req.settings

    await session.commit()
    await session.refresh(org)

    return OrgResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        created_at=org.created_at.isoformat(),
    )


# --- Members ---


@router.post("/{org_id}/members", response_model=MemberResponse)
async def invite_member(
    org_id: uuid.UUID,
    req: InviteMemberRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> MemberResponse:
    """Invite a user to the organization. Requires admin+ role."""
    await _require_membership(org_id, auth, session, min_role="admin")

    if req.role not in ("member", "admin"):
        raise HTTPException(status_code=400, detail="Role must be 'member' or 'admin'")

    result = await session.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"User with email '{req.email}' not found")

    # Check if already a member
    existing = await session.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")

    membership = OrgMembership(org_id=org_id, user_id=user.id, role=req.role)
    session.add(membership)
    await session.commit()

    from attocode.code_intel.audit import log_event

    await log_event(session, org_id, "member.invited", user_id=auth.user_id, detail={"email": req.email, "role": req.role})

    return MemberResponse(
        user_id=str(user.id),
        email=user.email,
        name=user.name,
        role=req.role,
        accepted=False,
    )


@router.get("/{org_id}/members", response_model=MemberListResponse)
async def list_members(
    org_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> MemberListResponse:
    """List organization members."""
    await _require_membership(org_id, auth, session)

    count_result = await session.execute(
        select(func.count()).select_from(
            select(OrgMembership).where(OrgMembership.org_id == org_id).subquery()
        )
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(OrgMembership, User)
        .join(User, OrgMembership.user_id == User.id)
        .where(OrgMembership.org_id == org_id)
        .offset(offset).limit(limit)
    )
    members = []
    for membership, user in result:
        members.append(MemberResponse(
            user_id=str(user.id),
            email=user.email,
            name=user.name,
            role=membership.role,
            accepted=membership.accepted_at is not None,
        ))
    return MemberListResponse(
        members=members, total=total, limit=limit, offset=offset,
        has_more=(offset + limit < total),
    )


@router.patch("/{org_id}/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    req: UpdateMemberRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> MemberResponse:
    """Change a member's role. Requires owner role."""
    await _require_membership(org_id, auth, session, min_role="owner")

    if req.role not in ("member", "admin", "owner"):
        raise HTTPException(status_code=400, detail="Invalid role")

    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")

    membership.role = req.role
    await session.commit()

    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one()

    from attocode.code_intel.audit import log_event

    await log_event(session, org_id, "member.role_changed", user_id=auth.user_id, detail={"target_user_id": str(user_id), "new_role": req.role})

    return MemberResponse(
        user_id=str(user.id),
        email=user.email,
        name=user.name,
        role=membership.role,
        accepted=membership.accepted_at is not None,
    )


@router.delete("/{org_id}/members/{user_id}")
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Remove a member from the organization. Requires admin+ role."""
    await _require_membership(org_id, auth, session, min_role="admin")

    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if membership.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove the org owner")

    await session.delete(membership)

    from attocode.code_intel.audit import log_event

    await log_event(session, org_id, "member.removed", user_id=auth.user_id, detail={"removed_user_id": str(user_id)})

    await session.commit()
    return {"detail": "Member removed"}


# --- Org-scoped Repositories ---


@router.post("/{org_id}/repos", response_model=RepoResponse)
async def create_repo(
    org_id: uuid.UUID,
    req: CreateRepoRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> RepoResponse:
    """Create a repository in the organization."""
    await _require_membership(org_id, auth, session)

    # Check uniqueness
    existing = await session.execute(
        select(Repository).where(
            Repository.org_id == org_id,
            Repository.name == req.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Repository '{req.name}' already exists in this org")

    repo = Repository(
        org_id=org_id,
        name=req.name,
        clone_url=req.clone_url,
        local_path=req.local_path,
        default_branch=req.default_branch,
        language=req.language,
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)

    # Only enqueue full index if we have a clone_url (server can clone it).
    # local_path-only repos use incremental updates via notify/watch.
    if repo.clone_url:
        try:
            from arq import create_pool

            from attocode.code_intel.workers.settings import get_redis_settings

            pool = await create_pool(get_redis_settings())
            await pool.enqueue_job("index_repository", str(repo.id))
            await pool.aclose()
            repo.index_status = "indexing"
            await session.commit()
            await session.refresh(repo)
        except Exception:
            logger.warning("Failed to enqueue indexing job for repo %s", repo.id, exc_info=True)

    return RepoResponse(
        id=str(repo.id),
        name=repo.name,
        clone_url=repo.clone_url,
        local_path=repo.local_path,
        default_branch=repo.default_branch,
        language=repo.language,
        index_status=repo.index_status,
        last_indexed_at=repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
        created_at=repo.created_at.isoformat(),
    )


@router.get("/{org_id}/repos", response_model=RepoListResponse)
async def list_repos(
    org_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> RepoListResponse:
    """List repositories in the organization."""
    await _require_membership(org_id, auth, session)

    count_result = await session.execute(
        select(func.count()).select_from(
            select(Repository).where(Repository.org_id == org_id).subquery()
        )
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(Repository).where(Repository.org_id == org_id)
        .offset(offset).limit(limit)
    )
    repos = []
    for repo in result.scalars():
        repos.append(RepoResponse(
            id=str(repo.id),
            name=repo.name,
            clone_url=repo.clone_url,
            local_path=repo.local_path,
            default_branch=repo.default_branch,
            language=repo.language,
            index_status=repo.index_status,
            last_indexed_at=repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
            created_at=repo.created_at.isoformat(),
        ))
    return RepoListResponse(
        repositories=repos, total=total, limit=limit, offset=offset,
        has_more=(offset + limit < total),
    )


@router.get("/{org_id}/repos/{repo_id}", response_model=RepoResponse)
async def get_repo(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> RepoResponse:
    """Get repository details."""
    await _require_membership(org_id, auth, session)

    result = await session.execute(
        select(Repository).where(Repository.id == repo_id, Repository.org_id == org_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    return RepoResponse(
        id=str(repo.id),
        name=repo.name,
        clone_url=repo.clone_url,
        local_path=repo.local_path,
        default_branch=repo.default_branch,
        language=repo.language,
        index_status=repo.index_status,
        last_indexed_at=repo.last_indexed_at.isoformat() if repo.last_indexed_at else None,
        created_at=repo.created_at.isoformat(),
    )


@router.delete("/{org_id}/repos/{repo_id}")
async def delete_repo(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete a repository. Requires admin+ role."""
    await _require_membership(org_id, auth, session, min_role="admin")

    result = await session.execute(
        select(Repository).where(Repository.id == repo_id, Repository.org_id == org_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    await session.delete(repo)
    await session.commit()
    return {"detail": "Repository deleted"}


@router.post("/{org_id}/repos/{repo_id}/reindex")
async def reindex_repo(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Trigger a reindex of the repository."""
    await _require_membership(org_id, auth, session)

    result = await session.execute(
        select(Repository).where(Repository.id == repo_id, Repository.org_id == org_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        from arq import create_pool

        from attocode.code_intel.workers.settings import get_redis_settings

        pool = await create_pool(get_redis_settings())
        await pool.enqueue_job("index_repository", str(repo_id))
        await pool.aclose()
    except Exception:
        logger.warning("Failed to enqueue reindex job for repo %s", repo_id, exc_info=True)
        raise HTTPException(status_code=503, detail="Failed to enqueue reindex job")

    repo.index_status = "indexing"
    await session.commit()

    return {"detail": "Reindex triggered", "repo_id": str(repo_id)}


# --- Repo Credential Management ---

_VALID_CRED_TYPES = {"pat", "deploy_token", "ssh_key"}


class SetCredentialRequest(BaseModel):
    cred_type: str  # pat|deploy_token|ssh_key
    value: str


@router.post("/{org_id}/repos/{repo_id}/credentials")
async def set_repo_credential(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    body: SetCredentialRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Set or replace credential for a private repository (admin+)."""
    await _require_membership(org_id, auth, session, min_role="admin")

    if body.cred_type not in _VALID_CRED_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid cred_type. Must be one of: {', '.join(sorted(_VALID_CRED_TYPES))}",
        )

    result = await session.execute(
        select(Repository).where(Repository.id == repo_id, Repository.org_id == org_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    from attocode.code_intel.crypto import encrypt_credential
    from attocode.code_intel.db.models import RepoCredential

    # Remove any existing credential for this repo
    existing = await session.execute(
        select(RepoCredential).where(RepoCredential.repo_id == repo_id)
    )
    for old_cred in existing.scalars().all():
        await session.delete(old_cred)

    cred = RepoCredential(
        repo_id=repo_id,
        cred_type=body.cred_type,
        encrypted_value=encrypt_credential(body.value),
    )
    session.add(cred)
    await session.commit()

    return {"detail": "Credential set", "cred_type": body.cred_type}


@router.get("/{org_id}/repos/{repo_id}/credentials")
async def get_repo_credential_status(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Check whether a credential is configured for a repo (admin+). Never returns the value."""
    await _require_membership(org_id, auth, session, min_role="admin")

    result = await session.execute(
        select(Repository).where(Repository.id == repo_id, Repository.org_id == org_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    from attocode.code_intel.db.models import RepoCredential

    result = await session.execute(
        select(RepoCredential).where(RepoCredential.repo_id == repo_id).limit(1)
    )
    cred = result.scalar_one_or_none()
    if cred is None:
        return {"configured": False}

    return {
        "configured": True,
        "cred_type": cred.cred_type,
        "created_at": cred.created_at.isoformat(),
    }


@router.delete("/{org_id}/repos/{repo_id}/credentials")
async def delete_repo_credential(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Remove credential for a repository (admin+)."""
    await _require_membership(org_id, auth, session, min_role="admin")

    result = await session.execute(
        select(Repository).where(Repository.id == repo_id, Repository.org_id == org_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    from attocode.code_intel.db.models import RepoCredential

    existing = await session.execute(
        select(RepoCredential).where(RepoCredential.repo_id == repo_id)
    )
    deleted = 0
    for cred in existing.scalars().all():
        await session.delete(cred)
        deleted += 1

    await session.commit()
    return {"detail": "Credential removed" if deleted else "No credential configured"}
