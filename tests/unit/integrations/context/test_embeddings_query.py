"""Document/query asymmetry: nomic must prefix queries with search_query:.

Symmetric providers (BGE/MiniLM) reuse embed() for queries; nomic overrides
embed_query() to use the query-specific prefix. The query path in
SemanticSearchManager.search must call embed_query (not embed).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from attocode.integrations.context import embeddings as emb


def test_abc_embed_query_defaults_to_embed():
    # BGE (CodeEmbeddingProvider) is symmetric: embed_query delegates to embed.
    p = emb.CodeEmbeddingProvider.__new__(emb.CodeEmbeddingProvider)
    p._model = MagicMock()
    p._model.encode.return_value = [[0.1, 0.2]]
    p._dim = 2
    p.embed_query(["x"])
    called_arg = p._model.encode.call_args[0][0]
    assert called_arg == ["x"]  # symmetric: no prefix


def test_nomic_uses_distinct_doc_and_query_prefixes():
    p = emb.NomicEmbeddingProvider.__new__(emb.NomicEmbeddingProvider)
    p._model = MagicMock()
    p._model.encode.return_value = [[0.0]]
    p._dim = 1

    p.embed(["hello"])
    doc_arg = p._model.encode.call_args[0][0]
    p.embed_query(["hello"])
    qry_arg = p._model.encode.call_args[0][0]

    assert doc_arg == ["search_document: hello"]
    assert qry_arg == ["search_query: hello"]
