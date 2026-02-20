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
