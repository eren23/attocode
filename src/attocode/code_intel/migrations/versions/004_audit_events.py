"""Add audit_events table for activity feed / audit log.

Revision ID: 004
Revises: 003
Create Date: 2026-03-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repo_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("detail", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_events_org_created", "audit_events", ["org_id", sa.text("created_at DESC")])
    op.create_index("ix_audit_events_repo_created", "audit_events", ["repo_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_audit_events_repo_created", "audit_events")
    op.drop_index("ix_audit_events_org_created", "audit_events")
    op.drop_table("audit_events")
