"""Semantic search manager.

Indexes codebase content into embeddings and provides natural language
search over code. Gracefully degrades to BM25 keyword matching when no
embedding provider is available.
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import re
import sqlite3
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

# Mapping from common query terms to code construct types for query expansion
_CONSTRUCT_HINTS: dict[str, list[str]] = {
    "function": ["def", "func", "fn"],
    "class": ["class", "struct", "type"],
    "method": ["def", "func", "method"],
    "import": ["import", "require", "from", "use"],
    "test": ["test", "spec", "assert", "expect"],
    "error": ["error", "exception", "raise", "throw", "catch"],
    "config": ["config", "settings", "env", "option"],
    "api": ["route", "endpoint", "handler", "controller"],
    "auth": ["auth", "login", "password", "token", "session"],
    "database": ["query", "model", "schema", "migration", "table"],
}


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


def _expand_query(query: str, language: str = "") -> str:
    """Expand a search query with language and construct hints.

    Prepends language context and adds related terms for known constructs,
    improving recall for code-specific embedding models.

    Examples:
        "auth middleware" + "python" -> "python auth middleware login token session"
        "parse config" -> "parse config settings env option"
    """
    query_lower = query.lower()
    tokens = _tokenize(query)
    expansions: list[str] = []

    # Add language hint if known
    if language:
        expansions.append(language)

    # Add construct-related terms for each matching concept
    for concept, hints in _CONSTRUCT_HINTS.items():
        if concept in query_lower or any(t == concept for t in tokens):
            for hint in hints:
                if hint not in query_lower and hint not in expansions:
                    expansions.append(hint)

    if not expansions:
        return query

    return f"{query} {' '.join(expansions)}"


def _summarize_code_to_nl(name: str, chunk_type: str, text: str) -> str:
    """Generate a heuristic NL summary from code structure.

    Converts code identifiers into natural language fragments to improve
    BM25 matching between NL queries and code symbols.

    Examples:
        "parseConfigFile" -> "parse config file"
        "UserAuthMiddleware" -> "user auth middleware"
    """
    # Tokenize the name into natural language words
    name_words = _CAMEL_RE.sub(" ", name).replace("_", " ").lower().strip()

    if chunk_type == "function":
        return f"function {name_words} {text[:200]}"
    elif chunk_type == "class":
        return f"class {name_words} {text[:200]}"
    elif chunk_type == "method":
        return f"method {name_words} {text[:200]}"
    else:
        return f"{name_words} {text[:200]}"


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
    last_error: str = ""
    degraded_reason: str = ""


@dataclass(slots=True)
class SearchScoringConfig:
    """Tunable scoring parameters for BM25 keyword search and two-stage retrieval.

    Default values match the original hardcoded constants. Adjusting these
    allows the meta-harness optimization loop to explore better configurations.
    """

    # BM25 base parameters
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

    # Graduated symbol name match boosts
    name_exact_boost: float = 3.0
    name_substring_boost: float = 2.0
    name_token_boost: float = 1.5

    # Definition-type boosts
    class_boost: float = 1.3
    function_boost: float = 1.15
    method_boost: float = 1.1

    # Path relevance: source directory boost
    src_dir_boost: float = 1.2

    # Multi-term coverage bonuses
    multi_term_high_bonus: float = 1.4   # >= 80% coverage
    multi_term_med_bonus: float = 1.15   # >= 50% coverage
    multi_term_high_threshold: float = 0.8
    multi_term_med_threshold: float = 0.5

    # File type penalties
    non_code_penalty: float = 0.3
    config_penalty: float = 0.15
    test_penalty: float = 0.7

    # Exact phrase bonus
    exact_phrase_bonus: float = 1.2

    # Deduplication: max chunks per file in results
    max_chunks_per_file: int = 2

    # Two-stage retrieval parameters
    wide_k_multiplier: int = 5
    wide_k_min: int = 50
    rrf_k: int = 60


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
    scoring_config: SearchScoringConfig = field(default_factory=SearchScoringConfig)
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
    _kw_cache_db_path: str = field(default="", repr=False)
    _kw_cache_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _trigram_index: Any = field(default=None, repr=False)
    _bg_indexer: Any = field(default=None, repr=False)
    _bg_thread: Any = field(default=None, repr=False)
    _index_progress: IndexProgress = field(default_factory=IndexProgress, repr=False)
    _summarizer: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Defer provider creation to first use (_ensure_provider) to avoid
        # 5-15s model-load latency on construction.
        self._provider = None
        self._keyword_fallback = True  # assume keyword-only until provider loads
        self._kw_cache_db_path = os.path.join(
            self.root_dir, ".attocode", "index", "kw_index.db",
        )
        if not self.nl_mode:
            self.nl_mode = os.environ.get("ATTOCODE_NL_EMBEDDING_MODE", "none")

    def _ensure_provider(self) -> None:
        """Initialize embedding provider on first use."""
        if self._provider is not None:
            return
        from attocode.integrations.context.embeddings import (
            NullEmbeddingProvider,
            create_embedding_provider,
        )
        self._provider = create_embedding_provider()
        self._keyword_fallback = isinstance(self._provider, NullEmbeddingProvider)
        if self._keyword_fallback:
            self._index_progress.degraded_reason = "embedding_provider_unavailable"
            if not self._index_progress.last_error:
                self._index_progress.last_error = (
                    "Embedding provider unavailable; semantic search is running in keyword-only mode."
                )

        if not self._keyword_fallback:
            from attocode.integrations.context.vector_store import (
                VectorStore,
                VectorStoreDimensionMismatchError,
            )
            db_dir = os.path.join(self.root_dir, ".attocode", "vectors")
            os.makedirs(db_dir, exist_ok=True)
            # strict_dimension=False: catch the mismatch as degraded mode
            # instead of crashing the whole MCP server. The provider + store
            # both stay available for diagnostic tools
            # (`embeddings_status`, etc.) but writes refuse to land until
            # the user resolves the mismatch.
            provider_name = getattr(self._provider, "name", lambda: "unknown")
            provider_name_str = provider_name() if callable(provider_name) else str(provider_name)
            provider_version = getattr(self._provider, "version", lambda: "")
            provider_version_str = (
                provider_version() if callable(provider_version) else str(provider_version)
            )
            try:
                self._store = VectorStore(
                    db_path=os.path.join(db_dir, "embeddings.db"),
                    dimension=self._provider.dimension(),
                    model_name=provider_name_str,
                    model_version=provider_version_str,
                    strict_dimension=False,
                )
            except VectorStoreDimensionMismatchError as exc:
                logger.warning(
                    "semantic_search: vector store unusable (%s); "
                    "falling back to keyword-only mode",
                    exc,
                )
                self._store = None
                self._keyword_fallback = True
                self._index_progress.degraded_reason = "dimension_mismatch"
                self._index_progress.last_error = str(exc)
            else:
                if self._store.degraded:
                    self._index_progress.degraded_reason = self._store.degraded_reason
                    self._index_progress.last_error = (
                        f"Vector store at {self._store.db_path} is in degraded mode: "
                        f"{self._store.degraded_reason}. Existing vectors preserved; "
                        f"writes disabled until resolved."
                    )

        if not self.nl_mode:
            self.nl_mode = os.environ.get("ATTOCODE_NL_EMBEDDING_MODE", "none")
        if self.nl_mode == "heuristic" and self._summarizer is None:
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
        self._ensure_provider()
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
        self._ensure_provider()
        return not self._keyword_fallback

    @property
    def provider_name(self) -> str:
        self._ensure_provider()
        return self._provider.name if self._provider else "none"

    def index(self, context_manager: Any = None) -> int:
        """Build or update the vector index.

        Args:
            context_manager: Optional CodebaseContextManager for file discovery.

        Returns:
            Number of chunks indexed.
        """
        self._ensure_provider()
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
        expand_query: bool = True,
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
            expand_query: Whether to expand query with code construct hints.

        Returns:
            List of search results sorted by relevance.
        """
        # Detect language from file_filter for query expansion
        _lang = ""
        if file_filter:
            _ext_map = {".py": "python", ".js": "javascript", ".ts": "typescript",
                        ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby"}
            for ext, lang in _ext_map.items():
                if file_filter.endswith(ext):
                    _lang = lang
                    break

        # Apply query expansion for better recall
        expanded_query = _expand_query(query, _lang) if expand_query else query

        self._ensure_provider()
        if self._keyword_fallback:
            return self._keyword_search(expanded_query, top_k, file_filter)

        # Coverage-based switchover: use keyword fallback while indexing
        if not self._indexed and self._store:
            count = self._store.count()
            if count == 0 and self._bg_indexer is None:
                # No embeddings and no background indexer — use keyword fallback
                return self._keyword_search(expanded_query, top_k, file_filter)
            elif not self.is_index_ready() and self._bg_indexer is not None:
                # Indexer running but coverage < 80% — use keyword fallback
                return self._keyword_search(expanded_query, top_k, file_filter)

        # Embed query — use expanded query for better recall
        try:
            query_vectors = self._provider.embed([expanded_query])
            if not query_vectors or not query_vectors[0]:
                self._index_progress.degraded_reason = "query_embedding_failed"
                self._index_progress.last_error = "Query embedding returned no vector."
                return self._keyword_search(expanded_query, top_k, file_filter)
            query_vec = query_vectors[0]
        except Exception as exc:
            logger.warning("Query embedding failed, falling back to keyword", exc_info=True)
            self._index_progress.degraded_reason = "query_embedding_failed"
            self._index_progress.last_error = f"Query embedding failed: {type(exc).__name__}: {exc}"
            return self._keyword_search(expanded_query, top_k, file_filter)

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
        cfg = self.scoring_config
        wide_k = max(top_k * cfg.wide_k_multiplier, cfg.wide_k_min) if two_stage else top_k
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
        keyword_results = self._keyword_search(expanded_query, top_k=wide_k, file_filter=file_filter)

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

        fused = reciprocal_rank_fusion(vector_ranked, keyword_ranked, k=cfg.rrf_k)

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

    # ------------------------------------------------------------------
    # Trigram pre-filtering for keyword search
    # ------------------------------------------------------------------

    def _get_trigram_index(self) -> Any | None:
        """Get a loaded TrigramIndex instance, or None if unavailable."""
        if self._trigram_index is not None:
            return self._trigram_index
        try:
            from attocode.integrations.context.trigram_index import TrigramIndex

            index_dir = os.path.join(self.root_dir, ".attocode", "index")
            if not os.path.isdir(index_dir):
                return None
            idx = TrigramIndex(index_dir=index_dir)
            if idx.load():
                self._trigram_index = idx
                return idx
        except Exception:
            logger.debug("Failed to load trigram index for kw pre-filter", exc_info=True)
        return None

    def _trigram_prefilter(self, query_tokens: list[str]) -> set[str] | None:
        """Use trigram index to find candidate files containing query terms.

        Returns set of candidate file paths, or None to fall back to full scan.
        Uses UNION semantics: a file matching ANY query term is included.
        """
        idx = self._get_trigram_index()
        if idx is None or not idx.is_ready():
            return None

        filterable = [t for t in query_tokens if len(t) >= 3]
        if not filterable:
            return None

        candidates: set[str] = set()
        any_definitive = False

        for token in filterable:
            escaped = re.escape(token)
            try:
                result = idx.query(escaped, selectivity_threshold=0.5)
            except Exception:
                logger.debug("Trigram query failed for '%s'", token, exc_info=True)
                return None

            if result is None:
                continue  # too common or no trigrams — skip this token
            any_definitive = True
            candidates.update(result)

        if not any_definitive:
            return None  # no token could be filtered, full scan needed

        return candidates

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

        # Trigram pre-filter: narrow to files containing query terms
        candidate_files = self._trigram_prefilter(query_tokens)
        if candidate_files is not None:
            docs_to_score = [
                d for d in self._kw_docs if d.file_path in candidate_files
            ]
            logger.debug(
                "Trigram pre-filter: %d/%d docs from %d candidate files",
                len(docs_to_score), len(self._kw_docs), len(candidate_files),
            )
        else:
            docs_to_score = self._kw_docs

        query_lower = query.lower()
        cfg = self.scoring_config

        # BM25 parameters — N and avg_dl use FULL corpus for correct IDF
        k1 = cfg.bm25_k1
        b = cfg.bm25_b
        N = len(self._kw_docs)  # noqa: N806
        avg_dl = self._kw_avg_dl or 1.0

        scored: list[tuple[float, _KeywordDoc]] = []
        for doc in docs_to_score:
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

            # Graduated symbol name match boost
            _name_boost_applied = False
            for term in query_tokens:
                if term == _name_lower:
                    score *= cfg.name_exact_boost
                    _name_boost_applied = True
                    break
                if term in _name_lower:
                    score *= cfg.name_substring_boost
                    _name_boost_applied = True
                    break
            if not _name_boost_applied:
                for term in query_tokens:
                    if term in name_tokens:
                        score *= cfg.name_token_boost
                        break

            # Definition-type boost: classes and functions rank above file-level
            if doc.chunk_type == "class":
                score *= cfg.class_boost
            elif doc.chunk_type == "function":
                score *= cfg.function_boost
            elif doc.chunk_type == "method":
                score *= cfg.method_boost

            # Path relevance boost: source directories rank higher
            _SRC_DIRS = {"src", "lib", "pkg", "core", "internal", "app", "main"}  # noqa: N806
            _first_dir = doc.file_path.split("/")[0] if "/" in doc.file_path else ""
            if _first_dir.lower() in _SRC_DIRS:
                score *= cfg.src_dir_boost

            # Multi-term coverage bonus
            if len(query_tokens) > 1:
                _matched_terms = sum(1 for t in query_tokens if doc.term_freqs.get(t, 0) > 0)
                _coverage = _matched_terms / len(query_tokens)
                if _coverage >= cfg.multi_term_high_threshold:
                    score *= cfg.multi_term_high_bonus
                elif _coverage >= cfg.multi_term_med_threshold:
                    score *= cfg.multi_term_med_bonus

            # Non-code file penalty (markdown, text, config formats)
            _NON_CODE_EXTS = {".md", ".txt", ".rst", ".cfg", ".ini", ".yml", ".yaml", ".json", ".toml", ".xml", ".csv"}  # noqa: N806
            _ext = os.path.splitext(doc.file_path)[1].lower()
            if _ext in _NON_CODE_EXTS:
                score *= cfg.non_code_penalty

            # Config/doc file penalty (stacks with non-code ext penalty)
            if doc.is_config:
                score *= cfg.config_penalty

            # Test file mild penalty
            if doc.is_test:
                score *= cfg.test_penalty

            # Exact phrase bonus: multi-word query substring match in text
            if len(query_tokens) > 1 and query_lower in doc.text.lower():
                score *= cfg.exact_phrase_bonus

            scored.append((score, doc))

        if not scored:
            return []

        scored.sort(key=lambda x: x[0], reverse=True)

        # Normalize to 0-1
        max_score = scored[0][0] if scored else 1.0
        if max_score <= 0:
            max_score = 1.0

        # Deduplicate: max N chunks per file
        file_counts: dict[str, int] = {}
        results: list[SemanticSearchResult] = []
        for raw_score, doc in scored:
            if file_counts.get(doc.file_path, 0) >= cfg.max_chunks_per_file:
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

    # ------------------------------------------------------------------
    # BM25 keyword index disk cache
    # ------------------------------------------------------------------

    def _open_kw_cache_db(self) -> sqlite3.Connection | None:
        """Open the keyword index cache database. Returns None on failure."""
        try:
            os.makedirs(os.path.dirname(self._kw_cache_db_path), exist_ok=True)
            conn = sqlite3.connect(self._kw_cache_db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kw_files (
                    file_path TEXT PRIMARY KEY, mtime REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kw_docs (
                    id TEXT PRIMARY KEY, file_path TEXT NOT NULL,
                    chunk_type TEXT NOT NULL, name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    is_config INTEGER NOT NULL DEFAULT 0,
                    is_test INTEGER NOT NULL DEFAULT 0,
                    term_freqs TEXT NOT NULL, doc_len INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS ix_kw_docs_file ON kw_docs(file_path);
            """)
            row = conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'",
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO metadata (key, value) VALUES ('schema_version', '1')",
                )
                conn.commit()
            elif row[0] != "1":
                conn.executescript(
                    "DROP TABLE IF EXISTS kw_files; DROP TABLE IF EXISTS kw_docs;"
                )
                conn.executescript("""
                    CREATE TABLE kw_files (
                        file_path TEXT PRIMARY KEY, mtime REAL NOT NULL
                    );
                    CREATE TABLE kw_docs (
                        id TEXT PRIMARY KEY, file_path TEXT NOT NULL,
                        chunk_type TEXT NOT NULL, name TEXT NOT NULL,
                        text TEXT NOT NULL,
                        is_config INTEGER NOT NULL DEFAULT 0,
                        is_test INTEGER NOT NULL DEFAULT 0,
                        term_freqs TEXT NOT NULL, doc_len INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS ix_kw_docs_file ON kw_docs(file_path);
                """)
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) "
                    "VALUES ('schema_version', '1')",
                )
                conn.commit()
            return conn
        except Exception:
            logger.debug("Failed to open kw cache db", exc_info=True)
            return None

    def _save_kw_cache(
        self,
        docs: list[_KeywordDoc],
        file_mtimes: dict[str, float],
    ) -> None:
        """Persist keyword index docs to disk cache."""
        conn = self._open_kw_cache_db()
        if conn is None:
            return
        try:
            with self._kw_cache_lock:
                conn.execute("DELETE FROM kw_files")
                conn.execute("DELETE FROM kw_docs")
                for fpath, mtime in file_mtimes.items():
                    conn.execute(
                        "INSERT INTO kw_files (file_path, mtime) VALUES (?, ?)",
                        (fpath, mtime),
                    )
                for doc in docs:
                    conn.execute(
                        "INSERT OR REPLACE INTO kw_docs "
                        "(id, file_path, chunk_type, name, text, is_config, "
                        "is_test, term_freqs, doc_len) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            doc.id, doc.file_path, doc.chunk_type, doc.name,
                            doc.text, int(doc.is_config), int(doc.is_test),
                            json.dumps(doc.term_freqs), doc.doc_len,
                        ),
                    )
                conn.commit()
        except Exception:
            logger.debug("Failed to save kw cache", exc_info=True)
        finally:
            conn.close()

    def _load_kw_cache(
        self,
        current_files: dict[str, tuple[str, float]],
    ) -> tuple[list[_KeywordDoc], set[str]] | None:
        """Load cached keyword docs, identify files that need re-parsing.

        Args:
            current_files: dict of rel_path -> (abs_path, mtime)

        Returns:
            (cached_docs, files_to_parse) or None if cache unavailable.
        """
        conn = self._open_kw_cache_db()
        if conn is None:
            return None
        try:
            with self._kw_cache_lock:
                rows = conn.execute(
                    "SELECT file_path, mtime FROM kw_files",
                ).fetchall()
                if not rows:
                    conn.close()
                    return None

                cached_mtimes = {r[0]: r[1] for r in rows}

                # Identify stale (modified/new) and deleted files
                stale: set[str] = set()
                for fpath, (_, current_mtime) in current_files.items():
                    cached_mtime = cached_mtimes.get(fpath)
                    if cached_mtime is None or current_mtime > cached_mtime:
                        stale.add(fpath)
                deleted = set(cached_mtimes.keys()) - set(current_files.keys())
                exclude = stale | deleted

                # Load docs for unchanged files
                doc_rows = conn.execute(
                    "SELECT id, file_path, chunk_type, name, text, "
                    "is_config, is_test, term_freqs, doc_len FROM kw_docs",
                ).fetchall()

                docs: list[_KeywordDoc] = []
                for row in doc_rows:
                    if row[1] in exclude:
                        continue
                    docs.append(_KeywordDoc(
                        id=row[0], file_path=row[1], chunk_type=row[2],
                        name=row[3], text=row[4], is_config=bool(row[5]),
                        is_test=bool(row[6]),
                        term_freqs=json.loads(row[7]), doc_len=row[8],
                    ))

            conn.close()
            return (docs, stale)
        except Exception:
            logger.debug("Failed to load kw cache", exc_info=True)
            try:
                conn.close()
            except Exception:
                pass
            return None

    # ------------------------------------------------------------------
    # BM25 keyword index builder (incremental with cache)
    # ------------------------------------------------------------------

    def _build_keyword_index(self) -> None:
        """Build BM25 inverted index from AST-extracted data.

        Uses disk cache to avoid re-parsing unchanged files.
        """
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

        # Discover current files with mtimes
        current_files: dict[str, tuple[str, float]] = {}
        file_meta: dict[str, tuple[bool, bool]] = {}  # rel -> (is_config, is_test)
        for f in ctx._files:
            try:
                mtime = os.path.getmtime(f.path)
            except OSError:
                continue
            current_files[f.relative_path] = (f.path, mtime)
            basename = os.path.basename(f.relative_path).lower()
            ext = os.path.splitext(basename)[1]
            is_config = ext in _CONFIG_EXTS or basename in _CONFIG_NAMES
            file_meta[f.relative_path] = (is_config, f.is_test)

        # Try incremental update from cache
        cache_result = self._load_kw_cache(current_files)

        if cache_result is not None:
            docs, files_to_parse = cache_result
            logger.debug(
                "kw_index incremental: %d cached docs, %d files to parse",
                len(docs), len(files_to_parse),
            )
        else:
            docs = []
            files_to_parse = set(current_files.keys())
            logger.debug("kw_index full rebuild: %d files", len(files_to_parse))

        # Parse only files that need updating
        for rel in files_to_parse:
            entry = current_files.get(rel)
            if entry is None:
                continue
            abs_path, _ = entry
            is_config, is_test = file_meta.get(rel, (False, False))

            try:
                ast = parse_file(abs_path)
            except Exception:
                continue

            # File-level doc
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
                parts.extend([func.name] * 3)
                # Add NL summary of the function name for better query matching
                nl_summary = _summarize_code_to_nl(func.name, "function", "")
                parts.append(nl_summary)
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
                # Add NL summary of the class name
                cls_nl = _summarize_code_to_nl(cls.name, "class", "")
                cls_parts.append(cls_nl)
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

        # Build document frequencies (always recomputed from full doc list)
        df: dict[str, int] = {}
        for doc in docs:
            for term in doc.term_freqs:
                df[term] = df.get(term, 0) + 1

        total_len = sum(doc.doc_len for doc in docs)
        avg_dl = total_len / len(docs) if docs else 1.0

        self._kw_docs = docs
        self._kw_df = df
        self._kw_avg_dl = avg_dl
        self._kw_index_built = True

        # Persist to cache
        file_mtimes = {rel: mt for rel, (_, mt) in current_files.items()}
        self._save_kw_cache(docs, file_mtimes)

        logger.debug(
            "BM25 keyword index built: %d docs, %d terms (%d files parsed)",
            len(docs), len(df), len(files_to_parse),
        )

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
        self._ensure_provider()
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
        self._trigram_index = None  # Reload on next use
        try:
            rel = os.path.relpath(file_path, self.root_dir)
        except ValueError:
            rel = file_path
        # Mark stale in keyword cache
        try:
            conn = self._open_kw_cache_db()
            if conn:
                with self._kw_cache_lock:
                    conn.execute(
                        "UPDATE kw_files SET mtime = 0 WHERE file_path = ?",
                        (rel,),
                    )
                    conn.commit()
                conn.close()
        except Exception:
            pass
        if self._store:
            self._store.delete_by_file(rel)

    def reindex_stale_files(self, context_manager: Any = None) -> int:
        """Re-index only files whose mtime has changed since last indexing.

        Designed to be called on agent startup for incremental freshness.

        Returns:
            Number of chunks re-indexed.
        """
        self._ensure_provider()
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
        self._ensure_provider()
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

        self._ensure_provider()
        if self._keyword_fallback or not self._store:
            self._index_progress.status = "error"
            self._index_progress.degraded_reason = "embedding_provider_unavailable"
            self._index_progress.last_error = (
                "Background indexing unavailable because no embedding provider is configured."
            )
            return self._index_progress

        with self._reindex_lock:
            if self._bg_indexer is not None:
                return self._index_progress

            self._index_progress = IndexProgress(status="running", started_at=time.time())
            stop_event = threading.Event()

            def _worker() -> None:
                try:
                    self._run_background_indexing(stop_event)
                except Exception as exc:
                    logger.error("Background indexer crashed", exc_info=True)
                    with self._reindex_lock:
                        self._index_progress.status = "error"
                        self._index_progress.degraded_reason = "background_indexer_crashed"
                        self._index_progress.last_error = (
                            f"Background indexer crashed: {type(exc).__name__}: {exc}"
                        )
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
            self._index_progress.degraded_reason = "tree_sitter_languages_unavailable"
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
                        self._index_progress.last_error = (
                            f"No indexable chunks generated for {f.relative_path}"
                        )
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
                            self._index_progress.last_error = (
                                f"No vectors generated for {f.relative_path}"
                            )
                            self._index_progress.degraded_reason = "partial_index_failure"
                except Exception as exc:
                    logger.debug("bg_index_failed: %s", f.relative_path, exc_info=True)
                    with self._reindex_lock:
                        self._index_progress.failed_files += 1
                        self._index_progress.last_error = (
                            f"Failed to index {f.relative_path}: {type(exc).__name__}: {exc}"
                        )
                        self._index_progress.degraded_reason = "partial_index_failure"

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
            if self._index_progress.failed_files > 0 and not self._index_progress.degraded_reason:
                self._index_progress.degraded_reason = "partial_index_failure"
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
