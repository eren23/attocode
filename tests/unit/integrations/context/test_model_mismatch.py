"""Refuse to serve vectors built by a different embedding model (manual reindex)."""
from __future__ import annotations

from unittest.mock import MagicMock

from attocode.integrations.context.semantic_search import SemanticSearchManager


def test_model_mismatch_skips_vector_search(tmp_path, monkeypatch):
    mgr = SemanticSearchManager(root_dir=str(tmp_path))
    provider = MagicMock()
    provider.name = "local:nomic-embed-text-v1.5"
    provider.embed_query.return_value = [[0.1, 0.2]]
    mgr._provider = provider
    mgr._keyword_fallback = False
    store = MagicMock()
    store.count.return_value = 5
    store.model_name = "local:bge-base-en-v1.5"  # different model on disk
    store.search.return_value = []
    mgr._store = store
    monkeypatch.setattr(SemanticSearchManager, "_ensure_provider", lambda self: None)
    monkeypatch.setattr(SemanticSearchManager, "_keyword_search", lambda self, *a, **k: [])

    mgr.search("anything", top_k=5, two_stage=False)
    assert store.search.call_count == 0  # vectors skipped on mismatch


def test_model_match_allows_vector_search(tmp_path, monkeypatch):
    mgr = SemanticSearchManager(root_dir=str(tmp_path))
    provider = MagicMock()
    provider.name = "local:nomic-embed-text-v1.5"
    provider.embed_query.return_value = [[0.1, 0.2]]
    mgr._provider = provider
    mgr._keyword_fallback = False
    store = MagicMock()
    store.count.return_value = 5
    store.model_name = "local:nomic-embed-text-v1.5"
    store.search.return_value = []
    mgr._store = store
    monkeypatch.setattr(SemanticSearchManager, "_ensure_provider", lambda self: None)

    mgr.search("anything", top_k=5, two_stage=False)
    assert store.search.call_count == 1
