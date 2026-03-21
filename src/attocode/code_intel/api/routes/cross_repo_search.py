"""Cross-repository search endpoint — search across all repos in an org."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v2/orgs/{org_id}",
    tags=["cross-repo-search"],
)


# --- Request/Response models ---


class CrossRepoSearchRequest(BaseModel):
    query: str
    repo_ids: list[str] = []
    top_k: int = 20
    file_filter: str = ""


class CrossRepoSearchResultItem(BaseModel):
    repo_id: str = ""
    repo_name: str = ""
    file_path: str = ""
    score: float = 0.0
    snippet: str = ""


class CrossRepoSearchResponse(BaseModel):
    query: str
    results: list[CrossRepoSearchResultItem]
    total: int
    repos_searched: int = 0


# --- Endpoint ---


@router.post("/search", response_model=CrossRepoSearchResponse)
async def cross_repo_search(
    org_id: uuid.UUID,
    req: CrossRepoSearchRequest,
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> CrossRepoSearchResponse:
    """Semantic search across multiple repositories in an organization.

    If repo_ids is empty, searches all repos in the org.
    Results are sorted globally by cosine similarity score.
    """
    from attocode.code_intel.api.deps import get_config
    from attocode.code_intel.db.models import Branch, OrgMembership, Repository
    from attocode.code_intel.storage.branch_overlay import BranchOverlay
    from attocode.code_intel.storage.embedding_store import EmbeddingStore
    from attocode.integrations.context.embeddings import create_embedding_provider

    # 1. Verify org membership
    if not auth.user_id:
        raise HTTPException(status_code=403, detail="Authentication required")

    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == auth.user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    # 2. Resolve target repositories
    if req.repo_ids:
        # Filter to specified repos within the org
        repo_uuids = []
        for rid in req.repo_ids:
            try:
                repo_uuids.append(uuid.UUID(rid))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid repo_id format: {rid}",
                )

        result = await session.execute(
            select(Repository).where(
                Repository.org_id == org_id,
                Repository.id.in_(repo_uuids),
            )
        )
    else:
        # All repos in the org
        result = await session.execute(
            select(Repository).where(Repository.org_id == org_id)
        )

    repos = result.scalars().all()
    if not repos:
        return CrossRepoSearchResponse(
            query=req.query, results=[], total=0, repos_searched=0,
        )

    # Build repo_id → name mapping
    repo_name_map: dict[str, str] = {str(r.id): r.name for r in repos}

    # 3. For each repo, get default branch and resolve manifest
    overlay = BranchOverlay(session)
    branch_manifests: dict[str, dict[str, str]] = {}

    for repo in repos:
        # Find the default branch
        branch_result = await session.execute(
            select(Branch).where(
                Branch.repo_id == repo.id,
                Branch.name == repo.default_branch,
            )
        )
        branch = branch_result.scalar_one_or_none()
        if branch is None:
            # Try is_default flag as fallback
            branch_result = await session.execute(
                select(Branch).where(
                    Branch.repo_id == repo.id,
                    Branch.is_default == True,  # noqa: E712
                )
            )
            branch = branch_result.scalar_one_or_none()

        if branch is None:
            logger.debug(
                "Skipping repo %s (%s): no default branch found",
                repo.name, repo.id,
            )
            continue

        manifest = await overlay.resolve_manifest(branch.id)
        if manifest:
            branch_manifests[str(repo.id)] = manifest

    if not branch_manifests:
        return CrossRepoSearchResponse(
            query=req.query, results=[], total=0, repos_searched=0,
        )

    # 4. Embed query
    config = get_config()
    provider = create_embedding_provider(config.embedding_model)
    if provider.name == "none":
        raise HTTPException(
            status_code=503,
            detail="No embedding provider available for semantic search",
        )

    query_vectors = provider.embed([req.query])
    query_vector = query_vectors[0]

    # 5. Single pgvector query across all repos
    store = EmbeddingStore(session)
    results = await store.multi_branch_similarity_search(
        session=session,
        branch_manifests=branch_manifests,
        query_vector=query_vector,
        top_k=req.top_k,
        model=provider.name,
        file_filter=req.file_filter,
    )

    # 6. Build response with repo context
    items = [
        CrossRepoSearchResultItem(
            repo_id=r["repo_id"],
            repo_name=repo_name_map.get(r["repo_id"], "unknown"),
            file_path=r["file"],
            score=r["score"],
            snippet=r.get("chunk_text", ""),
        )
        for r in results
    ]

    return CrossRepoSearchResponse(
        query=req.query,
        results=items,
        total=len(items),
        repos_searched=len(branch_manifests),
    )
