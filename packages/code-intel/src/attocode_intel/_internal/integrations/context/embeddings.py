"""Embedding provider abstraction for semantic search.

Tries providers in order:
1. Local: sentence-transformers with code-optimized model (no API cost)
2. Local: sentence-transformers with general model (smaller fallback)
3. API: OpenAI text-embedding-3-small (if OPENAI_API_KEY set)
4. None: graceful degradation (returns empty vectors)
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract embedding provider."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of vectors."""
        ...

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        """Embed query texts. Symmetric providers reuse embed(); asymmetric
        providers (e.g. nomic) override with a query-specific prefix."""
        return self.embed(texts)

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

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        # Queries use a different prefix than documents (asymmetric model).
        prefixed = [f"search_query: {t}" for t in texts]
        embeddings = self._model.encode(prefixed, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return "local:nomic-embed-text-v1.5"


class CodeEmbeddingProvider(EmbeddingProvider):
    """Local embeddings via BAAI/bge-base-en-v1.5 (768-dim, ~440MB model).

    Significantly outperforms all-MiniLM-L6-v2 on code search tasks due to
    larger model capacity and better handling of code tokens (identifiers,
    camelCase, snake_case, function signatures).

    Note: Switching models requires reindexing (different vector dimensions).
    """

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        self._model = SentenceTransformer("BAAI/bge-base-en-v1.5")
        self._dim = 768

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return "local:bge-base-en-v1.5"


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
            - "bge" (768-dim, recommended for code search)
            - "all-MiniLM-L6-v2" (384-dim, fast, smaller)
            - "nomic-embed-text" (768-dim, better code understanding)
            - "openai" (API-based, requires OPENAI_API_KEY)
            - "" (auto-detect best available)

    Auto-detect order: bge (code-optimized) > MiniLM > OpenAI API > null.
    Note: switching models requires reindexing (different vector dims).
    """
    model = model or os.environ.get("ATTOCODE_EMBEDDING_MODEL", "")

    if model in _provider_cache:
        return _provider_cache[model]

    # Explicit BGE request (code-optimized)
    if model == "bge":
        try:
            provider = CodeEmbeddingProvider()
            logger.info("Using embedding provider: %s", provider.name)
            _provider_cache[model] = provider
            return provider
        except ImportError:
            raise ImportError(
                f"Embedding model '{model}' requires sentence-transformers. "
                "Install with: pip install attocode[semantic]"
            )

    # Explicit MiniLM request
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

    # Auto-detect: code-trained nomic first, then BGE, then MiniLM (no API cost)
    try:
        provider = NomicEmbeddingProvider()
        logger.info("Using code-trained embedding provider: %s", provider.name)
        _provider_cache[model] = provider
        return provider
    except Exception as exc:
        logger.info("nomic unavailable (%s), trying BGE", exc)
    try:
        provider = CodeEmbeddingProvider()
        logger.info("Using code-optimized embedding provider: %s", provider.name)
        _provider_cache[model] = provider
        return provider
    except ImportError:
        logger.debug("sentence-transformers not installed, trying OpenAI")
    except Exception as exc:
        logger.info("BGE model unavailable (%s), falling back to MiniLM", exc)
        try:
            provider = LocalEmbeddingProvider()
            logger.info("Using local embedding provider: %s", provider.name)
            _provider_cache[model] = provider
            return provider
        except ImportError:
            logger.debug("sentence-transformers not installed, trying OpenAI")
        except Exception as exc2:
            logger.warning("Local embedding provider unavailable: %s", exc2)
            logger.debug("Local embedding provider traceback", exc_info=True)

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


_DATE_SUFFIX = re.compile(r"-(\d{4}|\d{8}|\d{4}-\d{2}(-\d{2})?)$")


def _same_model(want: str, got: object) -> bool:
    """Hosted routers drop the provider prefix and add a dated snapshot suffix."""
    def base(name: str) -> str:
        return _DATE_SUFFIX.sub("", name.rsplit("/", 1)[-1])
    return isinstance(got, str) and base(want) == base(got)


class _RefusedError(Exception):
    """The provider refused the inputs (400/413); split the batch."""


class OpenRouterEmbeddingProvider(EmbeddingProvider):
    """Opt-in hosted voyage-code-4 through OpenRouter. Sends source text off the machine.

    Only ``create_hosted_provider`` makes one, after the hosted-rerank consent.
    Construction makes no request. A text that fails gets an empty vector, which
    the index skips. 401/402/403 set ``abort``; later calls then make no request.
    """

    endpoint = "https://openrouter.ai/api/v1/embeddings"
    model = "voyageai/voyage-code-4"
    auth_env = "OPENROUTER_API_KEY"
    store_file = "embeddings-openrouter.db"
    index_batch = 4096
    remote = True
    max_inputs, max_chars, workers = 32, 40_000, 8
    backoff = (2, 4, 8, 16, 32)
    max_bytes = 4 * 1024 * 1024

    def __init__(self, transport: Any = None, timeout_seconds: float = 60.0) -> None:
        self._transport = transport
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self.requests = self.tokens = 0
        self.cost = 0.0
        self.abort: str | None = None
        self.sleep = time.sleep

    def dimension(self) -> int:
        return 1024

    @property
    def name(self) -> str:
        return "openrouter:voyage-code-4"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "search_document", attempts=6)

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        # ponytail: 2 attempts so a stalled endpoint delays search by at most ~2 timeouts.
        return self._embed(texts, "search_query", attempts=2)

    def _embed(self, texts: list[str], input_type: str, attempts: int) -> list[list[float]]:
        out: list[list[float]] = [[] for _ in texts]
        batches: list[list[int]] = []
        size = 0
        for i, text in enumerate(texts):
            if not batches or len(batches[-1]) >= self.max_inputs or size + len(text) > self.max_chars:
                batches.append([])
                size = 0
            batches[-1].append(i)
            size += len(text)

        def run(idx: list[int]) -> None:
            for i, vec in zip(idx, self._split([texts[i] for i in idx], input_type, attempts), strict=True):
                out[i] = vec

        if len(batches) <= 1:
            for idx in batches:
                run(idx)
        else:
            with ThreadPoolExecutor(self.workers) as pool:
                list(pool.map(run, batches))
        return out

    def _split(self, texts: list[str], input_type: str, attempts: int) -> list[list[float]]:
        try:
            return self._call(texts, input_type, attempts)
        except _RefusedError:
            if len(texts) == 1:
                return [[]]
            half = len(texts) // 2
            return (self._split(texts[:half], input_type, attempts)
                    + self._split(texts[half:], input_type, attempts))
        except RuntimeError:
            return [[] for _ in texts]

    def _post(self, body: dict) -> object:
        from attocode_intel._internal.integrations.context.systemone_ranker import post_json

        headers = {"Authorization": f"Bearer {os.environ.get(self.auth_env, '')}"}
        return post_json(self.endpoint, body, headers, self._timeout, self._transport, self.max_bytes)

    def _call(self, texts: list[str], input_type: str, attempts: int) -> list[list[float]]:
        body = {
            "model": self.model, "input": texts, "encoding_format": "float",
            "input_type": input_type, "provider": {"data_collection": "deny"},
        }
        for attempt in range(attempts):
            with self._lock:
                if self.abort:
                    raise RuntimeError(self.abort)
                self.requests += 1
            status: object = None
            try:
                data = self._post(body)
                error = data.get("error") if isinstance(data, dict) else None
                if isinstance(error, dict):
                    status = error.get("code")
                else:
                    return self._vectors(data, len(texts))
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, OSError):
                status = None  # transport error or invalid response: retry
            if status in (400, 413):
                raise _RefusedError(str(status))
            if isinstance(status, int) and status not in (408, 429) and status < 500:
                with self._lock:
                    self.abort = self.abort or f"status {status}"
                raise RuntimeError(self.abort)
            if attempt < attempts - 1:
                self.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
        raise RuntimeError("embedding request failed")

    def _vectors(self, data: Any, n: int) -> list[list[float]]:
        items = data.get("data")
        if not _same_model(self.model, data.get("model")) or not isinstance(items, list) or len(items) != n:
            raise ValueError("wrong model or count")
        items = sorted(items, key=lambda item: item["index"])
        if [item["index"] for item in items] != list(range(n)):
            raise ValueError("wrong indexes")
        vecs = []
        for item in items:
            vec = [float(x) for x in item["embedding"]]
            norm = math.sqrt(sum(x * x for x in vec))
            if len(vec) != self.dimension() or not all(math.isfinite(x) for x in vec) or norm == 0:
                raise ValueError("wrong vector")
            vecs.append([x / norm for x in vec])
        usage = data.get("usage") or {}
        cost = usage.get("cost")
        with self._lock:
            self.tokens += int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
            self.cost += float(cost) if isinstance(cost, int | float) else 0.0
        return vecs


def create_hosted_provider(kind: str, project_dir: str) -> OpenRouterEmbeddingProvider:
    """The opt-in hosted provider. Raises ``ValueError`` if a consent check refuses it."""
    from attocode_intel._internal.integrations.context.systemone_ranker import (
        check_endpoint,
        workspace_consent,
    )

    if kind != "openrouter":
        raise ValueError(f"unknown hosted embedding provider: {kind}")
    opt_in = os.environ.get("ATTOCODE_INTEL_RANKING_ALLOW_REMOTE", "").lower() in {"1", "true", "yes", "on"}
    workspace = os.environ.get("ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE", "")
    check_endpoint(
        OpenRouterEmbeddingProvider.endpoint,
        allow_remote=workspace_consent(opt_in, workspace, project_dir),
        service_mode=bool(os.environ.get("DATABASE_URL")),
        auth_env=OpenRouterEmbeddingProvider.auth_env,
    )
    if not os.environ.get(OpenRouterEmbeddingProvider.auth_env):
        raise ValueError(f"{OpenRouterEmbeddingProvider.auth_env} is not set")
    return OpenRouterEmbeddingProvider()
