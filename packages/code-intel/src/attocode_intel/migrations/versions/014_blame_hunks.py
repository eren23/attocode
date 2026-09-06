"""Add blame_hunks table for DB-backed blame data.

Revision ID: 014
Revises: 013
Create Date: 2026-03-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blame_hunks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("branch_name", sa.Text(), nullable=False, server_default="main"),
        sa.Column("commit_oid", sa.Text(), nullable=False),
        sa.Column("author_name", sa.Text(), nullable=False),
        sa.Column("author_email", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_blame_hunks_repo_path_branch", "blame_hunks", ["repo_id", "path", "branch_name"])


def downgrade() -> None:
    op.drop_index("ix_blame_hunks_repo_path_branch", table_name="blame_hunks")
    op.drop_table("blame_hunks")
