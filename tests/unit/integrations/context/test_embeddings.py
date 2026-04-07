"""Tests for embedding provider abstraction and model selection."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from attocode.integrations.context.embeddings import (
    CodeEmbeddingProvider,
    EmbeddingProvider,
    LocalEmbeddingProvider,
    NullEmbeddingProvider,
    _provider_cache,
    create_embedding_provider,
)


@pytest.fixture(autouse=True)
def _clear_provider_cache() -> None:
    """Clear the module-level provider cache between tests."""
    _provider_cache.clear()


# ============================================================
# CodeEmbeddingProvider Tests
# ============================================================


class TestCodeEmbeddingProvider:
    """Tests for the BGE code-optimized embedding provider."""

    def test_initialization_loads_bge_model(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        mock_model = MagicMock()
        mock_st.SentenceTransformer.return_value = mock_model
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider = CodeEmbeddingProvider()

        mock_st.SentenceTransformer.assert_called_once_with("BAAI/bge-base-en-v1.5")
        assert provider._model is mock_model

    def test_dimension_returns_768(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider = CodeEmbeddingProvider()

        assert provider.dimension() == 768

    def test_name_returns_bge_identifier(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider = CodeEmbeddingProvider()

        assert provider.name == "local:bge-base-en-v1.5"

    def test_embed_calls_model_encode(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        mock_model = MagicMock()
        # Simulate numpy-like arrays with .tolist()
        vec1 = MagicMock()
        vec1.tolist.return_value = [0.1, 0.2, 0.3]
        vec2 = MagicMock()
        vec2.tolist.return_value = [0.4, 0.5, 0.6]
        mock_model.encode.return_value = [vec1, vec2]
        mock_st.SentenceTransformer.return_value = mock_model
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider = CodeEmbeddingProvider()
        texts = ["def foo():", "class Bar:"]
        result = provider.embed(texts)

        mock_model.encode.assert_called_once_with(texts, convert_to_numpy=True)
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    def test_embed_empty_input(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = []
        mock_st.SentenceTransformer.return_value = mock_model
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider = CodeEmbeddingProvider()
        result = provider.embed([])

        assert result == []

    def test_is_embedding_provider_subclass(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider = CodeEmbeddingProvider()

        assert isinstance(provider, EmbeddingProvider)


# ============================================================
# create_embedding_provider Tests
# ============================================================


class TestCreateEmbeddingProvider:
    """Tests for model selection and auto-detection logic."""

    def test_explicit_bge_creates_code_embedding_provider(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider = create_embedding_provider("bge")

        assert isinstance(provider, CodeEmbeddingProvider)
        assert provider.name == "local:bge-base-en-v1.5"

    def test_explicit_bge_raises_import_error_when_st_unavailable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Ensure sentence_transformers is not available
        monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

        with patch(
            "attocode.integrations.context.embeddings.CodeEmbeddingProvider.__init__",
            side_effect=ImportError("No module named 'sentence_transformers'"),
        ):
            with pytest.raises(ImportError, match="sentence-transformers"):
                create_embedding_provider("bge")

    def test_auto_detect_tries_bge_first(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider = create_embedding_provider("")

        assert isinstance(provider, CodeEmbeddingProvider)
        assert provider.dimension() == 768

    def test_auto_detect_falls_back_to_minilm_when_bge_fails(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        call_count = 0
        original_init = MagicMock()

        def mock_sentence_transformer(model_name: str, **kwargs):  # noqa: ANN003
            nonlocal call_count
            call_count += 1
            if model_name == "BAAI/bge-base-en-v1.5":
                raise RuntimeError("Failed to load BGE model")
            return MagicMock()

        mock_st.SentenceTransformer.side_effect = mock_sentence_transformer
        # Remove env vars that could interfere
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ATTOCODE_EMBEDDING_MODEL", raising=False)

        provider = create_embedding_provider("")

        assert isinstance(provider, LocalEmbeddingProvider)
        assert provider.name == "local:all-MiniLM-L6-v2"

    def test_auto_detect_falls_back_to_null_when_nothing_available(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When sentence_transformers is not importable and no OpenAI key is set,
        auto-detect should return NullEmbeddingProvider."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ATTOCODE_EMBEDDING_MODEL", raising=False)

        with patch(
            "attocode.integrations.context.embeddings.CodeEmbeddingProvider.__init__",
            side_effect=ImportError("No module named 'sentence_transformers'"),
        ), patch(
            "attocode.integrations.context.embeddings.LocalEmbeddingProvider.__init__",
            side_effect=ImportError("No module named 'sentence_transformers'"),
        ):
            provider = create_embedding_provider("")

        assert isinstance(provider, NullEmbeddingProvider)

    def test_provider_caching(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider1 = create_embedding_provider("bge")
        provider2 = create_embedding_provider("bge")

        assert provider1 is provider2
        assert "bge" in _provider_cache

    def test_auto_detect_caches_under_empty_string_key(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)
        monkeypatch.delenv("ATTOCODE_EMBEDDING_MODEL", raising=False)

        provider = create_embedding_provider("")

        assert "" in _provider_cache
        assert _provider_cache[""] is provider

    def test_null_provider_not_cached(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """NullEmbeddingProvider should not be cached so retry picks up
        newly installed packages."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ATTOCODE_EMBEDDING_MODEL", raising=False)

        with patch(
            "attocode.integrations.context.embeddings.CodeEmbeddingProvider.__init__",
            side_effect=ImportError("nope"),
        ), patch(
            "attocode.integrations.context.embeddings.LocalEmbeddingProvider.__init__",
            side_effect=ImportError("nope"),
        ):
            provider = create_embedding_provider("")

        assert isinstance(provider, NullEmbeddingProvider)
        assert "" not in _provider_cache

    def test_env_var_model_selection(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)
        monkeypatch.setenv("ATTOCODE_EMBEDDING_MODEL", "bge")

        provider = create_embedding_provider("")

        assert isinstance(provider, CodeEmbeddingProvider)
        assert "bge" in _provider_cache

    def test_explicit_minilm_creates_local_provider(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_st = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)

        provider = create_embedding_provider("all-MiniLM-L6-v2")

        assert isinstance(provider, LocalEmbeddingProvider)
        assert provider.dimension() == 384


# ============================================================
# NullEmbeddingProvider Tests
# ============================================================


class TestNullEmbeddingProvider:
    """Tests for graceful degradation fallback."""

    def test_embed_returns_empty_vectors(self) -> None:
        provider = NullEmbeddingProvider()

        result = provider.embed(["hello", "world"])

        assert result == [[], []]

    def test_embed_empty_input(self) -> None:
        provider = NullEmbeddingProvider()

        result = provider.embed([])

        assert result == []

    def test_dimension_returns_zero(self) -> None:
        provider = NullEmbeddingProvider()

        assert provider.dimension() == 0

    def test_name_returns_none(self) -> None:
        provider = NullEmbeddingProvider()

        assert provider.name == "none"

    def test_is_embedding_provider_subclass(self) -> None:
        provider = NullEmbeddingProvider()

        assert isinstance(provider, EmbeddingProvider)
