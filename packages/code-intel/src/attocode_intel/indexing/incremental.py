"""Content-hash-gated incremental update pipeline.

This is the core pipeline that processes file changes from hook notifications.
It reads file content, computes SHA-256, compares to the current branch manifest,
and only re-parses/re-indexes files whose content has actually changed.

Flow:
    paths → read content → hash → compare to manifest → skip unchanged
    → store new content → parse symbols/references → update overlay → queue embeddings
    → publish event
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from attocode_intel.indexing.parser import (
    detect_language,
    extract_imports,
    extract_references,
    extract_symbols,
)

if TYPE_CHECKING:
    import uuid

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
    5. Atomically stores symbols and references for changed content
    6. Publishes branch overlay only after successful extraction
    7. Queues embedding generation for new content
    8. Returns stats about what changed
    """

    def __init__(self, session: AsyncSession) -> None:
        from attocode_intel.storage.branch_overlay import BranchOverlay
        from attocode_intel.storage.content_store import ContentStore
        from attocode_intel.storage.embedding_store import EmbeddingStore
        from attocode_intel.storage.symbol_store import SymbolStore

        self._session = session
        from attocode_intel.storage.dependency_store import DependencyStore

        self._content_store = ContentStore(session)
        self._symbol_store = SymbolStore(session)
        self._embedding_store = EmbeddingStore(session)
        self._overlay = BranchOverlay(session)
        self._dep_store = DependencyStore(session)

    @staticmethod
    async def acquire_branch_lock(session: AsyncSession, branch_id: uuid.UUID) -> None:
        """Acquire a PostgreSQL advisory lock for a branch to prevent concurrent indexing."""
        from sqlalchemy import text

        lock_key = int.from_bytes(branch_id.bytes[:8], "big") & 0x7FFFFFFFFFFFFFFF
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)").bindparams(key=lock_key)
        )

    async def process_file_changes(
        self,
        branch_id: uuid.UUID,
        paths: list[str],
        base_dir: str | None = None,
        git_reader: object | None = None,
        repo_id: str | None = None,
        ref: str | None = None,
        file_contents: dict[str, bytes] | None = None,
    ) -> dict:
        """Process a batch of file changes for a branch.

        Content sources (checked in order):
        1. file_contents — inline content sent by the client (remote mode)
        2. base_dir — read from local filesystem
        3. git_reader+repo_id+ref — read from git

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
            "references_updated": 0,
            "errors": 0,
        }

        # Acquire advisory lock to prevent concurrent indexing on same branch
        if self._session.get_bind().dialect.name == "postgresql":
            await self.acquire_branch_lock(self._session, branch_id)

        # Get current manifest for comparison
        manifest = await self._overlay.resolve_manifest(branch_id)

        # Batch: collect files to update
        overlay_updates: list[tuple[str, str, str]] = []  # (path, sha, status)

        needs_embedding = False
        for path in dict.fromkeys(paths):
            try:
                content = await self._read_file(path, base_dir, git_reader, repo_id, ref, file_contents=file_contents)

                if content is None:
                    # File was deleted
                    if path in manifest:
                        async with self._session.begin_nested():
                            await self._overlay.delete_file(branch_id, path)
                        manifest.pop(path)
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

                # Do not publish a new manifest entry after a parse/SQL failure.
                # The savepoint also leaves the rest of the batch usable on PostgreSQL.
                language = detect_language(path)
                symbol_count = reference_count = dependency_count = 0
                missing_embedding = False
                async with self._session.begin_nested():
                    await self._content_store.store(content, language)
                    symbols = extract_symbols(content, path)
                    if symbols:
                        symbol_count = await self._symbol_store.upsert_symbols(
                            sha, symbols, skip_if_exists=True
                        )
                    if language in ("python", "javascript", "typescript"):
                        refs = extract_references(content, path)
                        reference_count = await self._symbol_store.replace_references(sha, refs)

                    # This persisted graph is a content-addressed cache. Impact
                    # queries resolve imports against current branch paths.
                    imports = extract_imports(content, path, language)
                    if imports and not await self._dep_store.has_dependencies(sha):
                        from attocode_intel.indexing.full_indexer import _resolve_import_path

                        path_to_sha = {**manifest, path: sha}
                        known_paths = set(path_to_sha)
                        python_index = None
                        if language == "python":
                            from attocode_intel._internal.integrations.context.codebase_context import (
                                python_module_index,
                            )
                            python_index = python_module_index(known_paths)
                        deps = []
                        for imp in imports:
                            target = _resolve_import_path(imp, path, known_paths, language,
                                                          python_index=python_index)
                            if target and target in path_to_sha:
                                deps.append({"target_sha": path_to_sha[target],
                                             "dep_type": "import", "weight": 1.0})
                        if deps:
                            dependency_count = await self._dep_store.upsert_dependencies(sha, deps)

                    if repo_id:
                        missing_embedding = not await self._embedding_store.has_embeddings(sha)

                needs_embedding = needs_embedding or missing_embedding
                status = "added" if path not in manifest else "modified"
                overlay_updates.append((path, sha, status))
                manifest[path] = sha
                stats["symbols_updated"] += symbol_count
                stats["references_updated"] += reference_count
                if dependency_count:
                    stats["dependencies_extracted"] = stats.get("dependencies_extracted", 0) + dependency_count

                stats["processed"] += 1

            except Exception as e:
                logger.warning("Error processing %s: %s", path, e)
                stats["errors"] += 1

        # Batch update overlay (single version bump)
        if overlay_updates:
            await self._overlay.set_files_batch(branch_id, overlay_updates)

        if needs_embedding and repo_id:
            from attocode_intel.workers.job_utils import enqueue_embedding_job
            await enqueue_embedding_job(repo_id, ref or "main")

        return stats

    async def _read_file(
        self,
        path: str,
        base_dir: str | None,
        git_reader: object | None,
        repo_id: str | None,
        ref: str | None,
        file_contents: dict[str, bytes] | None = None,
    ) -> bytes | None:
        """Read file content from inline content, disk, or git.

        Content sources (checked in order):
        1. file_contents — inline content sent by the client
        2. base_dir — local filesystem
        3. git_reader — git object reader

        Returns None if file doesn't exist (deleted) or no content source available.
        C1 fix: Validates resolved path is within base_dir to prevent path traversal.
        """
        # Priority 1: inline content (sent by client for remote servers)
        if file_contents is not None and path in file_contents:
            return file_contents[path]

        # Priority 2: local filesystem
        if base_dir:
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
            except FileNotFoundError:
                return None

        # Priority 3: git reader
        if git_reader and repo_id and ref:
            try:
                return git_reader.read_file(repo_id, ref, path)  # type: ignore[union-attr]
            except FileNotFoundError:
                return None

        # No content source — file is missing or deleted
        return None
