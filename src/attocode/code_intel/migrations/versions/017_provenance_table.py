"""Add provenance table — one row per derived code-intel artifact.

A ``Provenance`` row records how a symbol set / embedding / dep graph /
repo-map slice was produced: which indexer, which version, which blob was
the input, when, and by whom. Joined into derived-artifact queries by
``action_hash``.

Per-row storage here rather than a JSONB column on every derived table
because:
  - Multiple artifact types want the same shape (no duplication).
  - Queries like "find everything produced by indexer X version Y" are
    common for audit / GC and would be O(n_tables) with per-table JSONB.
  - Provenance should outlive the derived row it describes (for audit).

Revision ID: 017
Revises: 016
Create Date: 2026-04-10
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provenance",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("action_hash", sa.Text(), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("input_blob_oid", sa.Text(), nullable=False),
        sa.Column("input_tree_oid", sa.Text(), nullable=True),
        sa.Column("indexer_name", sa.Text(), nullable=False),
        sa.Column("indexer_version", sa.Text(), nullable=False),
        sa.Column("config_digest", sa.Text(), nullable=False),
        sa.Column(
            "produced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "producer_service",
            sa.Text(),
            nullable=False,
            server_default="attocode-server",
        ),
        sa.Column(
            "producer_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "producer_job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("indexing_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("producer_host", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "extra",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    # action_hash is not quite unique: if the same artifact is re-produced
    # (idempotent indexer rerun with identical inputs) we still want a new
    # provenance row for audit purposes. So no UNIQUE, but an index for fast
    # dedup joins.
    op.create_index("ix_provenance_action_hash", "provenance", ["action_hash"])
    op.create_index("ix_provenance_input_blob", "provenance", ["input_blob_oid"])
    op.create_index("ix_provenance_job", "provenance", ["producer_job_id"])
    op.create_index(
        "ix_provenance_indexer_version",
        "provenance",
        ["indexer_name", "indexer_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_provenance_indexer_version", table_name="provenance")
    op.drop_index("ix_provenance_job", table_name="provenance")
    op.drop_index("ix_provenance_input_blob", table_name="provenance")
    op.drop_index("ix_provenance_action_hash", table_name="provenance")
    op.drop_table("provenance")
