"""Service-mode file/tree browsing via bare git repos (v2).

Supports two backends:
1. Bare git clone on disk (repos with clone_path) — uses GitManager
2. DB-backed manifest (remote-connected repos without clone_path) — uses BranchOverlay + ContentStore
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_branch_context, get_db_session, get_git_manager
from attocode.code_intel.api.utils import MAX_FILE_SIZE, detect_language, is_binary

router = APIRouter(prefix="/api/v2/projects/{project_id}", tags=["files-v2"])
logger = logging.getLogger(__name__)

# Backward-compatible aliases
_MAX_FILE_SIZE = MAX_FILE_SIZE
_detect_language = detect_language
_is_binary = is_binary


# --- Response models ---


class TreeEntryV2(BaseModel):
    name: str
    path: str
    type: str  # file|directory
    size: int = 0
    language: str = ""
    children: list[TreeEntryV2] | None = None


class TreeResponse(BaseModel):
    path: str
    ref: str
    entries: list[TreeEntryV2]


class FileContentV2Response(BaseModel):
    path: str
    ref: str
    content: str
    language: str
    size_bytes: int
    line_count: int


class RepoStatsResponse(BaseModel):
    total_files: int = 0
    total_symbols: int = 0
    languages: dict[str, int] = {}
    embedded_files: int = 0
    total_size_bytes: int = 0


# --- Helpers ---


async def _get_repo(project_id: uuid.UUID, session: AsyncSession, auth: AuthContext | None = None):
    from attocode.code_intel.db.models import Repository

    result = await session.execute(select(Repository).where(Repository.id == project_id))
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    # Org isolation
    if auth and auth.org_id and repo.org_id != auth.org_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


async def _resolve_ref(repo, ref: str) -> str:
    """Resolve ref to use — defaults to repo's default_branch."""
    return ref if ref else repo.default_branch


async def _build_tree_from_manifest(
    session: AsyncSession,
    repo_id: uuid.UUID,
    ref: str,
    path: str = "",
) -> list[TreeEntryV2]:
    """Build nested tree from BranchFile manifest (for repos without bare git clones).

    Resolves the manifest once, then builds the tree in-memory.
    """
    from attocode.code_intel.db.models import FileContent

    branch_ctx = await get_branch_context(repo_id, ref, session)
    manifest = branch_ctx.manifest  # dict[str, str] path → sha

    # Fetch file sizes in bulk
    shas = list(set(manifest.values()))
    sizes: dict[str, int] = {}
    if shas:
        result = await session.execute(
            select(FileContent.sha256, FileContent.size_bytes)
            .where(FileContent.sha256.in_(shas))
        )
        sizes = {row[0]: row[1] for row in result}

    return _assemble_tree(manifest, sizes, path)


def _assemble_tree(
    manifest: dict[str, str],
    sizes: dict[str, int],
    path: str = "",
) -> list[TreeEntryV2]:
    """Build a nested TreeEntryV2 list from a flat manifest (pure in-memory, no DB calls)."""
    prefix = (path.rstrip("/") + "/") if path else ""

    dirs: dict[str, list[str]] = {}
    files: list[tuple[str, str, int]] = []

    for file_path, sha in manifest.items():
        if prefix and not file_path.startswith(prefix):
            continue
        relative = file_path[len(prefix):]
        parts = relative.split("/")
        if len(parts) == 1:
            files.append((parts[0], file_path, sizes.get(sha, 0)))
        else:
            dir_name = parts[0]
            if dir_name not in dirs:
                dirs[dir_name] = []
            dirs[dir_name].append(file_path)

    entries: list[TreeEntryV2] = []

    for dir_name in sorted(dirs.keys(), key=str.lower):
        dir_path = f"{prefix}{dir_name}" if prefix else dir_name
        children = _assemble_tree(manifest, sizes, dir_path)
        entries.append(TreeEntryV2(
            name=dir_name,
            path=dir_path,
            type="directory",
            size=0,
            language="",
            children=children,
        ))

    for name, full_path, size in sorted(files, key=lambda x: x[0].lower()):
        entries.append(TreeEntryV2(
            name=name,
            path=full_path,
            type="file",
            size=size,
            language=_detect_language(name),
        ))

    return entries


# --- Endpoints ---


def _build_tree_recursive(
    git, project_id: str, ref: str, path: str = "", max_depth: int = 10,
) -> list[TreeEntryV2]:
    """Build a nested tree by recursively walking git entries."""
    if max_depth <= 0:
        return []
    try:
        entries = git.get_tree(project_id, ref, path) if path else git.get_tree(project_id, ref)
    except (FileNotFoundError, ValueError, KeyError):
        return []

    result = []
    for e in entries:
        node_type = "directory" if e.type == "tree" else "file"
        children = None
        if e.type == "tree":
            children = _build_tree_recursive(git, project_id, ref, e.path, max_depth - 1)
        result.append(TreeEntryV2(
            name=e.name,
            path=e.path,
            type=node_type,
            size=e.size,
            language=_detect_language(e.name) if e.type == "blob" else "",
            children=children,
        ))
    # Sort: directories first, then files, alphabetically
    result.sort(key=lambda x: (0 if x.type == "directory" else 1, x.name.lower()))
    return result


