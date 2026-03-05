"""Semantic search manager.

Indexes codebase content into embeddings and provides natural language
search over code. Gracefully degrades to keyword matching when no
embedding provider is available.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SemanticSearchResult:
    """A single semantic search result."""

    file_path: str
    chunk_type: str  # "file", "function", "class"
    name: str
    text: str
    score: float


@dataclass(slots=True)
class SemanticSearchManager:
    """Manages semantic search over a codebase.

    Usage::

        mgr = SemanticSearchManager(root_dir="/path/to/repo")
        mgr.index()  # Build embeddings (once)
        results = mgr.search("authentication middleware", top_k=10)
    """

    root_dir: str
    _provider: Any = field(default=None, repr=False)
    _store: Any = field(default=None, repr=False)
    _indexed: bool = field(default=False, repr=False)
    _keyword_fallback: bool = field(default=False, repr=False)
    _reindex_queue: queue.Queue[str] = field(default_factory=queue.Queue, repr=False)
    _reindex_pending: set[str] = field(default_factory=set, repr=False)
    _reindex_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _reindex_worker_started: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        from attocode.integrations.context.embeddings import (
            NullEmbeddingProvider,
            create_embedding_provider,
        )
        self._provider = create_embedding_provider()
        self._keyword_fallback = isinstance(self._provider, NullEmbeddingProvider)

        if not self._keyword_fallback:
            from attocode.integrations.context.vector_store import VectorStore
            db_dir = os.path.join(self.root_dir, ".attocode", "vectors")
            os.makedirs(db_dir, exist_ok=True)
            self._store = VectorStore(
                db_path=os.path.join(db_dir, "embeddings.db"),
                dimension=self._provider.dimension(),
            )

    def _start_reindex_worker(self) -> None:
        """Start the background reindex worker once."""
        with self._reindex_lock:
            if self._reindex_worker_started:
                return
            self._reindex_worker_started = True

        worker = threading.Thread(
            target=self._reindex_worker_loop,
            daemon=True,
            name="semantic-reindex-worker",
        )
        worker.start()

    def _reindex_worker_loop(self) -> None:
        """Background worker for bounded, queued file reindexing."""
        while True:
            rel_path = self._reindex_queue.get()
            try:
                self.reindex_file(rel_path)
            except Exception:
                logger.debug("queue_reindex_failed: %s", rel_path, exc_info=True)
            finally:
                with self._reindex_lock:
                    self._reindex_pending.discard(rel_path)
                self._reindex_queue.task_done()

    def queue_reindex(self, file_path: str) -> None:
        """Queue a file for background reindex with de-duplication."""
        if self._keyword_fallback or not self._store:
            return
        try:
            rel = os.path.relpath(file_path, self.root_dir)
        except ValueError:
            rel = file_path

        self._start_reindex_worker()
        with self._reindex_lock:
            if rel in self._reindex_pending:
                return
            self._reindex_pending.add(rel)
        self._reindex_queue.put(rel)

    @property
    def is_available(self) -> bool:
        """Check if semantic search is fully available."""
        return not self._keyword_fallback

    @property
    def provider_name(self) -> str:
        return self._provider.name if self._provider else "none"

    def index(self, context_manager: Any = None) -> int:
        """Build or update the vector index.

        Args:
            context_manager: Optional CodebaseContextManager for file discovery.

        Returns:
            Number of chunks indexed.
        """
        if self._keyword_fallback:
            logger.info("Semantic search: no provider, skipping indexing")
            return 0

        from attocode.integrations.context.codebase_context import (
            CodebaseContextManager,
        )
        from attocode.integrations.context.vector_store import VectorEntry

        ctx = context_manager or CodebaseContextManager(root_dir=self.root_dir)
        ctx._ensure_fresh()
        if not ctx._files:
            ctx.discover_files()

        # Supported languages: Python, JS, TS always; others when tree-sitter available
        _ts_langs: set[str] = set()
        try:
            from attocode.integrations.context.ts_parser import supported_languages
            _ts_langs = set(supported_languages())
        except ImportError:
            pass
        _supported = {"python", "javascript", "typescript"} | _ts_langs

        chunks: list[tuple[str, str, str, str]] = []

        for f in ctx._files:
            if f.language not in _supported:
                continue
            file_chunks = self._chunk_single_file(f.relative_path, f.path)
            chunks.extend(file_chunks)

        if not chunks:
            return 0

        # Batch embed
        texts = [c[3] for c in chunks]
        batch_size = 64
        all_vectors: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                vectors = self._provider.embed(batch)
                all_vectors.extend(vectors)
            except Exception:
                logger.warning("Embedding batch failed at offset %d", i, exc_info=True)
                all_vectors.extend([[] for _ in batch])

        # Store
        entries = []
        for (cid, fpath, ctype, text), vec in zip(chunks, all_vectors):
            if not vec:
                continue
            entries.append(VectorEntry(
                id=cid,
                file_path=fpath,
                chunk_type=ctype,
                name=cid.split(":")[-1] if ":" in cid else fpath,
                text=text,
                vector=vec,
            ))

        if entries:
            self._store.upsert_batch(entries)

        # Update metadata for indexed files
        indexed_files: dict[str, int] = {}
        for e in entries:
            indexed_files[e.file_path] = indexed_files.get(e.file_path, 0) + 1
        for f in ctx._files:
            if f.relative_path in indexed_files:
                try:
                    mtime = os.path.getmtime(f.path)
                except OSError:
                    mtime = 0.0
                self._store.set_file_metadata(
                    f.relative_path, mtime, indexed_files[f.relative_path],
                )

        self._indexed = True
        logger.info("Semantic search: indexed %d chunks from %d files",
                     len(entries), len(ctx._files))
        return len(entries)

    def search(
        self,
        query: str,
        top_k: int = 10,
        file_filter: str = "",
        two_stage: bool = True,
    ) -> list[SemanticSearchResult]:
        """Search the codebase by natural language query.

        Uses two-stage retrieval when vector search is available:
        1. Wide recall: vector top-50 + keyword top-50
        2. Merge with Reciprocal Rank Fusion (RRF)

        This approach outperforms single-stage search on code retrieval
        benchmarks by combining semantic similarity with keyword matching.

        Args:
            query: Natural language search query.
            top_k: Number of results to return.
            file_filter: Optional glob pattern (e.g. "*.py").
            two_stage: Whether to use two-stage retrieval (default True).

        Returns:
            List of search results sorted by relevance.
        """
        if self._keyword_fallback:
            return self._keyword_search(query, top_k, file_filter)

        # Auto-index if needed (may be slow on large codebases —
        # for large projects, call index() explicitly at agent startup)
        if not self._indexed and self._store and self._store.count() == 0:
            logger.info("Semantic search: auto-indexing codebase (this may take a moment)...")
            self.index()

        # Embed query
        try:
            query_vectors = self._provider.embed([query])
            if not query_vectors or not query_vectors[0]:
                return self._keyword_search(query, top_k, file_filter)
            query_vec = query_vectors[0]
        except Exception:
            logger.warning("Query embedding failed, falling back to keyword", exc_info=True)
            return self._keyword_search(query, top_k, file_filter)

        # Stage 1a: Vector search (wide recall)
        wide_k = max(top_k * 5, 50) if two_stage else top_k
        raw_results = self._store.search(query_vec, top_k=wide_k, file_filter=file_filter)

        if not two_stage or not raw_results:
            return [
                SemanticSearchResult(
                    file_path=r.file_path,
                    chunk_type=r.chunk_type,
                    name=r.name,
                    text=r.text,
                    score=r.score,
                )
                for r in raw_results[:top_k]
            ]

        # Stage 1b: Keyword search (complementary recall)
        keyword_results = self._keyword_search(query, top_k=wide_k, file_filter=file_filter)

        # Stage 2: Reciprocal Rank Fusion
        from attocode.integrations.context.ast_chunker import reciprocal_rank_fusion

        vector_ranked = [(r.id, r.score) for r in raw_results]
        keyword_ranked = [(r.file_path, r.score) for r in keyword_results]

        fused = reciprocal_rank_fusion(vector_ranked, keyword_ranked)

        # Build result lookup for fast access
        result_map: dict[str, SemanticSearchResult] = {}
        for r in raw_results:
            result_map[r.id] = SemanticSearchResult(
                file_path=r.file_path,
                chunk_type=r.chunk_type,
                name=r.name,
                text=r.text,
                score=r.score,
            )
        for r in keyword_results:
            if r.file_path not in result_map:
                result_map[r.file_path] = r

        # Return top-k by fused score
        merged: list[SemanticSearchResult] = []
        for item_id, fused_score in fused[:top_k]:
            result = result_map.get(item_id)
            if result:
                result.score = round(fused_score, 4)
                merged.append(result)

        return merged

    def _keyword_search(
        self,
        query: str,
        top_k: int,
        file_filter: str,
    ) -> list[SemanticSearchResult]:
        """Fallback keyword-based search using CodebaseContextManager."""
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        ctx = CodebaseContextManager(root_dir=self.root_dir)
        files = ctx.select_context(query=query, strategy="relevance", max_files=top_k)

        results = []
        for f in files:
            if file_filter:
                import fnmatch
                if not fnmatch.fnmatch(f.relative_path, file_filter):
                    continue
            results.append(SemanticSearchResult(
                file_path=f.relative_path,
                chunk_type="file",
                name=os.path.basename(f.relative_path),
                text=f"[keyword match] {f.language} ({f.line_count}L)",
                score=round(f.importance, 4),
            ))

        return results[:top_k]

    def _chunk_single_file(
        self, rel_path: str, abs_path: str,
    ) -> list[tuple[str, str, str, str]]:
        """Extract chunks from a single file.

        Returns list of (id, file_path, chunk_type, text) tuples.
        """
        from attocode.integrations.context.codebase_ast import parse_file

        try:
            ast = parse_file(abs_path)
        except Exception:
            return []

        chunks: list[tuple[str, str, str, str]] = []

        # File-level summary
        imports = [imp.module for imp in ast.imports[:10]]
        symbols = ast.get_symbols()[:10]
        summary_parts = []
        if ast.docstring:
            summary_parts.append(ast.docstring[:200])
        if imports:
            summary_parts.append(f"imports: {', '.join(imports)}")
        if symbols:
            summary_parts.append(f"defines: {', '.join(symbols)}")
        if summary_parts:
            chunks.append((
                f"file:{rel_path}",
                rel_path,
                "file",
                " | ".join(summary_parts),
            ))

        # Function-level chunks
        for func in ast.functions:
            text_parts = [f"function {func.name}"]
            if func.docstring:
                text_parts.append(func.docstring[:150])
            params = ", ".join(p.name for p in func.parameters[:8])
            if params:
                text_parts.append(f"params: {params}")
            if func.return_type:
                text_parts.append(f"returns: {func.return_type}")
            chunks.append((
                f"func:{rel_path}:{func.name}",
                rel_path,
                "function",
                " | ".join(text_parts),
            ))

        # Class-level chunks (including method-level)
        for cls in ast.classes:
            text_parts = [f"class {cls.name}"]
            if cls.bases:
                text_parts.append(f"extends: {', '.join(cls.bases)}")
            if cls.docstring:
                text_parts.append(cls.docstring[:150])
            methods = [m.name for m in cls.methods[:8]]
            if methods:
                text_parts.append(f"methods: {', '.join(methods)}")
            chunks.append((
                f"cls:{rel_path}:{cls.name}",
                rel_path,
                "class",
                " | ".join(text_parts),
            ))

            # Method-level chunks for richer search
            for method in cls.methods:
                m_parts = [f"method {cls.name}.{method.name}"]
                if method.docstring:
                    m_parts.append(method.docstring[:150])
                m_params = ", ".join(p.name for p in method.parameters[:8])
                if m_params:
                    m_parts.append(f"params: {m_params}")
                if method.return_type:
                    m_parts.append(f"returns: {method.return_type}")
                chunks.append((
                    f"method:{rel_path}:{cls.name}.{method.name}",
                    rel_path,
                    "method",
                    " | ".join(m_parts),
                ))

        return chunks

    def reindex_file(self, file_path: str) -> int:
        """Re-index a single file: delete old vectors and re-embed.

        Args:
            file_path: Absolute or relative path to the file.

        Returns:
            Number of chunks indexed (0 if skipped).
        """
        if self._keyword_fallback or not self._store:
            return 0

        from attocode.integrations.context.vector_store import VectorEntry

        try:
            rel = os.path.relpath(file_path, self.root_dir)
        except ValueError:
            rel = file_path

        abs_path = os.path.join(self.root_dir, rel) if not os.path.isabs(file_path) else file_path

        if not os.path.isfile(abs_path):
            # File was deleted — just remove vectors
            self._store.delete_by_file(rel)
            self._store.delete_file_metadata(rel)
            return 0

        # Re-chunk
        chunks = self._chunk_single_file(rel, abs_path)
        if not chunks:
            self._store.delete_by_file(rel)
            self._store.delete_file_metadata(rel)
            return 0

        # Embed FIRST (before deleting old vectors) — if embed fails,
        # we keep existing vectors rather than losing them
        texts = [c[3] for c in chunks]
        try:
            vectors = self._provider.embed(texts)
        except Exception:
            logger.warning(
                "reindex_file embed failed for %s, keeping old vectors",
                rel, exc_info=True,
            )
            return 0

        # Build entries
        entries = []
        for (cid, fpath, ctype, text), vec in zip(chunks, vectors):
            if not vec:
                continue
            entries.append(VectorEntry(
                id=cid,
                file_path=fpath,
                chunk_type=ctype,
                name=cid.split(":")[-1] if ":" in cid else fpath,
                text=text,
                vector=vec,
            ))

        # Now safe to delete old + upsert new
        self._store.delete_by_file(rel)
        if entries:
            self._store.upsert_batch(entries)

        # Update metadata
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            mtime = 0.0
        self._store.set_file_metadata(rel, mtime, len(entries))

        logger.debug("reindex_file: %s -> %d chunks", rel, len(entries))
        self._indexed = True
        return len(entries)

    def invalidate_file(self, file_path: str) -> None:
        """Remove embeddings for a changed file."""
        if self._store:
            try:
                rel = os.path.relpath(file_path, self.root_dir)
            except ValueError:
                rel = file_path
            self._store.delete_by_file(rel)

    def reindex_stale_files(self, context_manager: Any = None) -> int:
        """Re-index only files whose mtime has changed since last indexing.

        Designed to be called on agent startup for incremental freshness.

        Returns:
            Number of chunks re-indexed.
        """
        if self._keyword_fallback or not self._store:
            return 0

        from attocode.integrations.context.codebase_context import (
            CodebaseContextManager,
        )

        ctx = context_manager or CodebaseContextManager(root_dir=self.root_dir)
        ctx._ensure_fresh()
        if not ctx._files:
            ctx.discover_files()

        # Build mtime map for all discovered files
        file_mtimes: dict[str, float] = {}
        file_paths: dict[str, str] = {}  # rel -> abs
        for f in ctx._files:
            try:
                file_mtimes[f.relative_path] = os.path.getmtime(f.path)
                file_paths[f.relative_path] = f.path
            except OSError:
                continue

        stale = self._store.get_stale_files(file_mtimes)

        # Clean up vectors for files that have been deleted from disk
        all_indexed = self._store.get_all_indexed_files()
        current_files = set(file_mtimes.keys())
        deleted_count = 0
        for indexed_path in all_indexed:
            if indexed_path not in current_files:
                self._store.delete_by_file(indexed_path)
                self._store.delete_file_metadata(indexed_path)
                deleted_count += 1
                logger.debug("Cleaned up vectors for deleted file: %s", indexed_path)

        if not stale and not deleted_count:
            logger.debug("reindex_stale_files: all files up to date")
            return 0

        if deleted_count:
            logger.info("reindex_stale_files: cleaned up %d deleted files", deleted_count)

        logger.info("reindex_stale_files: %d stale files to re-index", len(stale))
        total_chunks = 0
        for rel_path in stale:
            abs_path = file_paths.get(rel_path)
            if abs_path:
                total_chunks += self.reindex_file(abs_path)

        self._indexed = True
        return total_chunks

    def close(self) -> None:
        """Close the vector store."""
        if self._store:
            self._store.close()

    def format_results(self, results: list[SemanticSearchResult]) -> str:
        """Format search results as human-readable text."""
        if not results:
            return "No results found."

        lines = [f"Semantic search results ({len(results)}):"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"  {i}. [{r.chunk_type}] {r.file_path}"
                f" — {r.name} (score: {r.score:.3f})"
            )
            if r.text:
                # Show first 120 chars of text
                preview = r.text[:120]
                if len(r.text) > 120:
                    preview += "..."
                lines.append(f"     {preview}")
        return "\n".join(lines)
