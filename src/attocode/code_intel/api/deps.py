"""Dependency injection for the HTTP API."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Annotated, AsyncGenerator

from fastapi import HTTPException, Query

from attocode.code_intel.config import CodeIntelConfig
from attocode.code_intel.service import CodeIntelService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from attocode.code_intel.api.auth.context import AuthContext

# N2: Shared BranchParam type alias — used by all route modules
BranchParam = Annotated[str, Query(alias="branch", description="Branch name (empty = default/working dir)")]

logger = logging.getLogger(__name__)

# Module-level singletons set during app startup
_config: CodeIntelConfig | None = None
_services: dict[str, CodeIntelService] = {}
_default_project_id: str = ""


def configure(config: CodeIntelConfig) -> None:
    """Initialize the DI container with a config. Called once at app startup."""
    global _config, _default_project_id
    if _config is not None:
        logger.warning("configure() called more than once; overwriting previous config")
    _config = config
    if config.project_dir:
        svc = CodeIntelService.get_instance(config.project_dir, config)
        _default_project_id = "default"
        _services["default"] = svc


def reset() -> None:
    """Reset all state. For test isolation only."""
    global _config, _default_project_id
    _config = None
    _services.clear()
    _default_project_id = ""


def get_config() -> CodeIntelConfig:
    """Return the active config."""
    if _config is None:
        return CodeIntelConfig.from_env()
    return _config


def get_service(project_id: str = "") -> CodeIntelService:
    """Return the CodeIntelService for a project.

    For Phase 1, only a single project is supported (the default).
    Multi-project support comes in Phase 2.
    """
    pid = project_id or _default_project_id
    if pid not in _services:
        raise ValueError(f"Project '{pid}' not found. Register it first via POST /api/v1/projects")
    return _services[pid]


async def get_service_or_404(project_id: str) -> CodeIntelService:
    """Return the service for a project or raise HTTP 404.

    Supports both CLI-mode string IDs ("default") and service-mode UUIDs.
    For UUIDs in service mode, looks up the repo path from the DB.
    """
    # Fast path: already registered
    if project_id in _services:
        return _services[project_id]
    pid = project_id or _default_project_id
    if pid in _services:
        return _services[pid]

    # Service mode: try UUID lookup from DB
    config = get_config()
    if config.is_service_mode:
        try:
            uuid.UUID(project_id)
        except ValueError:
            pass
        else:
            from attocode.code_intel.db.engine import get_engine

            engine = get_engine()
            if engine is not None:
                from sqlalchemy import text

                async with engine.connect() as conn:
                    result = await conn.execute(
                        text("SELECT clone_path, local_path FROM repositories WHERE id = :rid"),
                        {"rid": project_id},
                    )
                    row = result.first()

                if row is not None:
                    path = row[0] or row[1]
                    if not path:
                        raise HTTPException(
                            status_code=422,
                            detail=f"Repository '{project_id}' has no indexed content yet",
                        )
                    return register_project(project_id, path)

    raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")


def register_project(project_id: str, path: str, name: str = "") -> CodeIntelService:
    """Register a new project and return its service instance."""
    svc = CodeIntelService.get_instance(path, _config)
    _services[project_id] = svc
    return svc


def list_projects() -> dict[str, CodeIntelService]:
    """Return all registered projects."""
    return dict(_services)


def get_default_project_id() -> str:
    """Return the default project ID."""
    return _default_project_id


# --- Provider factories ---


async def get_analysis_provider(project_id: str):
    """Return the appropriate analysis provider based on mode."""
    config = get_config()
    if config.is_service_mode:
        from attocode.code_intel.api.providers.db_provider import DbAnalysisProvider

        return DbAnalysisProvider(project_id)

    from attocode.code_intel.api.providers.local_provider import LocalAnalysisProvider

    svc = await get_service_or_404(project_id)
    return LocalAnalysisProvider(svc)


async def get_search_provider(project_id: str):
    """Return the appropriate search provider based on mode."""
    config = get_config()
    if config.is_service_mode:
        from attocode.code_intel.api.providers.db_provider import DbSearchProvider

        return DbSearchProvider(project_id)

    from attocode.code_intel.api.providers.local_provider import LocalSearchProvider

    svc = await get_service_or_404(project_id)
    return LocalSearchProvider(svc)


async def get_graph_provider(project_id: str):
    """Return the appropriate graph provider based on mode."""
    config = get_config()
    if config.is_service_mode:
        from attocode.code_intel.api.providers.db_provider import DbGraphProvider

        return DbGraphProvider(project_id)

    from attocode.code_intel.api.providers.local_provider import LocalGraphProvider

    svc = await get_service_or_404(project_id)
    return LocalGraphProvider(svc)


async def get_lsp_provider(project_id: str):
    """Return the LSP provider. Currently only local mode is supported."""
    from attocode.code_intel.api.providers.local_provider import LocalLSPProvider

    svc = await get_service_or_404(project_id)
    return LocalLSPProvider(svc)


# --- Branch context ---


class BranchContext:
    """Resolved branch context for service mode queries.

    Contains the branch ID and resolved manifest (path → content_sha).
    Passed to service methods so all queries are branch-aware.
    """

    def __init__(
        self,
        branch_id: uuid.UUID,
        branch_name: str,
        manifest: dict[str, str],
        version: int = 0,
    ) -> None:
        self.branch_id = branch_id
        self.branch_name = branch_name
        self.manifest = manifest
        self.version = version
        self._sha_to_path: dict[str, str] | None = None

    @property
    def content_shas(self) -> set[str]:
        return set(self.manifest.values())

    @property
    def sha_to_path(self) -> dict[str, str]:
        if self._sha_to_path is None:
            self._sha_to_path = {sha: path for path, sha in self.manifest.items()}
        return self._sha_to_path


async def get_branch_context(
    repo_id: uuid.UUID,
    branch_name: str,
    session: AsyncSession,
) -> BranchContext:
    """Resolve branch context for a query. Returns BranchContext with manifest.

    If branch_name is empty, uses the repository's default branch.
    """
    from sqlalchemy import select

    from attocode.code_intel.db.models import Branch, Repository
    from attocode.code_intel.storage.branch_overlay import BranchOverlay

    if not branch_name:
        result = await session.execute(
            select(Repository.default_branch).where(Repository.id == repo_id)
        )
        branch_name = result.scalar_one_or_none() or "main"

    result = await session.execute(
        select(Branch).where(
            Branch.repo_id == repo_id,
            Branch.name == branch_name,
        )
    )
    branch = result.scalar_one_or_none()
    if branch is None:
        raise HTTPException(status_code=404, detail=f"Branch '{branch_name}' not found")

    overlay = BranchOverlay(session)
    manifest = await overlay.resolve_manifest(branch.id)
    version = await overlay.get_version(branch.id)

    return BranchContext(
        branch_id=branch.id,
        branch_name=branch_name,
        manifest=manifest,
        version=version,
    )


# --- Git manager ---


def get_git_manager():
    """Return a GitRepoManager configured from the active config."""
    from attocode.code_intel.git.manager import GitRepoManager

    config = get_config()
    return GitRepoManager(config.git_clone_dir, config.git_ssh_key_path)


# --- Service mode dependencies ---


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session. Raises 503 if not in service mode."""
    config = get_config()
    if not config.is_service_mode:
        raise HTTPException(status_code=503, detail="Service mode not enabled (DATABASE_URL not set)")
    from attocode.code_intel.db.engine import get_session

    async for session in get_session():
        yield session


async def get_org_scoped_session(
    auth: AuthContext,
    session: AsyncSession,
) -> AsyncSession:
    """Set RLS context for org isolation, then return the session.

    M12 fix: Use parameterized SET to prevent SQL injection.
    """
    if auth.org_id:
        from sqlalchemy import text
        await session.execute(
            text("SET LOCAL app.current_org_id = :org_id").bindparams(org_id=str(auth.org_id))
        )
    return session


async def get_repo_service(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    session: AsyncSession,
) -> CodeIntelService:
    """Look up a Repository from DB and return a CodeIntelService for its local_path."""
    from sqlalchemy import select

    from attocode.code_intel.db.models import Repository

    result = await session.execute(
        select(Repository).where(Repository.id == repo_id, Repository.org_id == org_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    path = repo.clone_path or repo.local_path
    if not path:
        raise HTTPException(status_code=422, detail="Repository has no local path or clone")
    return CodeIntelService.get_instance(path, _config)
