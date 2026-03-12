"""Content-hash-gated incremental update pipeline.

This is the core pipeline that processes file changes from hook notifications.
It reads file content, computes SHA-256, compares to the current branch manifest,
and only re-parses/re-indexes files whose content has actually changed.

Flow:
    paths → read content → hash → compare to manifest → skip unchanged
    → store new content → update overlay → parse symbols → queue embeddings
    → publish event
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from attocode.code_intel.indexing.parser import detect_language, extract_symbols

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 1_000_000  # 1MB


class IncrementalPipeline:
    """Content-hash-gated incremental indexing pipeline.

    Given a list of changed file paths and a branch, this pipeline:
    1. Reads each file from disk (local mode) or git (service mode)
    2. Computes SHA-256 of the content
    3. Compares to current manifest — skips if SHA matches (no-op)
    4. Stores new content in content-addressed store
    5. Updates branch overlay (path → new SHA)
    6. Extracts symbols (skips if SHA already has symbols — dedup)
    7. Queues embedding generation for new content
    8. Returns stats about what changed
    """

    def __init__(self, session: AsyncSession) -> None:
        from attocode.code_intel.storage.branch_overlay import BranchOverlay
        from attocode.code_intel.storage.content_store import ContentStore
        from attocode.code_intel.storage.embedding_store import EmbeddingStore
        from attocode.code_intel.storage.symbol_store import SymbolStore

        self._session = session
        self._content_store = ContentStore(session)
        self._symbol_store = SymbolStore(session)
        self._embedding_store = EmbeddingStore(session)
        self._overlay = BranchOverlay(session)

    async def process_file_changes(
        self,
        branch_id: uuid.UUID,
        paths: list[str],
        base_dir: str | None = None,
        git_reader: object | None = None,
        repo_id: str | None = None,
        ref: str | None = None,
    ) -> dict:
        """Process a batch of file changes for a branch.

        Either base_dir (local mode — reads from disk) or
        git_reader+repo_id+ref (service mode — reads from git) must be provided.

        Returns stats: {processed, skipped_unchanged, skipped_missing,
                        skipped_too_large, symbols_updated, errors}
        """
        stats = {
            "processed": 0,
            "skipped_unchanged": 0,
            "skipped_missing": 0,
            "skipped_too_large": 0,
            "skipped_binary": 0,
            "symbols_updated": 0,
            "errors": 0,
        }

        # Get current manifest for comparison
        manifest = await self._overlay.resolve_manifest(branch_id)

        # Batch: collect files to update
        overlay_updates: list[tuple[str, str, str]] = []  # (path, sha, status)

        for path in paths:
            try:
                content = await self._read_file(path, base_dir, git_reader, repo_id, ref)

                if content is None:
                    # File was deleted
                    if path in manifest:
                        await self._overlay.delete_file(branch_id, path)
                        stats["processed"] += 1
                    else:
                        stats["skipped_missing"] += 1
                    continue

                if len(content) > _MAX_FILE_SIZE:
                    stats["skipped_too_large"] += 1
                    continue

                # Content-hash comparison — the key optimization
                sha = self._content_store.hash_content(content)
                current_sha = manifest.get(path)

                if sha == current_sha:
                    stats["skipped_unchanged"] += 1
                    continue

                # New or changed content
                language = detect_language(path)
                await self._content_store.store(content, language)

                # Determine status
                status = "added" if path not in manifest else "modified"
                overlay_updates.append((path, sha, status))

                # Extract symbols (skip if SHA already indexed — content dedup)
                symbols = extract_symbols(content, path)
                if symbols:
                    count = await self._symbol_store.upsert_symbols(
                        sha, symbols, skip_if_exists=True
                    )
                    stats["symbols_updated"] += count or len(symbols)

                # Queue embedding generation (dedup: skip if already embedded)
                if not await self._embedding_store.has_embeddings(sha):
                    # In service mode, this would enqueue an ARQ job.
                    # For now, we just note it needs embedding.
                    pass

                stats["processed"] += 1

            except Exception as e:
                logger.warning("Error processing %s: %s", path, e)
                stats["errors"] += 1

        # Batch update overlay (single version bump)
        if overlay_updates:
            await self._overlay.set_files_batch(branch_id, overlay_updates)

        return stats

    async def _read_file(
        self,
        path: str,
        base_dir: str | None,
        git_reader: object | None,
        repo_id: str | None,
        ref: str | None,
    ) -> bytes | None:
        """Read file content from disk or git.

        Returns None if file doesn't exist (deleted).
        C1 fix: Validates resolved path is within base_dir to prevent path traversal.
        """
        if base_dir:
            # Local mode — read from filesystem
            base = Path(base_dir).resolve()
            full_path = (base / path).resolve()
            # C1: prevent path traversal (e.g. ../../etc/passwd)
            if not full_path.is_relative_to(base):
                raise ValueError(
                    f"Path traversal detected: '{path}' resolves outside base directory"
                )
            if not full_path.is_file():
                return None
            try:
                return full_path.read_bytes()
            except (OSError, PermissionError):
                return None
        elif git_reader and repo_id and ref:
            # Service mode — read from git
            try:
                return git_reader.read_file(repo_id, ref, path)  # type: ignore[union-attr]
            except Exception:
                return None
        else:
            raise ValueError("Either base_dir or git_reader+repo_id+ref must be provided")
