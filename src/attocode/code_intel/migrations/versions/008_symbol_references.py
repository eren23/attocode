"""Add symbol_references table for call-site / import reference tracking.

Revision ID: 008
Revises: 007
Create Date: 2026-03-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "symbol_references",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("content_sha", sa.Text, sa.ForeignKey("file_contents.sha256", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol_name", sa.String(500), nullable=False),
        sa.Column("ref_kind", sa.String(20), nullable=False),
        sa.Column("line", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_symref_sha", "symbol_references", ["content_sha"])
    op.create_index("ix_symref_name", "symbol_references", ["symbol_name"])


def downgrade() -> None:
    op.drop_index("ix_symref_name", "symbol_references")
    op.drop_index("ix_symref_sha", "symbol_references")
    op.drop_table("symbol_references")
