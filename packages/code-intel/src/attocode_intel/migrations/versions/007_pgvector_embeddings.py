"""Enable pgvector extension for embedding vector storage.

The vector column on the embeddings table is added at runtime by
ensure_vector_column() — dimension depends on the configured embedding model.

Revision ID: 007
Revises: 006
Create Date: 2026-03-12
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Don't DROP EXTENSION — other things might use it
    pass
