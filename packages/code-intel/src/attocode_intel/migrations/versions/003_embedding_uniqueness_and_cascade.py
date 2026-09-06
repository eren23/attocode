"""Add unique constraint on embeddings and CASCADE on FK.

C6: Ensure one embedding per (content_sha, embedding_model, chunk_type).
N5: Add ON DELETE CASCADE to embeddings.content_sha FK.

Revision ID: 003
Revises: 002
Create Date: 2026-03-11
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # C6: unique constraint on (content_sha, embedding_model, chunk_type)
    op.create_unique_constraint(
        "uq_embedding_content_model_chunk",
        "embeddings",
        ["content_sha", "embedding_model", "chunk_type"],
    )

    # N5: replace FK with CASCADE version
    op.drop_constraint("embeddings_content_sha_fkey", "embeddings", type_="foreignkey")
    op.create_foreign_key(
        "embeddings_content_sha_fkey",
        "embeddings",
        "file_contents",
        ["content_sha"],
        ["sha256"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("embeddings_content_sha_fkey", "embeddings", type_="foreignkey")
    op.create_foreign_key(
        "embeddings_content_sha_fkey",
        "embeddings",
        "file_contents",
        ["content_sha"],
        ["sha256"],
    )
    op.drop_constraint("uq_embedding_content_model_chunk", "embeddings", type_="unique")
