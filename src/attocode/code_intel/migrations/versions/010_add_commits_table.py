"""Add commits table for DB-backed commit history.

Revision ID: 010
Revises: 009
Create Date: 2026-03-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "commits",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("oid", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("author_name", sa.Text(), nullable=False),
        sa.Column("author_email", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("parent_oids", sa.dialects.postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("branch_name", sa.Text(), nullable=False, server_default="main"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repo_id", "oid", name="uq_commits_repo_oid"),
    )
    op.create_index("ix_commits_repo_branch_ts", "commits", ["repo_id", "branch_name", sa.text("timestamp DESC")])


def downgrade() -> None:
    op.drop_index("ix_commits_repo_branch_ts", table_name="commits")
    op.drop_table("commits")
