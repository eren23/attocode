"""Semantic search manager.

Indexes codebase content into embeddings and provides natural language
search over code. Gracefully degrades to keyword matching when no
embedding provider is available.
"""

from __future__ import annotations

import logging
import os
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

        from attocode.integrations.context.codebase_ast import parse_file
        from attocode.integrations.context.codebase_context import (
            CodebaseContextManager,
        )
        from attocode.integrations.context.vector_store import VectorEntry

        ctx = context_manager or CodebaseContextManager(root_dir=self.root_dir)
        ctx._ensure_fresh()
        if not ctx._files:
            ctx.discover_files()

        chunks: list[tuple[str, str, str, str]] = []  # (id, file_path, chunk_type, text)

        for f in ctx._files:
            if f.language not in ("python", "javascript", "typescript"):
                continue

            # File-level summary
            try:
                ast = parse_file(f.path)
            except Exception:
                continue

            # Build file summary
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
                    f"file:{f.relative_path}",
                    f.relative_path,
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
                    f"func:{f.relative_path}:{func.name}",
                    f.relative_path,
                    "function",
                    " | ".join(text_parts),
                ))

            # Class-level chunks
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
                    f"cls:{f.relative_path}:{cls.name}",
                    f.relative_path,
                    "class",
                    " | ".join(text_parts),
                ))

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

        self._indexed = True
        logger.info("Semantic search: indexed %d chunks from %d files",
                     len(entries), len(ctx._files))
        return len(entries)

    def search(
        self,
        query: str,
        top_k: int = 10,
        file_filter: str = "",
    ) -> list[SemanticSearchResult]:
        """Search the codebase by natural language query.

        Args:
            query: Natural language search query.
            top_k: Number of results to return.
            file_filter: Optional glob pattern (e.g. "*.py").

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

        # Search vector store
        raw_results = self._store.search(query_vec, top_k=top_k, file_filter=file_filter)

        return [
            SemanticSearchResult(
                file_path=r.file_path,
                chunk_type=r.chunk_type,
                name=r.name,
                text=r.text,
                score=r.score,
            )
            for r in raw_results
        ]

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

    def invalidate_file(self, file_path: str) -> None:
        """Remove embeddings for a changed file."""
        if self._store:
            try:
                rel = os.path.relpath(file_path, self.root_dir)
            except ValueError:
                rel = file_path
            self._store.delete_by_file(rel)

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
