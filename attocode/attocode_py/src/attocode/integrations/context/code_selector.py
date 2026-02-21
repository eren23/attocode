"""Code selection strategies for codebase context.

Selects relevant code chunks from analyzed files to include
in the LLM context, using configurable strategies:
importance, relevance, breadth, depth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from attocode.integrations.context.code_analyzer import CodeChunk, FileAnalysis
from attocode.integrations.context.codebase_context import FileInfo
from attocode.integrations.utilities.token_estimate import estimate_tokens


class SelectionStrategy(StrEnum):
    """Strategy for selecting code chunks."""

    IMPORTANCE = "importance"  # Highest importance score first
    RELEVANCE = "relevance"  # Most relevant to query
    BREADTH = "breadth"  # Wide coverage across files
    DEPTH = "depth"  # Deep coverage of key files


@dataclass(slots=True)
class SelectionResult:
    """Result of code selection."""

    chunks: list[CodeChunk]
    total_tokens: int
    files_represented: int
    strategy_used: SelectionStrategy
    budget_used: float  # 0.0-1.0


@dataclass(slots=True)
class SelectionConfig:
    """Configuration for code selection."""

    max_tokens: int = 4000
    strategy: SelectionStrategy = SelectionStrategy.IMPORTANCE
    min_importance: float = 0.0
    max_chunks_per_file: int = 10
    prefer_signatures: bool = True
    include_imports: bool = True
    query: str = ""  # For relevance strategy


@dataclass(slots=True)
class RankedSearchResult:
    """Result of a multi-factor ranked search."""

    chunk: CodeChunk
    total_score: float
    factors: dict[str, float]  # name -> contribution

    @property
    def top_factor(self) -> str:
        """The dominant scoring factor."""
        if not self.factors:
            return "none"
        return max(self.factors, key=self.factors.get)  # type: ignore[arg-type]


@dataclass(slots=True)
class ExpansionStep:
    """One step in incremental context expansion."""

    chunks_added: int
    tokens_added: int
    total_tokens: int
    strategy: str
    budget_remaining: int


class CodeSelector:
    """Selects code chunks for LLM context inclusion.

    Given analyzed files and a token budget, selects the most
    relevant/important chunks using configurable strategies.
    """

    def __init__(self, config: SelectionConfig | None = None) -> None:
        self._config = config or SelectionConfig()

    def select(
        self,
        analyses: list[FileAnalysis],
        file_infos: list[FileInfo] | None = None,
        *,
        config: SelectionConfig | None = None,
    ) -> SelectionResult:
        """Select code chunks from analyses.

        Args:
            analyses: Analyzed files with extracted chunks.
            file_infos: Optional file info for importance scoring.
            config: Override selection config.

        Returns:
            SelectionResult with chosen chunks.
        """
        cfg = config or self._config

        # Collect all chunks with file importance context
        file_importance: dict[str, float] = {}
        if file_infos:
            file_importance = {f.path: f.importance for f in file_infos}

        all_chunks: list[CodeChunk] = []
        for analysis in analyses:
            for chunk in analysis.chunks:
                # Boost chunk importance with file importance
                file_imp = file_importance.get(analysis.path, 0.5)
                chunk.importance = max(chunk.importance, file_imp)
                all_chunks.append(chunk)

        # Filter by minimum importance
        if cfg.min_importance > 0:
            all_chunks = [c for c in all_chunks if c.importance >= cfg.min_importance]

        # Apply strategy
        if cfg.strategy == SelectionStrategy.RELEVANCE and cfg.query:
            scored_chunks = self._score_by_relevance(all_chunks, cfg.query)
        elif cfg.strategy == SelectionStrategy.BREADTH:
            scored_chunks = self._score_by_breadth(all_chunks, analyses)
        elif cfg.strategy == SelectionStrategy.DEPTH:
            scored_chunks = self._score_by_depth(all_chunks, analyses)
        else:
            scored_chunks = self._score_by_importance(all_chunks)

        # Select chunks within token budget
        selected: list[CodeChunk] = []
        total_tokens = 0
        file_chunk_counts: dict[str, int] = {}

        for chunk, _score in scored_chunks:
            # Respect per-file limit
            file_count = file_chunk_counts.get(chunk.file_path, 0)
            if file_count >= cfg.max_chunks_per_file:
                continue

            # Prefer signatures over full content
            content = chunk.signature if (cfg.prefer_signatures and chunk.signature) else chunk.content
            chunk_tokens = estimate_tokens(content)

            if total_tokens + chunk_tokens > cfg.max_tokens:
                continue

            selected.append(chunk)
            total_tokens += chunk_tokens
            file_chunk_counts[chunk.file_path] = file_count + 1

        files_represented = len(set(c.file_path for c in selected))
        budget_used = total_tokens / cfg.max_tokens if cfg.max_tokens > 0 else 0.0

        return SelectionResult(
            chunks=selected,
            total_tokens=total_tokens,
            files_represented=files_represented,
            strategy_used=cfg.strategy,
            budget_used=min(budget_used, 1.0),
        )

    def _score_by_importance(self, chunks: list[CodeChunk]) -> list[tuple[CodeChunk, float]]:
        """Score chunks by importance (higher = better)."""
        scored = [(c, c.importance) for c in chunks]
        scored.sort(key=lambda x: -x[1])
        return scored

    def _score_by_relevance(self, chunks: list[CodeChunk], query: str) -> list[tuple[CodeChunk, float]]:
        """Score chunks by relevance to a query."""
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        scored: list[tuple[CodeChunk, float]] = []
        for chunk in chunks:
            score = 0.0
            name_lower = chunk.name.lower()
            content_lower = chunk.content.lower()

            # Name matches
            for term in query_terms:
                if term in name_lower:
                    score += 2.0
                if term in content_lower:
                    score += 0.5

            # Exact name match bonus
            if query_lower in name_lower:
                score += 5.0

            # Docstring relevance
            if chunk.docstring:
                doc_lower = chunk.docstring.lower()
                for term in query_terms:
                    if term in doc_lower:
                        score += 1.0

            # Base importance as tiebreaker
            score += chunk.importance * 0.1

            scored.append((chunk, score))

        scored.sort(key=lambda x: -x[1])
        return scored

    def _score_by_breadth(
        self,
        chunks: list[CodeChunk],
        analyses: list[FileAnalysis],
    ) -> list[tuple[CodeChunk, float]]:
        """Score to maximize file coverage."""
        # Group by file and pick best from each
        by_file: dict[str, list[CodeChunk]] = {}
        for chunk in chunks:
            by_file.setdefault(chunk.file_path, []).append(chunk)

        scored: list[tuple[CodeChunk, float]] = []
        num_files = len(by_file)

        for file_path, file_chunks in by_file.items():
            # Sort file's chunks by importance
            file_chunks.sort(key=lambda c: -c.importance)
            for i, chunk in enumerate(file_chunks):
                # First chunk per file gets highest score
                file_bonus = 10.0 / (i + 1)  # Diminishing returns within file
                score = file_bonus + chunk.importance
                scored.append((chunk, score))

        scored.sort(key=lambda x: -x[1])
        return scored

    def _score_by_depth(
        self,
        chunks: list[CodeChunk],
        analyses: list[FileAnalysis],
    ) -> list[tuple[CodeChunk, float]]:
        """Score to maximize depth in key files."""
        # Find top files by total importance
        file_total_importance: dict[str, float] = {}
        for chunk in chunks:
            file_total_importance[chunk.file_path] = (
                file_total_importance.get(chunk.file_path, 0.0) + chunk.importance
            )

        # Sort files by total importance
        ranked_files = sorted(file_total_importance.items(), key=lambda x: -x[1])
        top_files = {f for f, _ in ranked_files[:5]}  # Focus on top 5 files

        scored: list[tuple[CodeChunk, float]] = []
        for chunk in chunks:
            if chunk.file_path in top_files:
                score = chunk.importance * 3.0  # Boost chunks from key files
            else:
                score = chunk.importance * 0.5  # Penalize other files
            scored.append((chunk, score))

        scored.sort(key=lambda x: -x[1])
        return scored

    def format_selection(self, result: SelectionResult) -> str:
        """Format selected chunks into a context string."""
        if not result.chunks:
            return ""

        parts: list[str] = []
        current_file = ""

        for chunk in result.chunks:
            if chunk.file_path != current_file:
                current_file = chunk.file_path
                parts.append(f"\n--- {current_file} ---")

            if chunk.signature:
                parts.append(chunk.signature)
            else:
                parts.append(chunk.content)

        return "\n".join(parts)

    def get_enhanced_context(
        self,
        analyses: list[FileAnalysis],
        file_infos: list[FileInfo] | None = None,
        *,
        lsp_symbols: dict[str, float] | None = None,
        config: SelectionConfig | None = None,
    ) -> SelectionResult:
        """Enhanced context selection with LSP symbol boost.

        When LSP data is available, boosts the importance of chunks
        that match LSP-resolved symbols (definitions, references).

        Args:
            analyses: Analyzed files.
            file_infos: Optional file importance info.
            lsp_symbols: Map of symbol_name -> boost_factor from LSP.
            config: Override selection config.

        Returns:
            SelectionResult with LSP-boosted chunks.
        """
        cfg = config or self._config

        # Apply LSP boost to chunk importance
        if lsp_symbols:
            for analysis in analyses:
                for chunk in analysis.chunks:
                    # Check if chunk name matches any LSP symbol
                    for symbol, boost in lsp_symbols.items():
                        if symbol.lower() in chunk.name.lower():
                            chunk.importance = min(1.0, chunk.importance + boost * 0.3)
                            break

                    # Check if chunk content references LSP symbols
                    content_lower = chunk.content.lower()
                    ref_count = sum(
                        1 for sym in lsp_symbols
                        if sym.lower() in content_lower
                    )
                    if ref_count > 0:
                        chunk.importance = min(1.0, chunk.importance + ref_count * 0.05)

        return self.select(analyses, file_infos, config=cfg)

    def incremental_expand(
        self,
        analyses: list[FileAnalysis],
        file_infos: list[FileInfo] | None = None,
        *,
        initial_budget: int = 2000,
        max_budget: int = 8000,
        step_size: int = 1000,
        query: str = "",
    ) -> tuple[SelectionResult, list[ExpansionStep]]:
        """Budget-aware incremental context expansion.

        Starts with a small token budget and iteratively expands,
        adding chunks in order of decreasing value. Tracks each
        expansion step for transparency.

        Args:
            analyses: Analyzed files.
            file_infos: Optional file importance info.
            initial_budget: Starting token budget.
            max_budget: Maximum token budget.
            step_size: Tokens to add per expansion step.
            query: Optional query for relevance scoring.

        Returns:
            Tuple of (final SelectionResult, list of expansion steps).
        """
        steps: list[ExpansionStep] = []
        current_budget = initial_budget
        last_result: SelectionResult | None = None

        while current_budget <= max_budget:
            cfg = SelectionConfig(
                max_tokens=current_budget,
                strategy=SelectionStrategy.RELEVANCE if query else SelectionStrategy.IMPORTANCE,
                query=query,
                prefer_signatures=current_budget < 4000,  # Signatures only for small budgets
            )

            result = self.select(analyses, file_infos, config=cfg)

            chunks_added = (
                len(result.chunks) - len(last_result.chunks) if last_result else len(result.chunks)
            )
            tokens_added = (
                result.total_tokens - last_result.total_tokens if last_result else result.total_tokens
            )

            steps.append(ExpansionStep(
                chunks_added=chunks_added,
                tokens_added=tokens_added,
                total_tokens=result.total_tokens,
                strategy=str(cfg.strategy),
                budget_remaining=current_budget - result.total_tokens,
            ))

            last_result = result

            # Stop if we didn't add anything new (all chunks exhausted)
            if chunks_added == 0:
                break

            current_budget += step_size

        return last_result or SelectionResult(
            chunks=[], total_tokens=0, files_represented=0,
            strategy_used=SelectionStrategy.IMPORTANCE, budget_used=0.0,
        ), steps

    def ranked_search(
        self,
        analyses: list[FileAnalysis],
        query: str,
        *,
        file_infos: list[FileInfo] | None = None,
        recency_scores: dict[str, float] | None = None,
        edit_frequency: dict[str, int] | None = None,
        import_graph: dict[str, list[str]] | None = None,
        max_results: int = 20,
    ) -> list[RankedSearchResult]:
        """Multi-factor relevance-ranked search.

        Scores chunks using multiple factors:
        - Text relevance: keyword matching against query
        - Importance: base chunk importance score
        - Recency: how recently the file was modified
        - Edit frequency: how often the file has been edited this session
        - Import distance: proximity in the import graph

        Args:
            analyses: Analyzed files.
            query: Search query.
            file_infos: File importance info.
            recency_scores: file_path -> recency score (0-1, higher=more recent).
            edit_frequency: file_path -> edit count this session.
            import_graph: file_path -> list of imported file paths.
            max_results: Maximum results to return.

        Returns:
            List of RankedSearchResult sorted by total score.
        """
        file_importance = {f.path: f.importance for f in file_infos} if file_infos else {}
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        results: list[RankedSearchResult] = []

        for analysis in analyses:
            for chunk in analysis.chunks:
                factors: dict[str, float] = {}

                # Factor 1: Text relevance (0-10)
                text_score = 0.0
                name_lower = chunk.name.lower()
                content_lower = chunk.content.lower()
                for term in query_terms:
                    if term in name_lower:
                        text_score += 3.0
                    if term in content_lower:
                        text_score += 0.5
                if query_lower in name_lower:
                    text_score += 5.0
                factors["relevance"] = min(10.0, text_score)

                # Factor 2: Importance (0-3)
                imp = file_importance.get(analysis.path, chunk.importance)
                factors["importance"] = imp * 3.0

                # Factor 3: Recency (0-2)
                if recency_scores:
                    recency = recency_scores.get(analysis.path, 0.0)
                    factors["recency"] = recency * 2.0

                # Factor 4: Edit frequency (0-2)
                if edit_frequency:
                    freq = edit_frequency.get(analysis.path, 0)
                    factors["edit_frequency"] = min(2.0, freq * 0.5)

                # Factor 5: Import distance (0-1.5)
                if import_graph:
                    # Boost files imported by the query's likely location
                    imported_by_count = sum(
                        1 for deps in import_graph.values()
                        if analysis.path in deps
                    )
                    factors["import_proximity"] = min(1.5, imported_by_count * 0.3)

                total = sum(factors.values())

                if total > 0.5:  # Minimum threshold
                    results.append(RankedSearchResult(
                        chunk=chunk,
                        total_score=total,
                        factors=factors,
                    ))

        results.sort(key=lambda r: -r.total_score)
        return results[:max_results]
