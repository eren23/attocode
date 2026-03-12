"""Service-mode file/tree browsing via bare git repos (v2)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.auth import resolve_auth
from attocode.code_intel.api.auth.context import AuthContext
from attocode.code_intel.api.deps import get_db_session, get_git_manager

router = APIRouter(prefix="/api/v2/repos/{repo_id}", tags=["files-v2"])
logger = logging.getLogger(__name__)

# Max file size for content retrieval (5 MB)
_MAX_FILE_SIZE = 5 * 1024 * 1024

# Language detection by extension (shared with files.py)
_LANG_MAP: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescriptreact", ".jsx": "javascriptreact",
    ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
    ".cs": "csharp", ".swift": "swift", ".kt": "kotlin",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".xml": "xml", ".html": "html", ".css": "css",
    ".sql": "sql", ".md": "markdown", ".txt": "plaintext",
    ".dockerfile": "dockerfile",
}


def _detect_language(path: str) -> str:
    """Detect language from file extension."""
    import os

    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in _LANG_MAP:
        return _LANG_MAP[ext]
    basename = os.path.basename(path).lower()
    if basename == "dockerfile":
        return "dockerfile"
    if basename == "makefile":
        return "makefile"
    return ""


def _is_binary(data: bytes) -> bool:
    """Heuristic binary detection: check for null bytes in first 8KB."""
    return b"\x00" in data[:8192]


# --- Response models ---


class TreeEntryV2(BaseModel):
    name: str
    path: str
    type: str  # blob|tree
    size: int = 0
    language: str = ""


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


async def _get_repo(repo_id: uuid.UUID, session: AsyncSession):
    from attocode.code_intel.db.models import Repository

    result = await session.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


async def _resolve_ref(repo, ref: str) -> str:
    """Resolve ref to use — defaults to repo's default_branch."""
    return ref if ref else repo.default_branch


# --- Endpoints ---


@router.get("/tree", response_model=TreeResponse)
async def get_root_tree(
    repo_id: uuid.UUID,
    ref: str = Query("", description="Git ref (branch, tag, commit). Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> TreeResponse:
    """List root tree at a ref."""
    repo = await _get_repo(repo_id, session)
    git = get_git_manager()
    resolved_ref = await _resolve_ref(repo, ref)

    try:
        entries = git.get_tree(str(repo_id), resolved_ref)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    return TreeResponse(
        path="",
        ref=resolved_ref,
        entries=[
            TreeEntryV2(
                name=e.name,
                path=e.path,
                type=e.type,
                size=e.size,
                language=_detect_language(e.name) if e.type == "blob" else "",
            )
            for e in entries
        ],
    )


@router.get("/tree/{path:path}", response_model=TreeResponse)
async def get_subtree(
    repo_id: uuid.UUID,
    path: str,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> TreeResponse:
    """List subtree at a path and ref."""
    repo = await _get_repo(repo_id, session)
    git = get_git_manager()
    resolved_ref = await _resolve_ref(repo, ref)

    # Validate path
    if ".." in path.split("/"):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    try:
        entries = git.get_tree(str(repo_id), resolved_ref, path)
    except (FileNotFoundError, ValueError, KeyError) as e:
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")

    return TreeResponse(
        path=path,
        ref=resolved_ref,
        entries=[
            TreeEntryV2(
                name=e.name,
                path=e.path,
                type=e.type,
                size=e.size,
                language=_detect_language(e.name) if e.type == "blob" else "",
            )
            for e in entries
        ],
    )


@router.get("/files/{path:path}", response_model=FileContentV2Response)
async def get_file_content(
    repo_id: uuid.UUID,
    path: str,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> FileContentV2Response:
    """Read file content at a specific ref."""
    repo = await _get_repo(repo_id, session)
    git = get_git_manager()
    resolved_ref = await _resolve_ref(repo, ref)

    # Validate path
    if ".." in path.split("/"):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    try:
        data = git.read_file(str(repo_id), resolved_ref, path)
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
    repo_id: uuid.UUID,
    ref: str = Query("", description="Git ref. Defaults to default branch."),
    auth: AuthContext = Depends(resolve_auth),
    session: AsyncSession = Depends(get_db_session),
) -> RepoStatsResponse:
    """Get repository file/symbol/language/embedding stats."""
    from attocode.code_intel.api.deps import get_branch_context
    from attocode.code_intel.db.models import Embedding, Symbol

    repo = await _get_repo(repo_id, session)
    resolved_ref = ref if ref else repo.default_branch

    try:
        branch_ctx = await get_branch_context(repo_id, resolved_ref, session)
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
