"""Semantic search manager.

Indexes codebase content into embeddings and provides natural language
search over code. Gracefully degrades to BM25 keyword matching when no
embedding provider is available.
"""

from __future__ import annotations

import logging
import math
import os
import queue
import re
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BM25 keyword search support types
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset({
    "self", "cls", "the", "is", "in", "of", "and", "or", "to", "a", "an",
    "for", "not", "on", "with", "as", "at", "by", "from", "it", "be",
    "this", "that", "if", "else", "def", "class", "import", "return",
    "none", "true", "false", "pass", "str", "int", "float", "bool", "list",
    "dict", "set", "tuple", "any", "type", "optional",
})

_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokenize(text: str) -> list[str]:
    """Tokenize text: split camelCase/snake_case, lowercase, remove stop words."""
    # Split on non-alphanumeric first
    parts = re.split(r"[^a-zA-Z0-9]+", text)
    tokens: list[str] = []
    for part in parts:
        # Split camelCase
        sub_parts = _CAMEL_RE.sub("_", part).split("_")
        for sp in sub_parts:
            sp_lower = sp.lower()
            if len(sp_lower) >= 2 and sp_lower not in _STOP_WORDS:
                tokens.append(sp_lower)
    return tokens


@dataclass(slots=True)
class _KeywordDoc:
    """A document in the BM25 keyword index."""

    id: str              # "func:path:name" or "file:path"
    file_path: str
    chunk_type: str      # file, function, class, method
    name: str
    text: str            # preview text
    is_config: bool
    is_test: bool
    term_freqs: dict[str, int] = field(default_factory=dict)
    doc_len: int = 0


