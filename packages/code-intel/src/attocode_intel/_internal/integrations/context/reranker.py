"""Cross-encoder reranking for search results.

Provides optional reranking using a cross-encoder model to improve
precision after initial retrieval. Gracefully degrades if the model
is not available.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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


def model_tree_sha256(model_path: str | Path) -> str:
    """Fingerprint a locally installed model, including every file's contents.

    The digest is for deployment pinning, not for use on a search request. The
    caller can compute it once when installing weights and configure that value
    as ``expected_sha256``. Symlinks are rejected so the fingerprint cannot
    silently depend on files outside the chosen model directory.
    """
    path = Path(model_path)
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise ValueError("model_path must be an existing absolute directory")
    digest = hashlib.sha256()
    files = sorted(path.rglob("*"))
    if not files or not any(item.is_file() for item in files):
        raise ValueError("model_path contains no files")
    for item in files:
        if item.is_symlink():
            raise ValueError("model_path must not contain symlinks")
        if not item.is_file():
            continue
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with item.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class LocalRerankOutcome:
    """Result plus a compact, source-free fallback reason for provenance."""

    candidates: list[tuple[str, str, float]]
    reranked: bool
    fallback_reason: str | None = None


RankingOutcome = LocalRerankOutcome


class RankingProvider(Protocol):
    """Shared shortlist contract for local and SystemOne-compatible adapters."""

    max_candidates: int

    @property
    def status(self) -> str: ...

    @property
    def is_available(self) -> bool: ...

    def rerank_result(
        self, query: str, candidates: list[tuple[str, str, float]], top_k: int = 10,
    ) -> RankingOutcome: ...


class LocalCrossEncoderReranker:
    """Opt-in offline reranking with preinstalled, fingerprint-pinned weights.

    Construction never loads weights. ``start_prewarm`` does that in a daemon
    worker; until it completes, search calls use the original order. At most
    one prediction runs at a time, and a timed-out prediction keeps the slot
    until it finishes, preventing an unbounded queue of background work.
    This class deliberately does not replace the legacy lazy-loading reranker.
    """

    def __init__(
        self,
        model_path: str | Path,
        expected_sha256: str,
        *,
        max_candidates: int = 24,
        max_query_chars: int = 512,
        max_excerpt_chars: int = 2048,
        timeout_seconds: float = 1.5,
    ) -> None:
        path = Path(model_path)
        if not path.is_absolute():
            raise ValueError("model_path must be absolute")
        if re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256) is None:
            raise ValueError("expected_sha256 must be a SHA-256 hex digest")
        if min(max_candidates, max_query_chars, max_excerpt_chars) < 1:
            raise ValueError("input bounds must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.model_path = path
        self.expected_sha256 = expected_sha256.lower()
        self.max_candidates = max_candidates
        self.max_query_chars = max_query_chars
        self.max_excerpt_chars = max_excerpt_chars
        self.timeout_seconds = timeout_seconds
        self._model: Any = None
        self._status = "cold"
        self._state_lock = threading.Lock()
        self._prediction_lock = threading.Lock()

    @property
    def status(self) -> str:
        """One of ``cold``, ``loading``, ``ready``, or ``failed``."""
        with self._state_lock:
            return self._status

    @property
    def is_available(self) -> bool:
        return self.status == "ready"

    def start_prewarm(self) -> bool:
        """Begin one asynchronous, offline load. Return False if already begun."""
        with self._state_lock:
            if self._status != "cold":
                return False
            self._status = "loading"
        threading.Thread(target=self._prewarm, name="local-reranker-prewarm", daemon=True).start()
        return True

    def _prewarm(self) -> None:
        try:
            actual_sha256 = model_tree_sha256(self.model_path)
            if not hmac.compare_digest(actual_sha256, self.expected_sha256):
                raise ValueError("model fingerprint mismatch")
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(
                str(self.model_path),
                local_files_only=True,
                trust_remote_code=False,
            )
        except Exception:
            # Never log a source snippet or a model's local path.
            logger.warning("Local cross-encoder prewarm failed; deterministic ranking remains active")
            with self._state_lock:
                self._status = "failed"
            return
        with self._state_lock:
            self._model = model
            self._status = "ready"

    def rerank_result(
        self,
        query: str,
        candidates: list[tuple[str, str, float]],
        top_k: int = 10,
    ) -> LocalRerankOutcome:
        """Rerank bounded pairs, or immediately return deterministic order."""
        fallback = candidates[:max(0, top_k)]
        if top_k <= 0 or not candidates:
            return LocalRerankOutcome(fallback, False, "empty")
        if not query.strip():
            return LocalRerankOutcome(fallback, False, "empty_query")
        if not self.is_available:
            return LocalRerankOutcome(fallback, False, self.status)
        if not self._prediction_lock.acquire(blocking=False):
            return LocalRerankOutcome(fallback, False, "busy")

        bounded = candidates[: self.max_candidates]
        pairs = [
            (query[: self.max_query_chars], excerpt[: self.max_excerpt_chars])
            for _, excerpt, _ in bounded
        ]
        done = threading.Event()
        output: list[Any] = []

        def predict() -> None:
            try:
                output.append(self._model.predict(pairs, batch_size=8, show_progress_bar=False))
            except Exception:
                output.append(None)
            finally:
                self._prediction_lock.release()
                done.set()

        threading.Thread(target=predict, name="local-reranker-predict", daemon=True).start()
        if not done.wait(self.timeout_seconds):
            return LocalRerankOutcome(fallback, False, "timeout")
        scores = output[0] if output else None
        try:
            if scores is None or len(scores) != len(bounded):
                raise ValueError("invalid score count")
            numeric_scores = [float(score) for score in scores]
            if not all(math.isfinite(score) for score in numeric_scores):
                raise ValueError("non-finite score")
        except (TypeError, ValueError, OverflowError):
            return LocalRerankOutcome(fallback, False, "prediction_failed")
        scored = [
            (candidate_id, excerpt, score)
            for (candidate_id, excerpt, _), score in zip(bounded, numeric_scores, strict=True)
        ]
        scored.sort(key=lambda item: item[2], reverse=True)
        # Never drop an unscored tail if a caller requests more than the cap.
        return LocalRerankOutcome((scored + candidates[self.max_candidates :])[:top_k], True)

    def rerank(
        self,
        query: str,
        candidates: list[tuple[str, str, float]],
        top_k: int = 10,
    ) -> list[tuple[str, str, float]]:
        """Compatibility-shaped wrapper for callers that only need results."""
        return self.rerank_result(query, candidates, top_k).candidates
