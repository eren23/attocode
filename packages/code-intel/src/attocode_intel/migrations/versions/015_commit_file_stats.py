"""Add commit_file_stats table for per-file commit statistics.

Revision ID: 015
Revises: 014
Create Date: 2026-03-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "commit_file_stats",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("commit_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("commits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repo_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("lines_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lines_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbols_changed", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_commit_file_stats_repo_path", "commit_file_stats", ["repo_id", "path"])
    op.create_index("ix_commit_file_stats_commit_id", "commit_file_stats", ["commit_id"])


def downgrade() -> None:
    op.drop_index("ix_commit_file_stats_commit_id", table_name="commit_file_stats")
    op.drop_index("ix_commit_file_stats_repo_path", table_name="commit_file_stats")
    op.drop_table("commit_file_stats")
