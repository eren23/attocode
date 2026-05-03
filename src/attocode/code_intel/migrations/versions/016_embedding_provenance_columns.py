"""Add provenance columns to embeddings (non-destructive).

This migration addresses the "embedding model/dimension silently wipes all
vectors" footgun by introducing explicit provenance columns — *without*
touching the primary ``vector`` column. Re-dimensioning is handled via a
separate rotation flow in a later phase; this migration is purely additive.

Changes:
  - Add ``embeddings.embedding_model_version`` (text, default '').
  - Add ``embeddings.embedding_dim`` (int, nullable — backfilled from
    ``vector_dims(vector)`` for rows where pgvector is available).
  - Add ``embeddings.embedding_provenance`` (JSONB, default '{}').
  - Replace the ``(content_sha, embedding_model, chunk_type)`` unique with
    ``(content_sha, embedding_model, embedding_model_version, chunk_type)``
    so two versions of the same model can coexist during rotation.

Revision ID: 016
Revises: 015
Create Date: 2026-04-10
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add new columns with safe defaults so existing rows don't break.
    op.add_column(
        "embeddings",
        sa.Column(
            "embedding_model_version",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "embeddings",
        sa.Column(
            "embedding_dim",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "embeddings",
        sa.Column(
            "embedding_provenance",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )

    # 2. Backfill embedding_dim from pgvector's vector_dims() where possible.
    #    Rows without a vector (vector IS NULL) stay NULL.
    #
    #    Done in a DO block so a connection lacking the `vector` extension
    #    or the `vector` column still lets the migration run on brand-new
    #    databases where ensure_vector_column() hasn't fired yet.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'embeddings' AND column_name = 'vector'
            ) THEN
                EXECUTE 'UPDATE embeddings SET embedding_dim = vector_dims(vector) '
                        'WHERE vector IS NOT NULL';
            END IF;
        END $$;
        """
    )

    # 3. Replace the unique constraint to include embedding_model_version.
    #    During rotation two versions of the same model coexist in place.
    op.drop_constraint(
        "uq_embedding_content_model_chunk",
        "embeddings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_embedding_content_model_version_chunk",
        "embeddings",
        ["content_sha", "embedding_model", "embedding_model_version", "chunk_type"],
    )

    # 4. Helpful secondary index for provenance lookups.
    op.create_index(
        "ix_embeddings_model_version",
        "embeddings",
        ["embedding_model", "embedding_model_version"],
    )


def downgrade() -> None:
    """Revert the non-destructive dual-column rewrite.

    A naive downgrade (drop the wide unique key, recreate the narrow
    one) fails outright when a dual-version rotation has left multiple
    ``embedding_model_version`` values for the same
    ``(content_sha, embedding_model, chunk_type)`` tuple — recreating
    the narrow unique constraint raises at DDL time.

    Safe default: REFUSE the downgrade unless the operator sets
    ``ATTOCODE_ALLOW_DESTRUCTIVE_016_DOWNGRADE``. When set, delete every
    row whose ``embedding_model_version`` is non-empty first (logging
    the count) and then rewrite. Pre-rotation databases (every row has
    ``embedding_model_version = ''``) downgrade cleanly without the
    flag.
    """
    import logging
    import os

    logger = logging.getLogger("alembic.016")

    bind = op.get_bind()
    conflicts_row = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM embeddings "
            "WHERE embedding_model_version IS NOT NULL "
            "  AND embedding_model_version != ''"
        )
    ).fetchone()
    conflict_count = int(conflicts_row[0] or 0) if conflicts_row else 0

    if conflict_count > 0:
        allow = os.environ.get(
            "ATTOCODE_ALLOW_DESTRUCTIVE_016_DOWNGRADE", ""
        ).lower() in {"1", "true", "yes"}
        if not allow:
            raise RuntimeError(
                f"Refusing to downgrade migration 016: {conflict_count} "
                f"embedding row(s) carry a non-empty "
                f"embedding_model_version, which would violate the "
                f"recreated (content_sha, embedding_model, chunk_type) "
                f"unique constraint. Set "
                f"ATTOCODE_ALLOW_DESTRUCTIVE_016_DOWNGRADE=1 to confirm "
                f"the destructive downgrade (this will DELETE those rows)."
            )
        logger.warning(
            "016 downgrade: destructive flag set, deleting %d "
            "embedding row(s) with non-empty embedding_model_version",
            conflict_count,
        )
        bind.execute(
            sa.text(
                "DELETE FROM embeddings "
                "WHERE embedding_model_version IS NOT NULL "
                "  AND embedding_model_version != ''"
            )
        )

    op.drop_index("ix_embeddings_model_version", table_name="embeddings")
    op.drop_constraint(
        "uq_embedding_content_model_version_chunk",
        "embeddings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_embedding_content_model_chunk",
        "embeddings",
        ["content_sha", "embedding_model", "chunk_type"],
    )
    op.drop_column("embeddings", "embedding_provenance")
    op.drop_column("embeddings", "embedding_dim")
    op.drop_column("embeddings", "embedding_model_version")
