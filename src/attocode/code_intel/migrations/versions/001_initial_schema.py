"""Initial schema — identity, repos, branches, content-addressed storage, jobs.

Revision ID: 001
Revises: None
Create Date: 2026-03-11
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Identity tables ---
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, unique=True, nullable=False),
        sa.Column("plan", sa.Text, nullable=False, server_default="free"),
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("email", sa.Text, unique=True, nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("password_hash", sa.Text, nullable=True),
        sa.Column("github_id", sa.BigInteger, unique=True, nullable=True),
        sa.Column("auth_provider", sa.Text, nullable=False, server_default="email"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "org_memberships",
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.Text, nullable=False, server_default="member"),
        sa.Column("invited_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("key_hash", sa.Text, unique=True, nullable=False),
        sa.Column("key_prefix", sa.Text, nullable=False),
        sa.Column("scopes", ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- Repositories ---
    op.create_table(
        "repositories",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("local_path", sa.Text, nullable=True),
        sa.Column("clone_url", sa.Text, nullable=True),
        sa.Column("default_branch", sa.Text, nullable=False, server_default="main"),
        sa.Column("language", sa.Text, nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        sa.Column("clone_path", sa.Text, nullable=True),
        sa.Column("disk_usage_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "name", name="uq_repo_org_name"),
    )

    op.create_table(
        "repo_credentials",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("repo_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cred_type", sa.Text, nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- Branches & content-addressed storage ---
    op.create_table(
        "branches",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("repo_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("parent_branch_id", UUID(as_uuid=True), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("head_commit", sa.Text, nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.UniqueConstraint("repo_id", "name", name="uq_branch_repo_name"),
    )

    op.create_table(
        "file_contents",
        sa.Column("sha256", sa.Text, primary_key=True),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("language", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "branch_files",
        sa.Column("branch_id", UUID(as_uuid=True), sa.ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("path", sa.Text, primary_key=True),
        sa.Column("content_sha", sa.Text, sa.ForeignKey("file_contents.sha256"), nullable=True),
        sa.Column("status", sa.Text, nullable=False),
    )

    op.create_table(
        "symbols",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("content_sha", sa.Text, sa.ForeignKey("file_contents.sha256"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("line_start", sa.Integer, nullable=True),
        sa.Column("line_end", sa.Integer, nullable=True),
        sa.Column("signature", sa.Text, nullable=True),
        sa.Column("exported", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_symbols_content_sha", "symbols", ["content_sha"])
    op.create_index("idx_symbols_name", "symbols", ["name"])

    op.create_table(
        "dependencies",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_sha", sa.Text, sa.ForeignKey("file_contents.sha256"), nullable=False),
        sa.Column("target_sha", sa.Text, sa.ForeignKey("file_contents.sha256"), nullable=False),
        sa.Column("dep_type", sa.Text, nullable=False),
        sa.Column("weight", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_deps_source", "dependencies", ["source_sha"])
    op.create_index("idx_deps_target", "dependencies", ["target_sha"])

    # --- Jobs & webhooks ---
    op.create_table(
        "indexing_jobs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("repo_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("job_type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("branch_name", sa.Text, nullable=True),
        sa.Column("progress", JSONB, nullable=False, server_default="{}"),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("arq_job_id", sa.Text, nullable=True),
    )

    op.create_table(
        "webhook_configs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("repo_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("secret_hash", sa.Text, nullable=False),
        sa.Column("events", ARRAY(sa.String), nullable=False, server_default="{push}"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- RLS policies ---
    op.execute("ALTER TABLE repositories ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY repo_org_isolation ON repositories
            USING (org_id = current_setting('app.current_org_id', true)::UUID)
    """)
    op.execute("ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY apikey_org_isolation ON api_keys
            USING (org_id = current_setting('app.current_org_id', true)::UUID)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS apikey_org_isolation ON api_keys")
    op.execute("ALTER TABLE api_keys DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS repo_org_isolation ON repositories")
    op.execute("ALTER TABLE repositories DISABLE ROW LEVEL SECURITY")

    op.drop_table("webhook_configs")
    op.drop_table("indexing_jobs")
    op.drop_index("idx_deps_target")
    op.drop_index("idx_deps_source")
    op.drop_table("dependencies")
    op.drop_index("idx_symbols_name")
    op.drop_index("idx_symbols_content_sha")
    op.drop_table("symbols")
    op.drop_table("branch_files")
    op.drop_table("file_contents")
    op.drop_table("branches")
    op.drop_table("repo_credentials")
    op.drop_table("repositories")
    op.drop_table("api_keys")
    op.drop_table("org_memberships")
    op.drop_table("users")
    op.drop_table("organizations")
