"""Add encrypted secret column to webhook_configs.

Revision ID: 009
Revises: 008
Create Date: 2026-03-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("webhook_configs", sa.Column("secret_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("webhook_configs", "secret_encrypted")
