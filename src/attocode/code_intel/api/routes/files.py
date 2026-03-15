"""File content and tree endpoints."""

from __future__ import annotations

import logging
import mimetypes
import os

from fastapi import APIRouter, Depends, HTTPException

from attocode.code_intel.api.auth import verify_auth
from attocode.code_intel.api.deps import BranchParam, get_service_or_404
from attocode.code_intel.api.models import (
    FileContentResponse,
    FileTreeResponse,
    TreeEntry,
)
from attocode.code_intel.api.utils import LANG_MAP, MAX_FILE_SIZE, detect_language

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["files"],
    dependencies=[Depends(verify_auth)],
)

# Backward-compatible aliases
_LANG_MAP = LANG_MAP
_MAX_FILE_SIZE = MAX_FILE_SIZE
_detect_language = detect_language


def _resolve_path(project_dir: str, rel_path: str) -> str:
    """Resolve and validate a relative path within the project."""
    abs_path = os.path.realpath(os.path.join(project_dir, rel_path))
    real_root = os.path.realpath(project_dir)
    if not abs_path.startswith(real_root + os.sep) and abs_path != real_root:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    return abs_path


@router.get("/files/{path:path}", response_model=FileContentResponse)
async def get_file_content(
    project_id: str,
    path: str,
    branch: BranchParam = "",
) -> FileContentResponse:
    """Read file content with metadata."""
    svc = await get_service_or_404(project_id)
    abs_path = _resolve_path(svc.project_dir, path)

    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    stat = os.stat(abs_path)
    if stat.st_size > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({stat.st_size} bytes, max {_MAX_FILE_SIZE})",
        )

    # Check if binary
    mime_type, _ = mimetypes.guess_type(abs_path)
    if mime_type and not mime_type.startswith("text/") and mime_type != "application/json":
        # Allow known text formats
        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in _LANG_MAP and ext not in {".cfg", ".ini", ".env", ".gitignore"}:
            raise HTTPException(status_code=415, detail="Binary file — content not available via this endpoint")

    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        logger.exception("Error reading %s", abs_path)
        raise HTTPException(status_code=500, detail="Error reading file")

    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

    return FileContentResponse(
        path=path,
        content=content,
        language=_detect_language(path),
        size_bytes=stat.st_size,
        line_count=line_count,
    )


@router.get("/tree/{path:path}", response_model=FileTreeResponse)
async def get_file_tree(
    project_id: str,
    path: str = "",
    branch: BranchParam = "",
) -> FileTreeResponse:
    """List directory entries."""
    svc = await get_service_or_404(project_id)
    abs_path = _resolve_path(svc.project_dir, path) if path else svc.project_dir

    if not os.path.isdir(abs_path):
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")

    entries: list[TreeEntry] = []
    try:
        for entry in sorted(os.scandir(abs_path), key=lambda e: (not e.is_dir(), e.name)):
            # Skip hidden files and common noise
            if entry.name.startswith(".") or entry.name in {"__pycache__", "node_modules", ".git"}:
                continue
            if entry.is_dir(follow_symlinks=False):
                entries.append(TreeEntry(name=entry.name, type="dir"))
            elif entry.is_file(follow_symlinks=False):
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = None
                entries.append(TreeEntry(
                    name=entry.name,
                    type="file",
                    size_bytes=size,
                    language=_detect_language(entry.name),
                ))
    except OSError:
        logger.exception("Error reading directory %s", abs_path)
        raise HTTPException(status_code=500, detail="Error reading directory")

    return FileTreeResponse(path=path or ".", entries=entries)


@router.get("/tree", response_model=FileTreeResponse)
async def get_root_tree(
    project_id: str,
    branch: BranchParam = "",
) -> FileTreeResponse:
    """List root directory entries."""
    return await get_file_tree(project_id, path="", branch=branch)
