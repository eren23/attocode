"""Add branch version counter, file_contents.content_type, and embeddings table.

Revision ID: 002
Revises: 001
Create Date: 2026-03-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Branch version counter for consistency tracking
    op.add_column(
        "branches",
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
    )

    # Content type for future fractal summaries (source|summary_l1|summary_l2)
    op.add_column(
        "file_contents",
        sa.Column("content_type", sa.Text, nullable=False, server_default="source"),
    )

    # Embeddings table — content-SHA-keyed with model tracking
    op.create_table(
        "embeddings",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("content_sha", sa.Text, sa.ForeignKey("file_contents.sha256"), nullable=False),
        sa.Column("embedding_model", sa.Text, nullable=False, server_default="default"),
        sa.Column("chunk_text", sa.Text, nullable=False, server_default=""),
        sa.Column("chunk_type", sa.Text, nullable=False, server_default="file"),
        # vector column will be added when pgvector extension is enabled:
        # sa.Column("vector", Vector(384))  # or Vector(1536) for OpenAI
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_embeddings_content_sha", "embeddings", ["content_sha"])
    op.create_index("idx_embeddings_model", "embeddings", ["embedding_model"])
    op.create_index(
        "idx_embeddings_content_model",
        "embeddings",
        ["content_sha", "embedding_model"],
    )


def downgrade() -> None:
    op.drop_index("idx_embeddings_content_model")
    op.drop_index("idx_embeddings_model")
    op.drop_index("idx_embeddings_content_sha")
    op.drop_table("embeddings")
    op.drop_column("file_contents", "content_type")
    op.drop_column("branches", "version")
