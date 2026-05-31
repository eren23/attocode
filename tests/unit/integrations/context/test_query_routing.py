"""The query path must embed via embed_query (correct nomic prefix), not embed."""
from __future__ import annotations

from unittest.mock import MagicMock

from attocode.integrations.context.semantic_search import SemanticSearchManager


def test_query_path_calls_embed_query(tmp_path, monkeypatch):
    mgr = SemanticSearchManager(root_dir=str(tmp_path))
    provider = MagicMock()
    provider.name = "local:nomic-embed-text-v1.5"
    provider.embed.return_value = [[0.1, 0.2]]
    provider.embed_query.return_value = [[0.1, 0.2]]
    mgr._provider = provider
    mgr._keyword_fallback = False
    store = MagicMock()
    store.count.return_value = 1
    store.model_name = "local:nomic-embed-text-v1.5"
    store.search.return_value = []
    mgr._store = store
    monkeypatch.setattr(SemanticSearchManager, "_ensure_provider", lambda self: None)

    mgr.search("find the auth check", top_k=5, two_stage=False)

    provider.embed_query.assert_called_once()
    assert provider.embed.call_count == 0  # query must not use the document path
