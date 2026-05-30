"""Auto-detect should prefer the code-trained nomic embedder by default."""
from __future__ import annotations


def test_autodetect_prefers_nomic(monkeypatch):
    import attocode.integrations.context.embeddings as e

    e._provider_cache.clear()
    monkeypatch.delenv("ATTOCODE_EMBEDDING_MODEL", raising=False)

    class _FakeNomic:
        name = "local:nomic-embed-text-v1.5"

        def embed(self, t):
            return [[0.0]]

        def dimension(self):
            return 768

    monkeypatch.setattr(e, "NomicEmbeddingProvider", lambda: _FakeNomic())

    p = e.create_embedding_provider("")
    assert p.name == "local:nomic-embed-text-v1.5"
