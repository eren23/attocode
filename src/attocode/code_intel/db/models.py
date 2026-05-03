"""SQLAlchemy ORM models for service mode."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from attocode.code_intel.db.base import Base, TimestampMixin, generate_uuid

try:
    from pgvector.sqlalchemy import Vector as _PgVector
except ImportError:
    _PgVector = None


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    memberships: Mapped[list[OrgMembership]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    repositories: Mapped[list[Repository]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    google_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    auth_provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="email")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    memberships: Mapped[list[OrgMembership]] = relationship(back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user", cascade="all, delete-orphan")


class OrgMembership(Base):
    __tablename__ = "org_memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="member")
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="api_keys")
    user: Mapped[User | None] = relationship(back_populates="api_keys")


class Repository(TimestampMixin, Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    clone_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_branch: Mapped[str] = mapped_column(Text, nullable=False, server_default="main")
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    index_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    clone_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    disk_usage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="repositories")
    credentials: Mapped[list[RepoCredential]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    branches: Mapped[list[Branch]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    webhook_configs: Mapped[list[WebhookConfig]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    indexing_jobs: Mapped[list[IndexingJob]] = relationship(back_populates="repository", cascade="all, delete-orphan")

    __table_args__ = (
        # Unique repo name within an org
        {"schema": None},
    )

    @classmethod
    def __declare_last__(cls) -> None:
        from sqlalchemy import UniqueConstraint
        if not any(isinstance(c, UniqueConstraint) for c in cls.__table__.constraints if hasattr(c, 'columns') and len(c.columns) == 2):
            pass  # UniqueConstraint added via migration


class RepoCredential(Base):
    __tablename__ = "repo_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    cred_type: Mapped[str] = mapped_column(Text, nullable=False)  # ssh_key|deploy_token|pat
    encrypted_value: Mapped[bytes] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    repository: Mapped[Repository] = relationship(back_populates="credentials")


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True)
    head_commit: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Monotonic version counter — incremented on every overlay write for consistency checks
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="branches")
    parent_branch: Mapped[Branch | None] = relationship(remote_side=[id])
    files: Mapped[list[BranchFile]] = relationship(back_populates="branch", cascade="all, delete-orphan")

    __table_args__ = (
        {"schema": None},
    )


class FileContent(Base):
    __tablename__ = "file_contents"

    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[bytes] = mapped_column(nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Supports storing summaries alongside code: source|summary_l1|summary_l2
    content_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="source")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BranchFile(Base):
    __tablename__ = "branch_files"

    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(Text, primary_key=True)
    content_sha: Mapped[str | None] = mapped_column(Text, ForeignKey("file_contents.sha256"), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # added|modified|deleted

    branch: Mapped[Branch] = relationship(back_populates="files")


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    content_sha: Mapped[str] = mapped_column(Text, ForeignKey("file_contents.sha256"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    line_start: Mapped[int | None] = mapped_column(nullable=True)
    line_end: Mapped[int | None] = mapped_column(nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    exported: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    # N5 fix: CASCADE on FK so deleting file_contents cleans up embeddings
    content_sha: Mapped[str] = mapped_column(Text, ForeignKey("file_contents.sha256", ondelete="CASCADE"), nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    # Migration 016: explicit model version + dim + provenance to replace the
    # old "silently wipe on dim change" flow. embedding_model_version defaults
    # to '' so pre-016 rows stay valid; new code should set it explicitly.
    embedding_model_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    chunk_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="file")
    # Vector column — added at runtime by ensure_vector_columns().
    # Dimension depends on the configured embedding model (384/768/1536).
    # Column is nullable: rows without vectors are pre-pgvector or pending re-embedding.
    if _PgVector is not None:
        vector = mapped_column(_PgVector(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Migration 016 replaced the old uq_embedding_content_model_chunk with
    # one that also includes embedding_model_version, so two versions of the
    # same model can coexist during a rotation.
    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "content_sha", "embedding_model", "embedding_model_version", "chunk_type",
            name="uq_embedding_content_model_version_chunk",
        ),
        __import__("sqlalchemy").Index(
            "ix_embeddings_model_version", "embedding_model", "embedding_model_version",
        ),
    )


class SymbolReference(Base):
    __tablename__ = "symbol_references"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    content_sha: Mapped[str] = mapped_column(Text, ForeignKey("file_contents.sha256", ondelete="CASCADE"), nullable=False)
    symbol_name: Mapped[str] = mapped_column(String(500), nullable=False)
    ref_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    line: Mapped[int] = mapped_column(nullable=False)
    # Qualified name of the function/method enclosing this reference. Empty
    # for top-level calls or when the parser could not attribute a caller.
    # Populated by extract_references() in full_indexer's third pass and
    # consumed by call-graph queries over HTTP-indexed repos.
    caller_qualified_name: Mapped[str] = mapped_column(
        String(500), nullable=False, server_default="",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Dependency(Base):
    __tablename__ = "dependencies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    source_sha: Mapped[str] = mapped_column(Text, ForeignKey("file_contents.sha256"), nullable=False)
    target_sha: Mapped[str] = mapped_column(Text, ForeignKey("file_contents.sha256"), nullable=False)
    # Types: import, call, type_ref, data_flow (extensible for future call graph)
    dep_type: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(nullable=False, server_default="1.0")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")


class Commit(Base):
    """DB-backed commit history for remote repos without bare clones."""
    __tablename__ = "commits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    oid: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str] = mapped_column(Text, nullable=False)
    author_email: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_oids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    branch_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="main")
    changed_files: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint("repo_id", "oid", name="uq_commits_repo_oid"),
    )


class CommitFileStat(Base):
    """Per-file statistics for each commit — lines added/removed, symbols changed."""
    __tablename__ = "commit_file_stats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    commit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("commits.id", ondelete="CASCADE"), nullable=False)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    lines_added: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lines_removed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    symbols_changed: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    change_type: Mapped[str] = mapped_column(Text, nullable=False)  # added|modified|deleted|renamed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        __import__("sqlalchemy").Index("ix_commit_file_stats_repo_path", "repo_id", "path"),
        __import__("sqlalchemy").Index("ix_commit_file_stats_commit_id", "commit_id"),
    )


class IndexingJob(Base):
    __tablename__ = "indexing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    branch_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    arq_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="indexing_jobs")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    repo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WebhookConfig(Base):
    __tablename__ = "webhook_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted webhook secret
    events: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{push}")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    repository: Mapped[Repository] = relationship(back_populates="webhook_configs")


class RevokedToken(Base):
    """JWT token blocklist for revocation."""
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(Text, primary_key=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BlameHunk(Base):
    """DB-backed blame data for remote repos."""
    __tablename__ = "blame_hunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    branch_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="main")
    commit_oid: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str] = mapped_column(Text, nullable=False)
    author_email: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Provenance(Base):
    """Provenance row for a derived code-intel artifact.

    Backed by migration 017. Embeddings carry provenance records that
    downstream tools (snapshot restore, orphan scan, model rotation
    audit) join against.
    """
    __tablename__ = "provenance"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid,
    )
    action_hash: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    input_blob_oid: Mapped[str] = mapped_column(Text, nullable=False)
    input_tree_oid: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexer_name: Mapped[str] = mapped_column(Text, nullable=False)
    indexer_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_digest: Mapped[str] = mapped_column(Text, nullable=False)
    produced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    producer_service: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="attocode-server",
    )
    producer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    producer_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("indexing_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    producer_host: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="",
    )
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        __import__("sqlalchemy").Index(
            "ix_provenance_action_hash", "action_hash",
        ),
        __import__("sqlalchemy").Index(
            "ix_provenance_input_blob", "input_blob_oid",
        ),
        __import__("sqlalchemy").Index(
            "ix_provenance_job", "producer_job_id",
        ),
        __import__("sqlalchemy").Index(
            "ix_provenance_indexer_version", "indexer_name", "indexer_version",
        ),
    )


class RepoSnapshot(Base):
    """A point-in-time manifest of a repo's code-intel state.

    Phase 3a delivers creation / listing / deletion over this table.
    Phase 3b will add an OCI adapter that pushes the same manifest +
    component rows as an artifact to a registry.
    """
    __tablename__ = "repo_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    manifest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    component_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    commit_oid: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    components: Mapped[list[RepoSnapshotComponent]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "repo_id", "name", name="uq_repo_snapshots_repo_name",
        ),
        __import__("sqlalchemy").Index(
            "ix_repo_snapshots_repo_created", "repo_id", "created_at",
        ),
        __import__("sqlalchemy").Index("ix_repo_snapshots_org", "org_id"),
    )


class RepoSnapshotComponent(Base):
    """One artifact entry inside a :class:`RepoSnapshot`.

    ``name`` is a logical identifier (``"content"`` / ``"symbols"`` /
    ``"embeddings.bge-small-en-v1.5"``), ``media_type`` is the OCI-shaped
    media type string, and ``digest`` is the SHA-256 content hash.
    """
    __tablename__ = "repo_snapshot_components"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repo_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    digest: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    snapshot: Mapped[RepoSnapshot] = relationship(back_populates="components")

    __table_args__ = (
        __import__("sqlalchemy").Index(
            "ix_repo_snapshot_components_snapshot", "snapshot_id",
        ),
        __import__("sqlalchemy").Index(
            "ix_repo_snapshot_components_digest", "digest",
        ),
    )
