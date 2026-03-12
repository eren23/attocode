"""Embedding storage — content-SHA-keyed with model tracking, pgvector-ready."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def ensure_vector_column(session: AsyncSession, dimension: int) -> None:
    """Ensure the embeddings table has a vector column of the right dimension.

    Called once at startup by generate_embeddings job. Handles:
    - Column doesn't exist yet -> CREATE
    - Column exists with wrong dimension -> DROP index, ALTER, recreate index
    - Column exists with right dimension -> no-op
    """
    from sqlalchemy import text

    result = await session.execute(text(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'embeddings'::regclass AND attname = 'vector'"
    ))
    row = result.first()

    if row is None:
        # Column doesn't exist — add it
        await session.execute(text(
            f"ALTER TABLE embeddings ADD COLUMN vector vector({dimension})"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_embeddings_vector_hnsw "
            "ON embeddings USING hnsw (vector vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        ))
        logger.info("Created vector column with dimension %d and HNSW index", dimension)
    elif row[0] != dimension + 4:  # pgvector stores dim+4 in atttypmod
        # Dimension mismatch — re-dimension
        await session.execute(text("DROP INDEX IF EXISTS idx_embeddings_vector_hnsw"))
        await session.execute(text("UPDATE embeddings SET vector = NULL"))
        await session.execute(text(
            f"ALTER TABLE embeddings ALTER COLUMN vector TYPE vector({dimension})"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_embeddings_vector_hnsw "
            "ON embeddings USING hnsw (vector vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        ))
        logger.info("Re-dimensioned vector column to %d (old vectors cleared)", dimension)
    else:
        logger.debug("Vector column already has correct dimension %d", dimension)

    await session.commit()


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

        Each embedding dict: {chunk_text, chunk_type, embedding_model, vector?}
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
            kwargs = {
                "content_sha": content_sha,
                "embedding_model": emb_data.get("embedding_model", "default"),
                "chunk_text": emb_data.get("chunk_text", ""),
                "chunk_type": emb_data.get("chunk_type", "file"),
            }
            # Include vector if provided and pgvector is available
            if "vector" in emb_data and emb_data["vector"] is not None:
                kwargs["vector"] = emb_data["vector"]
            emb = Embedding(**kwargs)
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
        query_vector: list[float],
        top_k: int = 10,
        model: str = "default",
    ) -> list[dict]:
        """Find most similar content within a branch context using pgvector cosine distance.

        Args:
            branch_id: Branch to scope results to.
            query_vector: Embedded query vector.
            top_k: Number of results to return.
            model: Embedding model name to filter by.

        Returns:
            List of dicts with file, content_sha, chunk_text, chunk_type, model, score.
        """
        from sqlalchemy import text

        from attocode.code_intel.storage.branch_overlay import BranchOverlay

        overlay = BranchOverlay(self._session)
        manifest = await overlay.resolve_manifest(branch_id)
        content_shas = set(manifest.values())

        if not content_shas:
            return []

        sha_to_path = {sha: path for path, sha in manifest.items()}

        # pgvector cosine distance query — score = 1 - distance (higher = more similar)
        result = await self._session.execute(
            text("""
                SELECT content_sha, chunk_text, chunk_type, embedding_model,
                       1 - (vector <=> :qv::vector) AS score
                FROM embeddings
                WHERE content_sha = ANY(:shas)
                  AND embedding_model = :model
                  AND vector IS NOT NULL
                ORDER BY vector <=> :qv::vector
                LIMIT :top_k
            """),
            {
                "qv": str(query_vector),
                "shas": list(content_shas),
                "model": model,
                "top_k": top_k,
            },
        )

        results = []
        for row in result:
            results.append({
                "file": sha_to_path.get(row.content_sha, "unknown"),
                "content_sha": row.content_sha,
                "chunk_text": row.chunk_text,
                "chunk_type": row.chunk_type,
                "model": row.embedding_model,
                "score": float(row.score),
            })
        return results
