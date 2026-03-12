"""Embedding storage — content-SHA-keyed with model tracking, pgvector-ready."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class EmbeddingStore:
    """Content-SHA-keyed embedding storage for semantic search.

    Embeddings are keyed by (content_sha, embedding_model) for deduplication.
    If content_sha+model already exists, skip — same content always produces
    the same embeddings for a given model.

    Branch-aware queries resolve through BranchOverlay.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_embeddings(
        self,
        content_sha: str,
        embeddings: list[dict],
    ) -> int:
        """Store embeddings for a content hash.

        Each embedding dict: {chunk_text, chunk_type, embedding_model}
        Idempotent — if content_sha+model already has embeddings, replaces them.

        Returns count of embeddings stored.
        """
        from sqlalchemy import delete

        from attocode.code_intel.db.models import Embedding

        if not embeddings:
            return 0

        # Determine models being upserted
        models_in_batch = {e.get("embedding_model", "default") for e in embeddings}
        for model in models_in_batch:
            await self._session.execute(
                delete(Embedding).where(
                    Embedding.content_sha == content_sha,
                    Embedding.embedding_model == model,
                )
            )

        # Insert new
        for emb_data in embeddings:
            emb = Embedding(
                content_sha=content_sha,
                embedding_model=emb_data.get("embedding_model", "default"),
                chunk_text=emb_data.get("chunk_text", ""),
                chunk_type=emb_data.get("chunk_type", "file"),
            )
            self._session.add(emb)

        await self._session.flush()
        return len(embeddings)

    async def batch_has_embeddings(self, content_shas: set[str], model: str = "default") -> set[str]:
        """Check which content_shas have embeddings. Returns the subset that do."""
        if not content_shas:
            return set()

        from sqlalchemy import select

        from attocode.code_intel.db.models import Embedding

        result = await self._session.execute(
            select(Embedding.content_sha).where(
                Embedding.content_sha.in_(content_shas),
                Embedding.embedding_model == model,
            ).distinct()
        )
        return {row[0] for row in result}

    async def has_embeddings(self, content_sha: str, model: str = "default") -> bool:
        """Check if embeddings exist for a content_sha+model. Used for dedup gating."""
        from sqlalchemy import select

        from attocode.code_intel.db.models import Embedding

        result = await self._session.execute(
            select(Embedding.id).where(
                Embedding.content_sha == content_sha,
                Embedding.embedding_model == model,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def similarity_search(
        self,
        branch_id: uuid.UUID,
        query_text: str,
        top_k: int = 10,
        model: str = "default",
    ) -> list[dict]:
        """Find most similar content within a branch context.

        When pgvector is available, uses cosine similarity on vector column.
        Currently returns text-based results scoped to branch manifest.
        """
        from sqlalchemy import select

        from attocode.code_intel.db.models import Embedding
        from attocode.code_intel.storage.branch_overlay import BranchOverlay

        overlay = BranchOverlay(self._session)
        manifest = await overlay.resolve_manifest(branch_id)
        content_shas = set(manifest.values())

        if not content_shas:
            return []

        sha_to_path = {sha: path for path, sha in manifest.items()}

        # When pgvector is available, use:
        # SELECT *, vector <=> :query_vector AS distance FROM embeddings
        # WHERE content_sha = ANY(:shas) AND embedding_model = :model
        # ORDER BY distance LIMIT :top_k
        result = await self._session.execute(
            select(Embedding)
            .where(
                Embedding.content_sha.in_(content_shas),
                Embedding.embedding_model == model,
            )
            .limit(top_k)
        )

        results = []
        for emb in result.scalars():
            results.append({
                "file": sha_to_path.get(emb.content_sha, "unknown"),
                "content_sha": emb.content_sha,
                "chunk_text": emb.chunk_text,
                "chunk_type": emb.chunk_type,
                "model": emb.embedding_model,
            })
        return results
