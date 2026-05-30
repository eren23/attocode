"""reindex(embeddings=True) must synchronously build the vector index.

The search-quality eval relies on this: without a synchronous vector build,
embeddings are built lazily during scoring, so index changes (chunking /
embedder) can't be measured deterministically.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from attocode.code_intel.service import CodeIntelService


def _svc(tmp_path) -> CodeIntelService:
    svc = CodeIntelService(str(tmp_path))
    # Stub the AST service so reindex() doesn't do real parsing.
    ast = MagicMock()
    ast._store.stats.return_value = {"files": 3, "symbols": 9}
    svc._ast_service = ast
    return svc


def test_reindex_without_embeddings_skips_vector_build(tmp_path):
    svc = _svc(tmp_path)
    mgr = MagicMock()
    svc._semantic_search = mgr

    stats = svc.reindex(force=True)

    mgr.index.assert_not_called()
    assert "embedded_chunks" not in stats
    assert stats["mode"] == "full"


def test_reindex_with_embeddings_builds_vectors(tmp_path):
    svc = _svc(tmp_path)
    mgr = MagicMock()
    mgr.index.return_value = 42
    svc._semantic_search = mgr

    stats = svc.reindex(force=True, embeddings=True)

    mgr.index.assert_called_once()
    assert stats["embedded_chunks"] == 42
    assert stats["mode"] == "full"
