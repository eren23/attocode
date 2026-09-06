"""Add repo_snapshots + repo_snapshot_components tables.

A ``repo_snapshot`` row records a point-in-time manifest hash of a repo's
code-intel state (branch manifest + derived artifacts). Components
(symbols / embeddings / deps / content slice) are stored in a sibling
table so downstream tools can walk the component list, fetch individual
blobs from ``file_contents`` / related stores, and reassemble the
snapshot without unpacking a monolithic tarball.

The shape of this table is forward-compatible with Phase 3b's OCI
adapter: every row's ``manifest_hash`` matches the SHA-256 of a canonical
JSON manifest that maps 1:1 to an OCI image manifest (``config`` +
``layers`` with media types) without schema changes.

Revision ID: 018
Revises: 017
Create Date: 2026-04-10
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repo_snapshots",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repo_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        # Total bytes across every component, for at-a-glance sizing in the
        # list endpoint (no need to scan component rows on every list call).
        sa.Column(
            "total_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "component_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # Commit pinning — stored as a plain string so even repos without a
        # commits table entry (e.g. local_path only) can still be pinned.
        sa.Column("commit_oid", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "extra",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    # Unique per (repo_id, name) so you can't shadow an existing named
    # snapshot — forces the user to delete + recreate.
    op.create_unique_constraint(
        "uq_repo_snapshots_repo_name",
        "repo_snapshots",
        ["repo_id", "name"],
    )
    op.create_index(
        "ix_repo_snapshots_repo_created",
        "repo_snapshots",
        ["repo_id", "created_at"],
    )
    op.create_index(
        "ix_repo_snapshots_org",
        "repo_snapshots",
        ["org_id"],
    )

    op.create_table(
        "repo_snapshot_components",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "snapshot_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repo_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        # Each component is content-addressed by a SHA-256 digest (in the
        # OCI ``sha256:<hex>`` form). For symbol_set_v1 / embedding_blob_v1
        # components this lines up with the content_store action hash.
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "extra",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index(
        "ix_repo_snapshot_components_snapshot",
        "repo_snapshot_components",
        ["snapshot_id"],
    )
    op.create_index(
        "ix_repo_snapshot_components_digest",
        "repo_snapshot_components",
        ["digest"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_repo_snapshot_components_digest",
        table_name="repo_snapshot_components",
    )
    op.drop_index(
        "ix_repo_snapshot_components_snapshot",
        table_name="repo_snapshot_components",
    )
    op.drop_table("repo_snapshot_components")
    op.drop_index("ix_repo_snapshots_org", table_name="repo_snapshots")
    op.drop_index(
        "ix_repo_snapshots_repo_created", table_name="repo_snapshots",
    )
    op.drop_constraint(
        "uq_repo_snapshots_repo_name",
        "repo_snapshots",
        type_="unique",
    )
    op.drop_table("repo_snapshots")
