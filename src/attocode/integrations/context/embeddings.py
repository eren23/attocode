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


class NomicEmbeddingProvider(EmbeddingProvider):
    """Local embeddings via nomic-embed-text (137M params, better code understanding)."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        logger.warning(
            "Loading nomic-embed-text with trust_remote_code=True — "
            "this executes code from the model repository"
        )
        self._model = SentenceTransformer(
            "nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True,
        )
        self._dim = 768

    def embed(self, texts: list[str]) -> list[list[float]]:
        # nomic-embed-text recommends prefixing with task type
        prefixed = [f"search_document: {t}" for t in texts]
        embeddings = self._model.encode(prefixed, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return "local:nomic-embed-text-v1.5"


class NullEmbeddingProvider(EmbeddingProvider):
    """Fallback provider that returns empty vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]

    def dimension(self) -> int:
        return 0

    @property
    def name(self) -> str:
        return "none"


_provider_cache: dict[str, EmbeddingProvider] = {}


def create_embedding_provider(
    model: str = "",
) -> EmbeddingProvider:
    """Create the best available embedding provider.

    Args:
        model: Preferred model name. Options:
            - "all-MiniLM-L6-v2" (default, 384-dim, fast)
            - "nomic-embed-text" (768-dim, better code understanding)
            - "openai" (API-based, requires OPENAI_API_KEY)
            - "" (auto-detect best available)

    Tries in order: local sentence-transformers, OpenAI API, null fallback.
    """
    model = model or os.environ.get("ATTOCODE_EMBEDDING_MODEL", "")

    if model in _provider_cache:
        return _provider_cache[model]

    # Explicit local default request
    if model == "all-MiniLM-L6-v2":
        try:
            provider = LocalEmbeddingProvider()
            logger.info("Using embedding provider: %s", provider.name)
            _provider_cache[model] = provider
            return provider
        except ImportError:
            raise ImportError(
                f"Embedding model '{model}' requires sentence-transformers. "
                "Install with: pip install attocode[semantic]"
            )

    # Explicit nomic request
    if model == "nomic-embed-text":
        try:
            provider = NomicEmbeddingProvider()
            logger.info("Using embedding provider: %s", provider.name)
            _provider_cache[model] = provider
            return provider
        except ImportError:
            raise ImportError(
                f"Embedding model '{model}' requires sentence-transformers and einops. "
                "Install with: pip install attocode[semantic-nomic]"
            )

    # Explicit OpenAI request
    if model == "openai":
        try:
            provider = OpenAIEmbeddingProvider()
            logger.info("Using embedding provider: %s", provider.name)
            _provider_cache[model] = provider
            return provider
        except ImportError:
            raise ImportError(
                "OpenAI embeddings require the openai package. "
                "Install with: pip install attocode[openai]"
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI embedding provider failed: {e}") from e

    # Auto-detect: try local first (no API cost)
    try:
        provider = LocalEmbeddingProvider()
        logger.info("Using local embedding provider: %s", provider.name)
        _provider_cache[model] = provider
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
            _provider_cache[model] = provider
            return provider
        except ImportError:
            logger.debug("openai package not installed")
        except Exception:
            logger.debug("OpenAI embedding provider failed", exc_info=True)

    # Graceful degradation — don't cache so retry picks up newly installed packages
    logger.info("No embedding provider available; semantic search will use keyword fallback")
    return NullEmbeddingProvider()
