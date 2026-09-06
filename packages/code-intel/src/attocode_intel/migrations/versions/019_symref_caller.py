"""Add caller_qualified_name to symbol_references for call-graph attribution.

Pairs with the function-level call graph in CrossRefIndex (Phase 1, A1).
Without this column, the full-indexer pipeline persists references but
loses the enclosing function/method, which makes call_graph queries over
HTTP-indexed repos return empty edges.

Revision ID: 019
Revises: 018
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "symbol_references",
        sa.Column(
            "caller_qualified_name",
            sa.String(500),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index(
        "ix_symref_caller", "symbol_references", ["caller_qualified_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_symref_caller", "symbol_references")
    op.drop_column("symbol_references", "caller_qualified_name")