@dataclass(slots=True)
class IndexProgress:
    """Progress of background embedding indexing."""

    total_files: int = 0
    indexed_files: int = 0
    failed_files: int = 0
    status: str = "idle"  # idle, running, paused, completed, error
    coverage: float = 0.0  # indexed / total
    started_at: float = 0.0
    elapsed_seconds: float = 0.0


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
    nl_mode: str = ""  # "none" or "heuristic"; "" = read ATTOCODE_NL_EMBEDDING_MODE env var
    _provider: Any = field(default=None, repr=False)
    _store: Any = field(default=None, repr=False)
    _indexed: bool = field(default=False, repr=False)
    _keyword_fallback: bool = field(default=False, repr=False)
    _reindex_queue: queue.Queue[str] = field(default_factory=queue.Queue, repr=False)
    _reindex_pending: set[str] = field(default_factory=set, repr=False)
    _reindex_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _reindex_worker_started: bool = field(default=False, repr=False)
    _kw_docs: list[_KeywordDoc] = field(default_factory=list, repr=False)
    _kw_df: dict[str, int] = field(default_factory=dict, repr=False)
    _kw_avg_dl: float = field(default=0.0, repr=False)
    _kw_index_built: bool = field(default=False, repr=False)
    _bg_indexer: Any = field(default=None, repr=False)
    _bg_thread: Any = field(default=None, repr=False)
    _index_progress: IndexProgress = field(default_factory=IndexProgress, repr=False)
    _summarizer: Any = field(default=None, repr=False)

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

        # Resolve NL embedding mode
        if not self.nl_mode:
            self.nl_mode = os.environ.get("ATTOCODE_NL_EMBEDDING_MODE", "none")
        if self.nl_mode == "heuristic":
            from attocode.code_intel.indexing.summarizer import get_summarizer
            self._summarizer = get_summarizer()

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

        # Batch embed (use NL summaries when heuristic mode is enabled)
        texts = self._get_embedding_texts(chunks)
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

        # Store (original chunk text is preserved for display, not the NL summary)
        entries = []
        for (cid, fpath, ctype, text), vec in zip(chunks, all_vectors, strict=False):
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
        rerank: bool = False,
    ) -> list[SemanticSearchResult]:
        """Search the codebase by natural language query.

        Uses two-stage retrieval when vector search is available:
        1. Wide recall: vector top-50 + keyword top-50
        2. Score normalization (min-max to [0,1])
        3. Merge with Reciprocal Rank Fusion (RRF)
        4. Optional cross-encoder reranking

        This approach outperforms single-stage search on code retrieval
        benchmarks by combining semantic similarity with keyword matching.

        Args:
            query: Natural language search query.
            top_k: Number of results to return.
            file_filter: Optional glob pattern (e.g. "*.py").
            two_stage: Whether to use two-stage retrieval (default True).
            rerank: Whether to apply cross-encoder reranking after fusion.

        Returns:
            List of search results sorted by relevance.
        """
        if self._keyword_fallback:
            return self._keyword_search(query, top_k, file_filter)

        # Coverage-based switchover: use keyword fallback while indexing
        if not self._indexed and self._store:
            count = self._store.count()
            if count == 0 and self._bg_indexer is None:
                # No embeddings and no background indexer — use keyword fallback
                return self._keyword_search(query, top_k, file_filter)
            elif not self.is_index_ready() and self._bg_indexer is not None:
                # Indexer running but coverage < 80% — use keyword fallback
                return self._keyword_search(query, top_k, file_filter)

        # Embed query
        try:
            query_vectors = self._provider.embed([query])
            if not query_vectors or not query_vectors[0]:
                return self._keyword_search(query, top_k, file_filter)
            query_vec = query_vectors[0]
        except Exception:
            logger.warning("Query embedding failed, falling back to keyword", exc_info=True)
            return self._keyword_search(query, top_k, file_filter)

        # Build set of files that exist on disk to filter out stale branch data.
        # In local mode the filesystem is the source of truth — vectors from
        # files that no longer exist (e.g. after a branch switch) are skipped.
        existing_files: set[str] | None = None
        try:
            indexed_paths = self._store.get_all_indexed_files()
            if indexed_paths:
                existing_files = {
                    p for p in indexed_paths
                    if os.path.exists(os.path.join(self.root_dir, p))
                }
        except Exception:
            logger.debug("Failed to build existing_files set", exc_info=True)

        # Stage 1a: Vector search (wide recall)
        wide_k = max(top_k * 5, 50) if two_stage else top_k
        raw_results = self._store.search(
            query_vec, top_k=wide_k, file_filter=file_filter,
            existing_files=existing_files,
        )

        if not two_stage:
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

        # Stage 1b: Keyword search (complementary recall) — always run
        keyword_results = self._keyword_search(query, top_k=wide_k, file_filter=file_filter)

        # If both pipelines returned nothing, bail out early
        if not raw_results and not keyword_results:
            return []

        # Stage 2: Score normalization + Reciprocal Rank Fusion
        from attocode.integrations.context.ast_chunker import reciprocal_rank_fusion

        # Map chunk_type to vector ID prefix for consistent key space
        _type_prefix = {"function": "func", "class": "cls", "method": "method", "file": "file"}

        vector_ranked = self._normalize_scores(
            [(r.id, r.score) for r in raw_results],
        )
        # Use composite IDs for keyword results matching vector key space
        keyword_ranked = self._normalize_scores([
            (f"{_type_prefix.get(r.chunk_type, r.chunk_type)}:{r.file_path}:{r.name}", r.score)
            for r in keyword_results
        ])

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
            kw_id = f"{_type_prefix.get(r.chunk_type, r.chunk_type)}:{r.file_path}:{r.name}"
            if kw_id not in result_map:
                result_map[kw_id] = r

        # Optional cross-encoder reranking
        if rerank:
            rerank_k = min(len(fused), 3 * top_k)
            fused = self._rerank(query, fused[:rerank_k], result_map, top_k)

        # Return top-k by fused score
        merged: list[SemanticSearchResult] = []
        for item_id, fused_score in fused[:top_k]:
            result = result_map.get(item_id)
            if result:
                result.score = round(fused_score, 4)
                merged.append(result)

        return merged

    def _normalize_scores(
        self,
        ranked: list[tuple[str, float]],
        method: str = "min_max",
    ) -> list[tuple[str, float]]:
        """Normalize scores to [0, 1] range for fair fusion.

        Ensures that vector similarity scores and BM25 scores are on
        comparable scales before Reciprocal Rank Fusion.

        Args:
            ranked: List of (id, score) tuples.
            method: Normalization method (currently only "min_max").

        Returns:
            List of (id, normalized_score) tuples in the same order.
        """
        if not ranked or len(ranked) < 2:
            return ranked
        scores = [s for _, s in ranked]
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            return [(key, 1.0) for key, _ in ranked]
        return [(key, (s - min_s) / (max_s - min_s)) for key, s in ranked]

    def _rerank(
        self,
        query: str,
        fused: list[tuple[str, float]],
        result_map: dict[str, SemanticSearchResult],
        top_k: int,
    ) -> list[tuple[str, float]]:
        """Apply cross-encoder reranking to fused results.

        Args:
            query: The search query.
            fused: List of (id, fused_score) from RRF.
            result_map: Lookup from item ID to SemanticSearchResult.
            top_k: Number of final results desired.

        Returns:
            Reranked list of (id, score) tuples.
        """
        from attocode.integrations.context.reranker import get_reranker

        reranker = get_reranker()

        # Build candidates: (id, text, fused_score)
        candidates: list[tuple[str, str, float]] = []
        for item_id, score in fused:
            result = result_map.get(item_id)
            if result:
                candidates.append((item_id, result.text, score))

        if not candidates:
            return fused[:top_k]

        reranked = reranker.rerank(query, candidates, top_k=top_k)
        return [(cid, score) for cid, _text, score in reranked]

    def _keyword_search(
        self,
        query: str,
        top_k: int,
        file_filter: str,
    ) -> list[SemanticSearchResult]:
        """BM25 content-aware keyword search using AST-extracted data."""
        if not self._kw_index_built:
            self._build_keyword_index()

        if not self._kw_docs:
            return []

        import fnmatch

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        query_lower = query.lower()

        # BM25 parameters
        k1 = 1.5
        b = 0.75
        N = len(self._kw_docs)  # noqa: N806
        avg_dl = self._kw_avg_dl or 1.0

        scored: list[tuple[float, _KeywordDoc]] = []
        for doc in self._kw_docs:
            if file_filter and not fnmatch.fnmatch(doc.file_path, file_filter):
                continue

            # BM25 score
            score = 0.0
            for term in query_tokens:
                tf = doc.term_freqs.get(term, 0)
                if tf == 0:
                    continue
                df = self._kw_df.get(term, 0)
                if df == 0:
                    continue
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                dl = doc.doc_len or 1
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
                score += idf * tf_norm

            if score <= 0:
                continue

            # Post-hoc boosts
            _name_lower = doc.name.lower()
            name_tokens = _tokenize(doc.name)

            # Symbol name match boost
            for term in query_tokens:
                if term in name_tokens:
                    score *= 1.5
                    break

            # Config/doc file penalty
            if doc.is_config:
                score *= 0.15

            # Test file mild penalty
            if doc.is_test:
                score *= 0.7

            # Function/method chunk preference over file-level
            if doc.chunk_type in ("function", "method"):
                score *= 1.1

            # Exact phrase bonus: multi-word query substring match in text
            if len(query_tokens) > 1 and query_lower in doc.text.lower():
                score *= 1.2

            scored.append((score, doc))

        if not scored:
            return []

        scored.sort(key=lambda x: x[0], reverse=True)

        # Normalize to 0-1
        max_score = scored[0][0] if scored else 1.0
        if max_score <= 0:
            max_score = 1.0

        # Deduplicate: max 2 chunks per file
        file_counts: dict[str, int] = {}
        results: list[SemanticSearchResult] = []
        for raw_score, doc in scored:
            if file_counts.get(doc.file_path, 0) >= 2:
                continue
            file_counts[doc.file_path] = file_counts.get(doc.file_path, 0) + 1
            results.append(SemanticSearchResult(
                file_path=doc.file_path,
                chunk_type=doc.chunk_type,
                name=doc.name,
                text=doc.text,
                score=round(raw_score / max_score, 4),
            ))
            if len(results) >= top_k:
                break

        return results

    def _build_keyword_index(self) -> None:
        """Build BM25 inverted index from AST-extracted data."""
        from attocode.integrations.context.codebase_ast import parse_file
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        ctx = CodebaseContextManager(root_dir=self.root_dir)
        ctx._ensure_fresh()
        if not ctx._files:
            ctx.discover_files()

        _CONFIG_EXTS = frozenset({".toml", ".json", ".yaml", ".yml", ".cfg", ".ini", ".md", ".rst", ".txt"})  # noqa: N806
        _CONFIG_NAMES = frozenset({  # noqa: N806
            "pyproject.toml", "package.json", "tsconfig.json", "setup.cfg",
            "setup.py", "readme.md", "readme.rst", "changelog.md", "license",
        })

        docs: list[_KeywordDoc] = []
        df: dict[str, int] = {}

        for f in ctx._files:
            rel = f.relative_path
            basename = os.path.basename(rel).lower()
            ext = os.path.splitext(basename)[1]
            is_config = ext in _CONFIG_EXTS or basename in _CONFIG_NAMES
            is_test = f.is_test

            try:
                ast = parse_file(f.path)
            except Exception:
                continue

            # File-level doc: path components + import modules + symbol names
            file_text_parts = list(re.split(r"[/\\]", rel))
            file_text_parts.extend(imp.module for imp in ast.imports[:30])
            file_text_parts.extend(ast.get_symbols()[:30])
            file_text = " ".join(file_text_parts)
            file_tokens = _tokenize(file_text)

            file_tf: dict[str, int] = {}
            for t in file_tokens:
                file_tf[t] = file_tf.get(t, 0) + 1

            docs.append(_KeywordDoc(
                id=f"file:{rel}",
                file_path=rel,
                chunk_type="file",
                name=os.path.basename(rel),
                text=file_text[:200],
                is_config=is_config,
                is_test=is_test,
                term_freqs=file_tf,
                doc_len=len(file_tokens),
            ))

            # Function-level docs
            for func in ast.functions:
                parts: list[str] = []
                # Name with 3x weight
                parts.extend([func.name] * 3)
                if func.docstring:
                    parts.append(func.docstring[:300])
                parts.extend(p.name for p in func.parameters[:10])
                parts.extend(p.type_annotation for p in func.parameters[:10] if p.type_annotation)
                if func.return_type:
                    parts.append(func.return_type)
                parts.extend(func.decorators[:5])
                text = " ".join(parts)
                tokens = _tokenize(text)

                tf: dict[str, int] = {}
                for t in tokens:
                    tf[t] = tf.get(t, 0) + 1

                preview_parts = [f"function {func.name}"]
                if func.docstring:
                    preview_parts.append(func.docstring[:100])
                params_str = ", ".join(p.name for p in func.parameters[:6])
                if params_str:
                    preview_parts.append(f"({params_str})")

                docs.append(_KeywordDoc(
                    id=f"func:{rel}:{func.name}",
                    file_path=rel,
                    chunk_type="function",
                    name=func.name,
                    text=" | ".join(preview_parts),
                    is_config=False,
                    is_test=is_test,
                    term_freqs=tf,
                    doc_len=len(tokens),
                ))

            # Class + method-level docs
            for cls in ast.classes:
                cls_parts: list[str] = [cls.name] * 3
                if cls.bases:
                    cls_parts.extend(cls.bases)
                if cls.docstring:
                    cls_parts.append(cls.docstring[:300])
                cls_parts.extend(m.name for m in cls.methods[:15])
                cls_text = " ".join(cls_parts)
                cls_tokens = _tokenize(cls_text)

                cls_tf: dict[str, int] = {}
                for t in cls_tokens:
                    cls_tf[t] = cls_tf.get(t, 0) + 1

                cls_preview = f"class {cls.name}"
                if cls.bases:
                    cls_preview += f"({', '.join(cls.bases[:3])})"
                if cls.docstring:
                    cls_preview += f" | {cls.docstring[:100]}"

                docs.append(_KeywordDoc(
                    id=f"cls:{rel}:{cls.name}",
                    file_path=rel,
                    chunk_type="class",
                    name=cls.name,
                    text=cls_preview,
                    is_config=False,
                    is_test=is_test,
                    term_freqs=cls_tf,
                    doc_len=len(cls_tokens),
                ))

                for method in cls.methods:
                    m_parts: list[str] = [method.name] * 3
                    m_parts.append(cls.name)
                    if method.docstring:
                        m_parts.append(method.docstring[:300])
                    m_parts.extend(p.name for p in method.parameters[:10])
                    m_parts.extend(p.type_annotation for p in method.parameters[:10] if p.type_annotation)
                    if method.return_type:
                        m_parts.append(method.return_type)
                    m_text = " ".join(m_parts)
                    m_tokens = _tokenize(m_text)

                    m_tf: dict[str, int] = {}
                    for t in m_tokens:
                        m_tf[t] = m_tf.get(t, 0) + 1

                    m_preview = f"method {cls.name}.{method.name}"
                    if method.docstring:
                        m_preview += f" | {method.docstring[:100]}"

                    docs.append(_KeywordDoc(
                        id=f"method:{rel}:{cls.name}.{method.name}",
                        file_path=rel,
                        chunk_type="method",
                        name=f"{cls.name}.{method.name}",
                        text=m_preview,
                        is_config=False,
                        is_test=is_test,
                        term_freqs=m_tf,
                        doc_len=len(m_tokens),
                    ))

        # Build document frequencies
        for doc in docs:
            for term in doc.term_freqs:
                df[term] = df.get(term, 0) + 1

        # Average document length
        total_len = sum(doc.doc_len for doc in docs)
        avg_dl = total_len / len(docs) if docs else 1.0

        self._kw_docs = docs
        self._kw_df = df
        self._kw_avg_dl = avg_dl
        self._kw_index_built = True
        logger.debug("BM25 keyword index built: %d docs, %d terms", len(docs), len(df))

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
        imports = [imp.module for imp in ast.imports[:20]]
        symbols = ast.get_symbols()[:20]
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

    def _get_embedding_texts(
        self, chunks: list[tuple[str, str, str, str]], language: str = "python",
    ) -> list[str]:
        """Return texts to feed to the embedding model.

        When ``nl_mode`` is ``"heuristic"``, each chunk's text is transformed
        into a natural language summary via :class:`CodeSummarizer` before
        embedding.  The original chunk text (index 3) is still stored in
        ``VectorEntry.text`` for display.

        Args:
            chunks: List of ``(id, file_path, chunk_type, text)`` tuples as
                returned by :meth:`_chunk_single_file`.
            language: Programming language hint for the summarizer.

        Returns:
            A list of strings, one per chunk, suitable for embedding.
        """
        if self._summarizer is None:
            # No NL mode — embed the raw chunk text directly
            return [c[3] for c in chunks]

        result: list[str] = []
        for cid, _fpath, ctype, text in chunks:
            # Derive the symbol name from the chunk ID
            name = cid.split(":")[-1] if ":" in cid else _fpath
            summary = self._summarizer.summarize(text, ctype, name, language)
            result.append(summary)
        return result

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
        texts = self._get_embedding_texts(chunks)
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
        for (cid, fpath, ctype, text), vec in zip(chunks, vectors, strict=False):
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
        self._kw_index_built = False  # Force rebuild on next keyword search
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

    # ------------------------------------------------------------------
    # Background indexing (P3)
    # ------------------------------------------------------------------

    def is_index_ready(self) -> bool:
        """Check if the vector index has sufficient coverage (>=80%)."""
        if self._keyword_fallback or not self._store:
            return False
        progress = self.get_index_progress()
        return progress.coverage >= 0.8

    def get_index_progress(self) -> IndexProgress:
        """Get current indexing progress (thread-safe snapshot)."""
        with self._reindex_lock:
            if self._bg_indexer is not None:
                # Return a snapshot to avoid races
                p = self._index_progress
                return IndexProgress(
                    total_files=p.total_files,
                    indexed_files=p.indexed_files,
                    failed_files=p.failed_files,
                    status=p.status,
                    coverage=p.coverage,
                    started_at=p.started_at,
                    elapsed_seconds=p.elapsed_seconds,
                )
        # If no background indexer, check store directly
        if self._store:
            # Use cached total if available to avoid expensive filesystem scan
            cached_total = self._index_progress.total_files
            if cached_total > 0:
                total = cached_total
            else:
                from attocode.integrations.context.codebase_context import CodebaseContextManager
                ctx = CodebaseContextManager(root_dir=self.root_dir)
                ctx._ensure_fresh()
                if not ctx._files:
                    ctx.discover_files()
                total = len([f for f in ctx._files if f.language in ("python", "javascript", "typescript")])
                self._index_progress.total_files = total
            indexed = len(self._store.get_all_indexed_files()) if total > 0 else 0
            coverage = indexed / total if total > 0 else 0.0
            return IndexProgress(
                total_files=total,
                indexed_files=indexed,
                coverage=round(coverage, 3),
                status="completed" if coverage >= 0.99 else "idle",
            )
        return self._index_progress

    def start_background_indexing(self) -> IndexProgress:
        """Start background progressive embedding indexing."""
        import time

        if self._keyword_fallback or not self._store:
            self._index_progress.status = "error"
            return self._index_progress

        with self._reindex_lock:
            if self._bg_indexer is not None:
                return self._index_progress

            self._index_progress = IndexProgress(status="running", started_at=time.time())
            stop_event = threading.Event()

            def _worker() -> None:
                try:
                    self._run_background_indexing(stop_event)
                except Exception:
                    logger.error("Background indexer crashed", exc_info=True)
                    with self._reindex_lock:
                        self._index_progress.status = "error"
                finally:
                    with self._reindex_lock:
                        self._bg_indexer = None
                        self._bg_thread = None

            worker = threading.Thread(target=_worker, daemon=True, name="bg-embedding-indexer")
            self._bg_indexer = stop_event
            self._bg_thread = worker
            worker.start()
        return self._index_progress

    def stop_background_indexing(self) -> None:
        """Stop background indexing gracefully."""
        if self._bg_indexer is not None:
            self._bg_indexer.set()

    def _run_background_indexing(self, stop_event: threading.Event) -> None:
        """Background indexer loop: process files in batches."""
        import time

        from attocode.integrations.context.codebase_context import CodebaseContextManager
        from attocode.integrations.context.vector_store import VectorEntry

        ctx = CodebaseContextManager(root_dir=self.root_dir)
        ctx._ensure_fresh()
        if not ctx._files:
            ctx.discover_files()

        _ts_langs: set[str] = set()
        try:
            from attocode.integrations.context.ts_parser import supported_languages
            _ts_langs = set(supported_languages())
        except ImportError:
            pass
        _supported = {"python", "javascript", "typescript"} | _ts_langs

        indexable = [f for f in ctx._files if f.language in _supported]
        self._index_progress.total_files = len(indexable)

        # Determine which files need indexing
        file_mtimes: dict[str, float] = {}
        for f in indexable:
            try:
                file_mtimes[f.relative_path] = os.path.getmtime(f.path)
            except OSError:
                pass

        stale = set(self._store.get_stale_files(file_mtimes))
        # Also include files not yet indexed at all
        all_indexed = set(self._store.get_all_indexed_files())
        to_index = [f for f in indexable if f.relative_path in stale or f.relative_path not in all_indexed]

        self._index_progress.indexed_files = len(indexable) - len(to_index)
        batch_size = 50

        for i in range(0, len(to_index), batch_size):
            if stop_event.is_set():
                self._index_progress.status = "paused"
                return

            batch = to_index[i:i + batch_size]
            for f in batch:
                if stop_event.is_set():
                    self._index_progress.status = "paused"
                    return
                try:
                    chunks = self._chunk_single_file(f.relative_path, f.path)
                    if not chunks:
                        self._index_progress.failed_files += 1
                        continue

                    texts = self._get_embedding_texts(chunks)
                    vectors = self._provider.embed(texts)
                    entries = []
                    for (cid, fpath, ctype, text), vec in zip(chunks, vectors, strict=False):
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
                        self._store.delete_by_file(f.relative_path)
                        self._store.upsert_batch(entries)
                        try:
                            mtime = os.path.getmtime(f.path)
                        except OSError:
                            mtime = 0.0
                        self._store.set_file_metadata(f.relative_path, mtime, len(entries))
                        with self._reindex_lock:
                            self._index_progress.indexed_files += 1
                    else:
                        with self._reindex_lock:
                            self._index_progress.failed_files += 1
                except Exception:
                    logger.debug("bg_index_failed: %s", f.relative_path, exc_info=True)
                    with self._reindex_lock:
                        self._index_progress.failed_files += 1

            # Update coverage
            with self._reindex_lock:
                total = self._index_progress.total_files or 1
                self._index_progress.coverage = round(self._index_progress.indexed_files / total, 3)
                self._index_progress.elapsed_seconds = round(time.time() - self._index_progress.started_at, 1)

            # Yield CPU between batches
            time.sleep(0.1)

        with self._reindex_lock:
            self._index_progress.status = "completed"
            total = self._index_progress.total_files or 1
            self._index_progress.coverage = round(self._index_progress.indexed_files / total, 3)
            self._index_progress.elapsed_seconds = round(time.time() - self._index_progress.started_at, 1)
        self._indexed = True
        logger.info(
            "Background indexing complete: %d/%d files (%.0f%% coverage)",
            self._index_progress.indexed_files,
            self._index_progress.total_files,
            self._index_progress.coverage * 100,
        )

    def close(self) -> None:
        """Close the vector store and stop background indexer."""
        self.stop_background_indexing()
        thread = self._bg_thread
        if thread is not None:
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("Background indexer thread did not stop within 5s")
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
