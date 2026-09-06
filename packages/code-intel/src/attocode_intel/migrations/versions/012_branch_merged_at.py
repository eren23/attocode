"""Add merged_at column to branches table.

Revision ID: 012
Revises: 011
Create Date: 2026-03-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "merged_at")
