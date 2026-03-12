"""Content-addressed file storage — SHA-256 keyed deduplication."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ContentStore:
    """SHA-256 keyed content storage with deduplication.

    Files are stored once by content hash. Multiple branches can reference
    the same content without duplication.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def hash_content(content: bytes) -> str:
        """Compute SHA-256 hash of content."""
        return hashlib.sha256(content).hexdigest()

    async def store(
        self,
        content: bytes,
        language: str | None = None,
        content_type: str = "source",
    ) -> str:
        """Store content and return its SHA-256 hash. Idempotent (INSERT ON CONFLICT DO NOTHING)."""
        from sqlalchemy.dialects.postgresql import insert

        from attocode.code_intel.db.models import FileContent

        sha = self.hash_content(content)

        # C4 fix: atomic INSERT ON CONFLICT DO NOTHING — eliminates TOCTOU race
        stmt = insert(FileContent).values(
            sha256=sha,
            content=content,
            size_bytes=len(content),
            language=language,
            content_type=content_type,
        ).on_conflict_do_nothing(index_elements=["sha256"])
        await self._session.execute(stmt)
        await self._session.flush()
        return sha

    async def store_batch(
        self,
        items: list[tuple[bytes, str | None]],
    ) -> list[str]:
        """Store multiple items efficiently. Returns list of SHA-256 hashes.

        Deduplicates within batch and uses INSERT ON CONFLICT DO NOTHING.
        """
        from sqlalchemy.dialects.postgresql import insert

        from attocode.code_intel.db.models import FileContent

        # Pre-compute all hashes
        entries = [(self.hash_content(content), content, lang) for content, lang in items]

        # M6 fix: deduplicate within batch by SHA
        seen: dict[str, tuple[str, bytes, str | None]] = {}
        hashes = []
        for sha, content, language in entries:
            hashes.append(sha)
            if sha not in seen:
                seen[sha] = (sha, content, language)

        # Bulk existence check on deduplicated set
        unique_shas = list(seen.keys())
        existing = await self.batch_exists(unique_shas)

        # Only insert new content using ON CONFLICT DO NOTHING
        for sha, content, language in seen.values():
            if sha in existing:
                continue
            stmt = insert(FileContent).values(
                sha256=sha,
                content=content,
                size_bytes=len(content),
                language=language,
            ).on_conflict_do_nothing(index_elements=["sha256"])
            await self._session.execute(stmt)

        await self._session.flush()
        return hashes

    async def get(self, sha: str) -> bytes | None:
        """Retrieve content by SHA-256 hash."""
        from sqlalchemy import select

        from attocode.code_intel.db.models import FileContent

        result = await self._session.execute(
            select(FileContent.content).where(FileContent.sha256 == sha)
        )
        row = result.scalar_one_or_none()
        return row if row is not None else None

    async def exists(self, sha: str) -> bool:
        """Check if content exists by hash."""
        from sqlalchemy import select

        from attocode.code_intel.db.models import FileContent

        result = await self._session.execute(
            select(FileContent.sha256).where(FileContent.sha256 == sha)
        )
        return result.scalar_one_or_none() is not None

    async def batch_exists(self, shas: list[str]) -> set[str]:
        """Check existence of multiple hashes in one query. Returns set of existing SHAs."""
        if not shas:
            return set()

        from sqlalchemy import select

        from attocode.code_intel.db.models import FileContent

        result = await self._session.execute(
            select(FileContent.sha256).where(FileContent.sha256.in_(shas))
        )
        return {row[0] for row in result}

    async def gc_unreferenced(self, min_age_minutes: int = 5) -> int:
        """Delete file_contents not referenced by any branch_files, symbols, dependencies, or embeddings.

        C2 fix: Only deletes content older than min_age_minutes to avoid racing
        with concurrent indexers that are still writing references.

        Returns count of deleted rows.
        """
        from sqlalchemy import text

        result = await self._session.execute(
            text("""
            DELETE FROM file_contents
            WHERE created_at < NOW() - INTERVAL ':age minutes'
              AND sha256 NOT IN (
                SELECT DISTINCT content_sha FROM branch_files WHERE content_sha IS NOT NULL
                UNION
                SELECT DISTINCT content_sha FROM symbols
                UNION
                SELECT DISTINCT source_sha FROM dependencies
                UNION
                SELECT DISTINCT target_sha FROM dependencies
                UNION
                SELECT DISTINCT content_sha FROM embeddings
            )
            """).bindparams(age=min_age_minutes)
        )
        count = result.rowcount
        if count:
            logger.info("GC: removed %d unreferenced file contents (older than %dm)", count, min_age_minutes)
        return count
