"""Cross-encoder reranking for search results.

Provides optional reranking using a cross-encoder model to improve
precision after initial retrieval. Gracefully degrades if the model
is not available.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Singleton cache for the cross-encoder model
_reranker_instance: CrossEncoderReranker | None = None
_reranker_lock = threading.Lock()


def get_reranker(
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
) -> CrossEncoderReranker:
    """Get or create the singleton CrossEncoderReranker instance."""
    global _reranker_instance
    if _reranker_instance is not None and _reranker_instance._model_name == model_name:
        return _reranker_instance
    with _reranker_lock:
        # Double-check after acquiring lock
        if _reranker_instance is not None and _reranker_instance._model_name == model_name:
            return _reranker_instance
        _reranker_instance = CrossEncoderReranker(model_name=model_name)
        return _reranker_instance


class CrossEncoderReranker:
    """Optional cross-encoder reranking for search results.

    Uses a lightweight cross-encoder model to score (query, document) pairs
    for more precise relevance ranking. Falls back to returning candidates
    unchanged if the model cannot be loaded.

    Usage::

        reranker = get_reranker()
        reranked = reranker.rerank(
            query="authentication middleware",
            candidates=[("id1", "text1", 0.8), ("id2", "text2", 0.6)],
            top_k=10,
        )
    """

    def __init__(
        self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._available = False
        self._load_attempted = False
        self._load_lock = threading.Lock()

    def _ensure_loaded(self) -> bool:
        """Lazy-load the cross-encoder model. Returns True if available."""
        if self._load_attempted:
            return self._available
        with self._load_lock:
            if self._load_attempted:
                return self._available
            self._load_attempted = True
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(self._model_name)
                self._available = True
                logger.info(
                    "Cross-encoder reranker loaded: %s", self._model_name,
                )
            except ImportError:
                logger.warning(
                    "sentence-transformers not installed; "
                    "cross-encoder reranking disabled. "
                    "Install with: pip install sentence-transformers",
                )
                self._available = False
            except Exception:
                logger.warning(
                    "Failed to load cross-encoder model %s; "
                    "reranking disabled",
                    self._model_name,
                    exc_info=True,
                )
                self._available = False
            return self._available

    @property
    def is_available(self) -> bool:
        """Check if the reranker model is loaded and usable."""
        return self._available

    def rerank(
        self,
        query: str,
        candidates: list[tuple[str, str, float]],
        top_k: int = 10,
    ) -> list[tuple[str, str, float]]:
        """Rerank candidates using the cross-encoder model.

        Args:
            query: The search query.
            candidates: List of (id, text, original_score) tuples.
            top_k: Number of results to return after reranking.

        Returns:
            Reranked list of (id, text, reranker_score) tuples,
            or the original candidates (truncated to top_k) if
            reranking is not available.
        """
        if not candidates:
            return []

        if not self._ensure_loaded():
            # Graceful degradation: return candidates as-is
            return candidates[:top_k]

        # Build (query, document) pairs for cross-encoder scoring
        pairs = [(query, text) for _, text, _ in candidates]

        try:
            scores = self._model.predict(pairs)
        except Exception:
            logger.warning(
                "Cross-encoder prediction failed; returning original ranking",
                exc_info=True,
            )
            return candidates[:top_k]

        # Attach scores and sort descending
        scored = [
            (cid, text, float(score))
            for (cid, text, _), score in zip(candidates, scores, strict=False)
        ]
        scored.sort(key=lambda x: x[2], reverse=True)
        return scored[:top_k]