@router.get("/tree", response_model=TreeResponse)
async def get_root_tree(
    project_id: uuid.UUID,
    ref: str = Query("", description="Git ref (branch, tag, commit). Defaults to default branch."),
    recursive: bool = Query(True, description="Return nested tree with children"),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> TreeResponse:
    """List root tree at a ref. With recursive=true, returns full nested tree."""
    repo = await _get_repo(project_id, session, auth)
    resolved_ref = await _resolve_ref(repo, ref)

    # DB-backed fallback for repos without a bare git clone (remote-connected)
    if not repo.clone_path:
        entries = await _build_tree_from_manifest(session, project_id, resolved_ref)
        return TreeResponse(path="", ref=resolved_ref, entries=entries)

    git = get_git_manager()

    if recursive:
        import asyncio
        loop = asyncio.get_running_loop()
        entries = await loop.run_in_executor(
            None, _build_tree_recursive, git, str(project_id), resolved_ref, "", 10,
        )
        return TreeResponse(path="", ref=resolved_ref, entries=entries)

    try:
        entries = git.get_tree(str(project_id), resolved_ref)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    return TreeResponse(
        path="",
        ref=resolved_ref,
        entries=[
            TreeEntryV2(
                name=e.name,
                path=e.path,
                type="directory" if e.type == "tree" else "file",
                size=e.size,
                language=_detect_language(e.name) if e.type == "blob" else "",
            )
            for e in entries
        ],
    )


@router.get("/tree/{path:path}", response_model=TreeResponse)
async def get_subtree(
    project_id: uuid.UUID,
    path: str,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> TreeResponse:
    """List subtree at a path and ref."""
    repo = await _get_repo(project_id, session, auth)
    resolved_ref = await _resolve_ref(repo, ref)

    # Validate path
    if ".." in path.split("/"):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    # DB-backed fallback for repos without a bare git clone
    if not repo.clone_path:
        entries = await _build_tree_from_manifest(session, project_id, resolved_ref, path)
        return TreeResponse(path=path, ref=resolved_ref, entries=entries)

    git = get_git_manager()

    try:
        entries = git.get_tree(str(project_id), resolved_ref, path)
    except (FileNotFoundError, ValueError, KeyError) as e:
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")

    return TreeResponse(
        path=path,
        ref=resolved_ref,
        entries=[
            TreeEntryV2(
                name=e.name,
                path=e.path,
                type="directory" if e.type == "tree" else "file",
                size=e.size,
                language=_detect_language(e.name) if e.type == "blob" else "",
            )
            for e in entries
        ],
    )


@router.get("/files/{path:path}", response_model=FileContentV2Response)
async def get_file_content(
    project_id: uuid.UUID,
    path: str,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> FileContentV2Response:
    """Read file content at a specific ref."""
    repo = await _get_repo(project_id, session, auth)
    resolved_ref = await _resolve_ref(repo, ref)

    # Validate path
    if ".." in path.split("/"):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    # DB-backed fallback: read from ContentStore via manifest SHA
    if not repo.clone_path:
        from attocode.code_intel.storage.content_store import ContentStore

        branch_ctx = await get_branch_context(project_id, resolved_ref, session)
        sha = branch_ctx.manifest.get(path)
        if sha is None:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        content_store = ContentStore(session)
        data = await content_store.get(sha)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Content not found for {path}")
    else:
        git = get_git_manager()
        try:
            data = git.read_file(str(project_id), resolved_ref, path)
        except (FileNotFoundError, KeyError) as e:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

    if len(data) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(data)} bytes, max {_MAX_FILE_SIZE})",
        )

    if _is_binary(data):
        raise HTTPException(status_code=415, detail="Binary file — content not available via this endpoint")

    content = data.decode("utf-8", errors="replace")
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

    return FileContentV2Response(
        path=path,
        ref=resolved_ref,
        content=content,
        language=_detect_language(path),
        size_bytes=len(data),
        line_count=line_count,
    )


@router.get("/stats", response_model=RepoStatsResponse)
async def get_repo_stats(
    project_id: uuid.UUID,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> RepoStatsResponse:
    """Get repository file/symbol/language/embedding stats."""
    from attocode.code_intel.db.models import Embedding, Symbol

    repo = await _get_repo(project_id, session, auth)
    resolved_ref = ref if ref else repo.default_branch

    try:
        branch_ctx = await get_branch_context(project_id, resolved_ref, session)
    except HTTPException:
        return RepoStatsResponse()

    manifest = branch_ctx.manifest
    content_shas = branch_ctx.content_shas

    # Count files and aggregate languages
    languages: dict[str, int] = {}
    total_size = 0
    for path in manifest:
        lang = _detect_language(path)
        if lang:
            languages[lang] = languages.get(lang, 0) + 1

    # Count symbols
    symbol_count = 0
    if content_shas:
        result = await session.execute(
            select(func.count()).select_from(
                select(Symbol.id).where(Symbol.content_sha.in_(content_shas)).subquery()
            )
        )
        symbol_count = result.scalar() or 0

    # Count embedded files
    embedded_count = 0
    if content_shas:
        result = await session.execute(
            select(func.count(func.distinct(Embedding.content_sha))).where(
                Embedding.content_sha.in_(content_shas)
            )
        )
        embedded_count = result.scalar() or 0

    return RepoStatsResponse(
        total_files=len(manifest),
        total_symbols=symbol_count,
        languages=languages,
        embedded_files=embedded_count,
    )
