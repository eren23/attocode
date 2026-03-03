"""Embedding provider abstraction for semantic search.

Tries providers in order:
1. Local: sentence-transformers (no API cost, ~22MB model)
2. API: OpenAI text-embedding-3-small (if OPENAI_API_KEY set)
3. None: graceful degradation (returns empty vectors)
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract embedding provider."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of vectors."""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging."""
        ...


class LocalEmbeddingProvider(EmbeddingProvider):
    """Local embeddings via sentence-transformers (all-MiniLM-L6-v2)."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        self._model = SentenceTransformer("all-MiniLM-L6-v2")
        self._dim = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return "local:all-MiniLM-L6-v2"


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embeddings via text-embedding-3-small."""

    def __init__(self, api_key: str | None = None) -> None:
        import openai  # type: ignore[import-untyped]
        self._client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self._dim = 1536

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        return [item.embedding for item in response.data]

    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return "openai:text-embedding-3-small"


class NullEmbeddingProvider(EmbeddingProvider):
    """Fallback provider that returns empty vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]

    def dimension(self) -> int:
        return 0

    @property
    def name(self) -> str:
        return "none"


def create_embedding_provider() -> EmbeddingProvider:
    """Create the best available embedding provider.

    Tries in order: local sentence-transformers, OpenAI API, null fallback.
    """
    # Try local first (no API cost)
    try:
        provider = LocalEmbeddingProvider()
        logger.info("Using local embedding provider: %s", provider.name)
        return provider
    except ImportError:
        logger.debug("sentence-transformers not installed, trying OpenAI")
    except Exception:
        logger.debug("Local embedding provider failed", exc_info=True)

    # Try OpenAI API
    if os.environ.get("OPENAI_API_KEY"):
        try:
            provider = OpenAIEmbeddingProvider()
            logger.info("Using OpenAI embedding provider: %s", provider.name)
            return provider
        except ImportError:
            logger.debug("openai package not installed")
        except Exception:
            logger.debug("OpenAI embedding provider failed", exc_info=True)

    # Graceful degradation
    logger.info("No embedding provider available; semantic search will use keyword fallback")
    return NullEmbeddingProvider()
