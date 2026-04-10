"""Embedding storage — content-SHA-keyed with model tracking, pgvector-ready."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class EmbeddingDimensionMismatchError(RuntimeError):
    """Raised when the running embedding provider's dimension does not match
    the vectors already persisted in the ``embeddings`` table.

    Migration 016 replaced the old behavior — which silently ran
    ``UPDATE embeddings SET vector = NULL`` and dropped every stored
    embedding — with a loud refusal. Callers must now explicitly rotate
    to the new dimension via the (phase-4) embeddings rotation endpoint,
    or clear the table manually. Silent data loss is never OK.
    """

    def __init__(self, *, stored: int, expected: int) -> None:
        self.stored = stored
        self.expected = expected
        super().__init__(
            f"embedding dimension mismatch: stored={stored} expected={expected}. "
            f"Refusing to wipe existing vectors. "
            f"Resolve by starting an embedding rotation (POST /embeddings/rotate), "
            f"or explicitly re-dimensioning the column after backing up."
        )


async def ensure_vector_columns(
    session: AsyncSession,
    primary_dim: int,
    shadow_dim: int | None = None,
) -> None:
    """Ensure ``embeddings.vector`` exists at ``primary_dim`` without destroying
    data, and optionally ensure a ``vector_b`` shadow column at ``shadow_dim``.

    Behavior:
      - If ``vector`` does not exist: CREATE at ``primary_dim``, build HNSW index.
      - If ``vector`` exists at ``primary_dim``: no-op.
      - If ``vector`` exists at a DIFFERENT dim: **raise** ``EmbeddingDimensionMismatchError``.
        Old code silently NULLed every row here; that was a footgun.
      - If ``shadow_dim`` is given and differs from ``primary_dim``: ensure a
        ``vector_b`` column at ``shadow_dim`` (used during rotation dual-write).
        Never touches the primary column.

    ``shadow_dim`` is accepted now so the rotation machinery in a later phase
    doesn't have to re-touch this function.
    """
    from sqlalchemy import text

    result = await session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'embeddings'::regclass AND attname = 'vector'"
        )
    )
    row = result.first()

    if row is None:
        # Column doesn't exist — safe to add.
        await session.execute(
            text(f"ALTER TABLE embeddings ADD COLUMN vector vector({primary_dim})")
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_embeddings_vector_hnsw "
                "ON embeddings USING hnsw (vector vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64)"
            )
        )
        logger.info(
            "Created vector column with dimension %d and HNSW index", primary_dim
        )
    else:
        stored_dim = row[0] - 4  # pgvector stores dim+4 in atttypmod
        if stored_dim != primary_dim:
            logger.error(
                "Embedding dimension mismatch: stored=%d, expected=%d. "
                "Refusing destructive UPDATE. Use embedding rotation flow.",
                stored_dim, primary_dim,
            )
            raise EmbeddingDimensionMismatchError(
                stored=stored_dim, expected=primary_dim,
            )
        logger.debug("Vector column already has correct dimension %d", primary_dim)

    # Shadow column handling — used during a live rotation where new writes
    # target vector_b with the new dimension while reads still hit vector.
    if shadow_dim is not None and shadow_dim != primary_dim:
        result_b = await session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'embeddings'::regclass AND attname = 'vector_b'"
            )
        )
        row_b = result_b.first()
        if row_b is None:
            await session.execute(
                text(f"ALTER TABLE embeddings ADD COLUMN vector_b vector({shadow_dim})")
            )
            await session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_embeddings_vector_b_hnsw "
                    "ON embeddings USING hnsw (vector_b vector_cosine_ops) "
                    "WITH (m = 16, ef_construction = 64)"
                )
            )
            logger.info("Created shadow vector_b column at dimension %d", shadow_dim)
        else:
            stored_shadow = row_b[0] - 4
            if stored_shadow != shadow_dim:
                raise EmbeddingDimensionMismatchError(
                    stored=stored_shadow, expected=shadow_dim,
                )

    await session.commit()


# Backwards-compatibility alias. Old callers that still invoke
# ``ensure_vector_column(session, dim)`` get the new non-destructive
# behavior automatically. They will now *raise* on dimension mismatch where
# they previously silently wiped vectors — which is exactly the point of
# this change. If you hit this error, use the rotation endpoint.
async def ensure_vector_column(session: AsyncSession, dimension: int) -> None:
    """Deprecated alias for :func:`ensure_vector_columns` (single-dim form)."""
    await ensure_vector_columns(session, primary_dim=dimension)


class EmbeddingStore:
    """Content-SHA-keyed embedding storage for semantic search.

    Embeddings are keyed by (content_sha, embedding_model, embedding_model_version)
    for deduplication. If content_sha+model+version already exists, skip — same
    content always produces the same embeddings for a given model version.

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

        Each embedding dict: {chunk_text, chunk_type, embedding_model,
        embedding_model_version?, embedding_dim?, embedding_provenance?, vector?}

        Idempotent within a (content_sha, model, model_version) triple —
        replaces all rows for that triple. Other (model, version) pairs
        coexist peacefully (needed for the dual-write rotation flow).

        Returns count of embeddings stored.
        """
        from sqlalchemy import delete

        from attocode.code_intel.db.models import Embedding

        if not embeddings:
            return 0

        # Determine (model, version) pairs being upserted. Rows at other
        # versions stay put — this is the key invariant enabling rotation.
        pairs_in_batch: set[tuple[str, str]] = {
            (
                e.get("embedding_model", "default"),
                e.get("embedding_model_version", ""),
            )
            for e in embeddings
        }
        for model, version in pairs_in_batch:
            await self._session.execute(
                delete(Embedding).where(
                    Embedding.content_sha == content_sha,
                    Embedding.embedding_model == model,
                    Embedding.embedding_model_version == version,
                )
            )

        # Insert new
        for emb_data in embeddings:
            kwargs = {
                "content_sha": content_sha,
                "embedding_model": emb_data.get("embedding_model", "default"),
                "embedding_model_version": emb_data.get("embedding_model_version", ""),
                "embedding_dim": emb_data.get("embedding_dim"),
                "embedding_provenance": emb_data.get("embedding_provenance", {}),
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

        stmt = select(Embedding.content_sha).where(
            Embedding.content_sha.in_(content_shas),
            Embedding.embedding_model == model,
        )
        if hasattr(Embedding, 'vector'):
            stmt = stmt.where(Embedding.vector.isnot(None))
        result = await self._session.execute(stmt.distinct())
        return {row[0] for row in result}

    async def batch_embedding_stats(
        self, content_shas: set[str], model: str = "default",
    ) -> dict[str, dict]:
        """Get chunk count + last embedded time for content SHAs with embeddings."""
        if not content_shas:
            return {}

        from sqlalchemy import func, select

        from attocode.code_intel.db.models import Embedding

        stmt = select(
            Embedding.content_sha,
            func.count().label("chunk_count"),
            func.max(Embedding.created_at).label("last_embedded"),
        ).where(
            Embedding.content_sha.in_(content_shas),
            Embedding.embedding_model == model,
        )
        if hasattr(Embedding, 'vector'):
            stmt = stmt.where(Embedding.vector.isnot(None))
        stmt = stmt.group_by(Embedding.content_sha)
        result = await self._session.execute(stmt)
        return {
            row.content_sha: {
                "chunk_count": row.chunk_count,
                "last_embedded": row.last_embedded,
            }
            for row in result
        }

    async def has_embeddings(self, content_sha: str, model: str = "default") -> bool:
        """Check if embeddings exist for a content_sha+model. Used for dedup gating."""
        from sqlalchemy import select

        from attocode.code_intel.db.models import Embedding

        stmt = select(Embedding.id).where(
            Embedding.content_sha == content_sha,
            Embedding.embedding_model == model,
        )
        if hasattr(Embedding, 'vector'):
            stmt = stmt.where(Embedding.vector.isnot(None))
        result = await self._session.execute(stmt.limit(1))
        return result.scalar_one_or_none() is not None

    async def find_similar_by_sha(
        self,
        branch_id: uuid.UUID,
        content_sha: str,
        top_k: int = 10,
        model: str = "default",
    ) -> list[dict]:
        """Find files similar to the given content_sha within a branch.

        Retrieves the embedding vector(s) for the source content_sha, averages
        them if multiple chunks exist, then runs a cosine similarity search
        excluding the source itself.
        """
        from sqlalchemy import text

        from attocode.code_intel.storage.branch_overlay import BranchOverlay

        # 1. Get vectors for the source content_sha
        result = await self._session.execute(
            text("""
                SELECT vector::text FROM embeddings
                WHERE content_sha = :sha AND embedding_model = :model AND vector IS NOT NULL
            """),
            {"sha": content_sha, "model": model},
        )
        rows = result.fetchall()
        if not rows:
            return []

        # 2. Parse and average vectors
        def parse_vector(vec_str: str) -> list[float]:
            return [float(x) for x in vec_str.strip("[]").split(",")]

        vectors = [parse_vector(row[0]) for row in rows]
        dim = len(vectors[0])
        if len(vectors) == 1:
            avg_vector = vectors[0]
        else:
            avg_vector = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]

        # 3. Resolve branch manifest
        overlay = BranchOverlay(self._session)
        manifest = await overlay.resolve_manifest(branch_id)
        content_shas = set(manifest.values())
        content_shas.discard(content_sha)  # exclude source

        if not content_shas:
            return []

        sha_to_path = {sha: path for path, sha in manifest.items()}

        # 4. Run cosine similarity search
        result = await self._session.execute(
            text("""
                SELECT content_sha, chunk_text, chunk_type, embedding_model,
                       1 - (vector <=> CAST(:qv AS vector)) AS score
                FROM embeddings
                WHERE content_sha = ANY(:shas)
                  AND embedding_model = :model
                  AND vector IS NOT NULL
                ORDER BY vector <=> CAST(:qv AS vector)
                LIMIT :top_k
            """),
            {
                "qv": "[" + ",".join(str(v) for v in avg_vector) + "]",
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
                "score": float(row.score),
            })
        return results

    async def similarity_search(
        self,
        branch_id: uuid.UUID,
        query_vector: list[float],
        top_k: int = 10,
        model: str = "default",
        file_filter: str = "",
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

        if file_filter:
            import fnmatch
            manifest = {p: s for p, s in manifest.items() if fnmatch.fnmatch(p, file_filter)}

        content_shas = set(manifest.values())

        if not content_shas:
            return []

        sha_to_path = {sha: path for path, sha in manifest.items()}

        # pgvector cosine distance query — score = 1 - distance (higher = more similar)
        result = await self._session.execute(
            text("""
                SELECT content_sha, chunk_text, chunk_type, embedding_model,
                       1 - (vector <=> CAST(:qv AS vector)) AS score
                FROM embeddings
                WHERE content_sha = ANY(:shas)
                  AND embedding_model = :model
                  AND vector IS NOT NULL
                ORDER BY vector <=> CAST(:qv AS vector)
                LIMIT :top_k
            """),
            {
                "qv": "[" + ",".join(str(v) for v in query_vector) + "]",
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

    async def multi_branch_similarity_search(
        self,
        session: AsyncSession,
        branch_manifests: dict[str, dict[str, str]],
        query_vector: list[float],
        top_k: int = 20,
        model: str = "",
        file_filter: str = "",
    ) -> list[dict]:
        """Find most similar content across multiple repo branch manifests.

        Args:
            session: Async DB session (uses self._session if same, but kept
                     for API symmetry with callers that pass it explicitly).
            branch_manifests: Mapping of repo_id (str) → manifest (path → content_sha).
            query_vector: Embedded query vector.
            top_k: Number of results to return globally.
            model: Embedding model name to filter by.
            file_filter: Optional glob pattern to filter file paths.

        Returns:
            List of dicts with repo_id, file, content_sha, chunk_text,
            chunk_type, model, score — sorted by score descending.
        """
        import fnmatch

        from sqlalchemy import text

        # 1. Union all content_shas across repos, building reverse lookup
        all_content_shas: set[str] = set()
        # sha → (repo_id, path) for mapping results back
        sha_to_context: dict[str, tuple[str, str]] = {}

        for repo_id, manifest in branch_manifests.items():
            for path, sha in manifest.items():
                if file_filter and not fnmatch.fnmatch(path, file_filter):
                    continue
                all_content_shas.add(sha)
                # First repo wins for a given sha (content-addressed dedup)
                if sha not in sha_to_context:
                    sha_to_context[sha] = (repo_id, path)

        if not all_content_shas:
            return []

        # 2. Single pgvector query across all repos
        result = await self._session.execute(
            text("""
                SELECT content_sha, chunk_text, chunk_type, embedding_model,
                       1 - (vector <=> CAST(:qv AS vector)) AS score
                FROM embeddings
                WHERE content_sha = ANY(:shas)
                  AND embedding_model = :model
                  AND vector IS NOT NULL
                ORDER BY vector <=> CAST(:qv AS vector)
                LIMIT :top_k
            """),
            {
                "qv": "[" + ",".join(str(v) for v in query_vector) + "]",
                "shas": list(all_content_shas),
                "model": model,
                "top_k": top_k,
            },
        )

        # 3. Map results back to repo context
        results = []
        for row in result:
            ctx = sha_to_context.get(row.content_sha)
            repo_id = ctx[0] if ctx else "unknown"
            file_path = ctx[1] if ctx else "unknown"
            results.append({
                "repo_id": repo_id,
                "file": file_path,
                "content_sha": row.content_sha,
                "chunk_text": row.chunk_text,
                "chunk_type": row.chunk_type,
                "model": row.embedding_model,
                "score": float(row.score),
            })
        return results

    async def gc_orphaned(self, min_age_minutes: int = 60) -> int:
        """Delete embeddings whose content_sha is not in any branch manifest.

        Only deletes embeddings older than *min_age_minutes* to avoid racing
        with concurrent indexers that are still writing references.

        Returns count of deleted rows.
        """
        from sqlalchemy import text

        result = await self._session.execute(
            text("""
            DELETE FROM embeddings
            WHERE created_at < NOW() - make_interval(mins => :age)
              AND content_sha NOT IN (
                SELECT DISTINCT content_sha FROM branch_files WHERE content_sha IS NOT NULL
            )
            """).bindparams(age=min_age_minutes)
        )
        count = result.rowcount
        if count:
            logger.info("GC: removed %d orphaned embeddings (older than %dm)", count, min_age_minutes)
        return count
