"""Shared utilities for the HTTP API."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import select

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from attocode.code_intel.api.auth.context import AuthContext
    from attocode.code_intel.db.models import Repository

# Language detection by extension
LANG_MAP: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescriptreact", ".jsx": "javascriptreact",
    ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".metal": "cpp",
    ".cs": "csharp", ".swift": "swift", ".kt": "kotlin",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".xml": "xml", ".html": "html", ".css": "css",
    ".sql": "sql", ".md": "markdown", ".txt": "plaintext",
    ".dockerfile": "dockerfile",
}

# Max file size for content retrieval (5 MB)
MAX_FILE_SIZE = 5 * 1024 * 1024


def detect_language(path: str) -> str:
    """Detect language from file extension."""
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in LANG_MAP:
        return LANG_MAP[ext]
    basename = os.path.basename(path).lower()
    if basename == "dockerfile":
        return "dockerfile"
    if basename == "makefile":
        return "makefile"
    return ""


def is_binary(data: bytes) -> bool:
    """Heuristic binary detection: check for null bytes in first 8KB."""
    return b"\x00" in data[:8192]


async def get_repo_by_id(
    project_id: uuid.UUID,
    session: AsyncSession,
    auth: AuthContext | None = None,
) -> Repository:
    """Fetch a repository by ID, enforcing optional org isolation.

    Returns 404 when the repo doesn't exist, or when ``auth.org_id`` is set
    and does not match the repo's org.
    """
    from attocode.code_intel.db.models import Repository as _Repository

    result = await session.execute(select(_Repository).where(_Repository.id == project_id))
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if auth and auth.org_id and repo.org_id != auth.org_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


async def get_repo_by_org(
    org_id: uuid.UUID,
    repo_id: uuid.UUID,
    session: AsyncSession,
) -> Repository:
    """Fetch a repository scoped to a specific org.

    Returns 404 when the (org_id, repo_id) tuple doesn't match a repo.
    """
    from attocode.code_intel.db.models import Repository as _Repository

    result = await session.execute(
        select(_Repository).where(
            _Repository.id == repo_id, _Repository.org_id == org_id,
        )
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
