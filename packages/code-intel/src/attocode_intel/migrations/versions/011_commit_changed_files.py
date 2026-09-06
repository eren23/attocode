"""Add changed_files JSONB column to commits table.

Revision ID: 011
Revises: 010
Create Date: 2026-03-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("commits", sa.Column("changed_files", sa.dialects.postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("commits", "changed_files")
