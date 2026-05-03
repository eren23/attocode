"""Delta indexer — processes only changed files between two refs.

Uses content-hash comparison to skip files whose content hasn't actually changed
(e.g., git reports a mode change but the content is identical).
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

_MAX_FILE_SIZE = 1_000_000


class DeltaIndexer:
    """Delta indexer — only processes changed files.

    Computes the git diff between the previously indexed commit and the
    current HEAD, then processes only additions, modifications, and deletions.

    Content-hash gating: even for files git reports as changed, we compare
    the SHA-256 of the new content to the existing manifest entry. If the
    content hash matches, we skip re-parsing (idempotent).
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
        from_ref: str,
        to_ref: str,
    ) -> dict:
        """Perform a delta index between two refs.

        Returns stats dict: {added, modified, deleted, skipped_unchanged,
                            symbols_updated, errors, duration_ms}.
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
            "added": 0,
            "modified": 0,
            "deleted": 0,
            "skipped_unchanged": 0,
            "symbols_updated": 0,
            "errors": 0,
        }

        # Get current manifest for content-hash comparison
        manifest = await overlay.resolve_manifest(branch_id)

        diff_entries = self._git.get_diff(repo_id, from_ref, to_ref)
        total = len(diff_entries)

        self._progress({"phase": "delta_indexing", "total": total, "current": 0})

        # Batch overlay updates for single version bump
        overlay_updates: list[tuple[str, str, str]] = []

        for i, entry in enumerate(diff_entries):
            try:
                if entry.status == "deleted":
                    await overlay.delete_file(branch_id, entry.path)
                    stats["deleted"] += 1
                elif entry.status in ("added", "modified"):
                    content = self._git.read_file(repo_id, to_ref, entry.path)
                    if len(content) > _MAX_FILE_SIZE:
                        continue

                    # Content-hash gating
                    sha = content_store.hash_content(content)
                    if sha == manifest.get(entry.path):
                        stats["skipped_unchanged"] += 1
                        continue

                    language = detect_language(entry.path)
                    await content_store.store(content, language)
                    overlay_updates.append((entry.path, sha, entry.status))

                    # Extract and update symbols (skip if already indexed for this SHA)
                    symbols = extract_symbols(content, entry.path)
                    if symbols:
                        count = await symbol_store.upsert_symbols(
                            sha, symbols, skip_if_exists=True
                        )
                        stats["symbols_updated"] += count or len(symbols)

                    stats[entry.status] = stats.get(entry.status, 0) + 1
                elif entry.status == "renamed":
                    if entry.old_path:
                        await overlay.delete_file(branch_id, entry.old_path)
                    content = self._git.read_file(repo_id, to_ref, entry.path)
                    if len(content) <= _MAX_FILE_SIZE:
                        sha = content_store.hash_content(content)
                        language = detect_language(entry.path)
                        await content_store.store(content, language)
                        overlay_updates.append((entry.path, sha, "added"))
                    stats["modified"] += 1

            except Exception as e:
                logger.warning("Error delta-indexing %s: %s", entry.path, e)
                stats["errors"] += 1

            if (i + 1) % 50 == 0:
                self._progress({"phase": "delta_indexing", "total": total, "current": i + 1})

        # Batch overlay update (single version bump)
        if overlay_updates:
            await overlay.set_files_batch(branch_id, overlay_updates)

        await self._session.commit()

        duration_ms = int((time.monotonic() - start) * 1000)
        stats["duration_ms"] = duration_ms

        self._progress({"phase": "completed", "stats": stats})
        logger.info(
            "Delta index complete: +%d ~%d -%d =%d(unchanged), %d symbols in %dms",
            stats["added"], stats["modified"], stats["deleted"],
            stats["skipped_unchanged"], stats["symbols_updated"], duration_ms,
        )
        return stats
