"""Full indexer — reads all files from git tree, indexes content, symbols, deps.

Uses content-addressed storage: files with the same content across branches
are stored and indexed only once.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Callable

from attocode.code_intel.indexing.parser import detect_language, extract_symbols

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from attocode.code_intel.git.manager import GitRepoManager

logger = logging.getLogger(__name__)

# Skip binary/large files
_SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2",
                    ".ttf", ".eot", ".pdf", ".zip", ".tar", ".gz", ".bin", ".exe",
                    ".dll", ".so", ".dylib", ".pyc", ".pyo", ".class", ".o"}
_MAX_FILE_SIZE = 1_000_000  # 1MB


class FullIndexer:
    """Full repository indexer.

    Reads all files from a git tree at a specific ref, computes content hashes,
    extracts symbols, and stores everything in content-addressed storage.

    Content dedup: if a file's content has already been stored (from another
    branch or previous indexing), the content, symbols, and embeddings are
    reused automatically via SHA-256 keying.
    """

    def __init__(
        self,
        session: AsyncSession,
        git_manager: GitRepoManager,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> None:
        self._session = session
        self._git = git_manager
        self._progress = progress_callback or (lambda _: None)

    async def index(
        self,
        repo_id: str,
        branch_id: uuid.UUID,
        ref: str = "main",
    ) -> dict:
        """Perform a full index of a branch.

        Returns stats dict: {files_indexed, symbols_found, skipped_existing,
                            errors, duration_ms}.
        """
        import time

        from attocode.code_intel.storage.branch_overlay import BranchOverlay
        from attocode.code_intel.storage.content_store import ContentStore
        from attocode.code_intel.storage.symbol_store import SymbolStore

        start = time.monotonic()
        content_store = ContentStore(self._session)
        symbol_store = SymbolStore(self._session)
        overlay = BranchOverlay(self._session)

        stats = {
            "files_indexed": 0,
            "symbols_found": 0,
            "skipped_existing": 0,
            "skipped_binary": 0,
            "errors": 0,
        }

        # Get all files from git tree recursively
        all_files = self._walk_tree(repo_id, ref)
        total = len(all_files)

        self._progress({"phase": "indexing", "total": total, "current": 0})

        # Batch overlay updates
        overlay_updates: list[tuple[str, str, str]] = []

        for i, (path, oid) in enumerate(all_files):
            try:
                # Skip binary/large files
                ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
                if ext.lower() in _SKIP_EXTENSIONS:
                    stats["skipped_binary"] += 1
                    continue

                content = self._git.read_file(repo_id, ref, path)
                if len(content) > _MAX_FILE_SIZE:
                    stats["skipped_binary"] += 1
                    continue

                # Content-addressed storage — dedup across branches
                language = detect_language(path)
                sha = await content_store.store(content, language)
                overlay_updates.append((path, sha, "added"))

                # Extract symbols (skip if SHA already has symbols — cross-branch dedup)
                symbols = extract_symbols(content, path)
                if symbols:
                    count = await symbol_store.upsert_symbols(
                        sha, symbols, skip_if_exists=True
                    )
                    if count == 0:
                        stats["skipped_existing"] += 1
                    else:
                        stats["symbols_found"] += count

                stats["files_indexed"] += 1

                if (i + 1) % 100 == 0:
                    self._progress({"phase": "indexing", "total": total, "current": i + 1})
                    # Flush batch overlay updates periodically
                    if overlay_updates:
                        await overlay.set_files_batch(branch_id, overlay_updates)
                        overlay_updates = []
                    await self._session.flush()

            except Exception as e:
                logger.warning("Error indexing %s: %s", path, e)
                stats["errors"] += 1

        # Final batch
        if overlay_updates:
            await overlay.set_files_batch(branch_id, overlay_updates)

        await self._session.commit()

        duration_ms = int((time.monotonic() - start) * 1000)
        stats["duration_ms"] = duration_ms

        self._progress({"phase": "completed", "stats": stats})
        logger.info(
            "Full index complete: %d files, %d symbols, %d reused, %d errors in %dms",
            stats["files_indexed"], stats["symbols_found"],
            stats["skipped_existing"], stats["errors"], duration_ms,
        )
        return stats

    def _walk_tree(self, repo_id: str, ref: str, path: str = "") -> list[tuple[str, str]]:
        """Recursively walk the git tree and return (path, oid) pairs."""
        entries = self._git.get_tree(repo_id, ref, path)
        files: list[tuple[str, str]] = []

        for entry in entries:
            if entry.type == "blob":
                files.append((entry.path, entry.oid))
            elif entry.type == "tree":
                files.extend(self._walk_tree(repo_id, ref, entry.path))

        return files
